#!/usr/bin/env python3
"""
DragonCP Queue Manager
Manages transfer queue with max concurrent transfers and destination validation
"""

import threading
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class QueueManager:
    """Manages transfer queue with destination tracking and concurrency limits"""
    
    # Maximum number of concurrent transfers allowed
    MAX_CONCURRENT_TRANSFERS = 3
    
    def __init__(self, transfer_model, socketio=None):
        self.transfer_model = transfer_model
        self.socketio = socketio
        self.coordinator = None  # Will be set by coordinator after initialization
        
        # Track active destinations to prevent duplicates
        # Format: {normalized_dest_path: transfer_id}
        self.active_destinations = {}
        
        # Track running transfers
        # Format: {transfer_id: dest_path}
        self.running_transfers = {}
        
        # Thread lock for thread-safe operations
        self.lock = threading.Lock()
        
        print(f"✅ QueueManager initialized (max concurrent: {self.MAX_CONCURRENT_TRANSFERS})")
    
    def set_coordinator(self, coordinator):
        """Set coordinator reference for starting queued transfers"""
        self.coordinator = coordinator
    
    def _normalize_path(self, path: str) -> str:
        """
        Normalize path for consistent comparison
        - Resolves to absolute path
        - Removes trailing slashes
        - Handles case sensitivity based on OS
        """
        # Remove trailing slashes
        path = path.rstrip('/\\')
        
        # Convert to absolute path if not already
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        
        # Normalize path separators
        path = os.path.normpath(path)
        
        # On Windows, make case-insensitive by converting to lowercase
        if os.name == 'nt':
            path = path.lower()
        
        return path
    
    def _check_duplicate_destination_internal(self, dest_path: str, proposed_transfer_id: str = None) -> Tuple[bool, Optional[str]]:
        """
        Internal method: Check for duplicate destination (lock must be held by caller)
        
        Args:
            dest_path: Destination path to check
            proposed_transfer_id: Transfer ID being checked (to exclude self)
        
        Returns:
            (True, transfer_id) if duplicate found
            (False, None) if no duplicate
        """
        normalized_dest = self._normalize_path(dest_path)
        
        # Check if this destination is already being synced
        if normalized_dest in self.active_destinations:
            existing_transfer_id = self.active_destinations[normalized_dest]
            
            # Don't mark as duplicate if it's the same transfer (e.g., restart)
            if existing_transfer_id != proposed_transfer_id:
                return (True, existing_transfer_id)
        
        return (False, None)
    
    def check_duplicate_destination(self, dest_path: str, proposed_transfer_id: str = None) -> Tuple[bool, Optional[str]]:
        """
        STRICT check: Returns (is_duplicate, existing_transfer_id)
        
        Args:
            dest_path: Destination path to check
            proposed_transfer_id: Transfer ID being checked (to exclude self)
        
        Returns:
            (True, transfer_id) if duplicate found
            (False, None) if no duplicate
        """
        with self.lock:
            return self._check_duplicate_destination_internal(dest_path, proposed_transfer_id)
    
    def can_start_transfer(self) -> bool:
        """Check if a new transfer can start (< MAX_CONCURRENT_TRANSFERS running)"""
        # Note: This method should ONLY be called when lock is already held by caller
        running_count = len(self.running_transfers)
        can_start = running_count < self.MAX_CONCURRENT_TRANSFERS
        
        print(f"📊 Queue status: {running_count}/{self.MAX_CONCURRENT_TRANSFERS} running, can_start={can_start}")
        
        return can_start
    
    def register_transfer(self, transfer_id: str, dest_path: str) -> Tuple[bool, str]:
        """
        Register a transfer for tracking
        
        Returns:
            (success, status) where status is 'running', 'queued', or 'duplicate'
        """
        with self.lock:
            normalized_dest = self._normalize_path(dest_path)
            
            # STRICT CHECK: Check for duplicate destination first (using internal method since we hold the lock)
            is_duplicate, existing_transfer = self._check_duplicate_destination_internal(dest_path, transfer_id)
            if is_duplicate:
                print(f"🚫 DUPLICATE DETECTED: Transfer {transfer_id} -> {dest_path}")
                print(f"   Existing transfer {existing_transfer} already syncing to this destination")
                return (False, 'duplicate')
            
            # Check if we can start immediately or need to queue
            if self.can_start_transfer():
                # Register as running
                self.active_destinations[normalized_dest] = transfer_id
                self.running_transfers[transfer_id] = normalized_dest
                print(f"✅ Transfer {transfer_id} registered as RUNNING -> {dest_path}")
                return (True, 'running')
            else:
                # Transfer should be queued
                # IMPORTANT: Still reserve the destination to prevent duplicate queued transfers
                self.active_destinations[normalized_dest] = transfer_id
                print(f"⏳ Transfer {transfer_id} should be QUEUED -> {dest_path}")
                print(f"   (Currently {len(self.running_transfers)}/{self.MAX_CONCURRENT_TRANSFERS} transfers running)")
                print(f"   Destination reserved to prevent duplicates")
                return (False, 'queued')
    
    def unregister_transfer(self, transfer_id: str):
        """
        Unregister a completed/failed/cancelled transfer and promote next queued transfer
        """
        with self.lock:
            # Remove from running transfers
            if transfer_id in self.running_transfers:
                dest_path = self.running_transfers[transfer_id]
                del self.running_transfers[transfer_id]
                
                # Remove from active destinations
                if dest_path in self.active_destinations:
                    if self.active_destinations[dest_path] == transfer_id:
                        del self.active_destinations[dest_path]
                
                print(f"✅ Transfer {transfer_id} unregistered")
                print(f"📊 Queue status: {len(self.running_transfers)}/{self.MAX_CONCURRENT_TRANSFERS} running")
            else:
                # Handle queued/cancelled transfers that never ran
                # Still need to remove from active_destinations
                for dest_path, tid in list(self.active_destinations.items()):
                    if tid == transfer_id:
                        del self.active_destinations[dest_path]
                        print(f"✅ Queued transfer {transfer_id} unregistered (freed destination)")
                        break
            
            # After unregistering, check if we can promote a queued transfer
            self._promote_next_queued_transfer()
    
    def _promote_next_queued_transfer(self):
        """
        Internal method to promote next queued transfer (should be called with lock held)
        """
        # Check if we have capacity
        if len(self.running_transfers) >= self.MAX_CONCURRENT_TRANSFERS:
            return
        
        # Get all queued transfers from database
        all_transfers = self.transfer_model.get_all()
        queued_transfers = [
            t for t in all_transfers 
            if t['status'] == 'queued'
        ]
        
        # Sort by creation time (oldest first)
        queued_transfers.sort(key=lambda t: t.get('created_at', t.get('start_time', '')))
        
        if not queued_transfers:
            return
        
        # Try to promote the next queued transfer
        for queued_transfer in queued_transfers:
            transfer_id = queued_transfer['transfer_id']
            dest_path = queued_transfer['dest_path']
            
            # Re-check for duplicate destination (using internal method since we hold the lock)
            is_duplicate, existing_transfer_id = self._check_duplicate_destination_internal(dest_path, transfer_id)
            if is_duplicate:
                # Mark as duplicate now - get better message with existing transfer details
                existing_transfer = self.transfer_model.get(existing_transfer_id)
                if existing_transfer:
                    existing_title = existing_transfer.get('parsed_title') or existing_transfer.get('folder_name') or 'Unknown'
                    if existing_transfer.get('season_name'):
                        existing_info = f"{existing_title} - {existing_transfer['season_name']}"
                    else:
                        existing_info = existing_title
                    duplicate_message = f'Duplicate: Another transfer "{existing_info}" is already syncing to this destination'
                else:
                    duplicate_message = f'Duplicate: Another transfer is already syncing to: {dest_path}'
                
                print(f"🚫 Queued transfer {transfer_id} is now DUPLICATE (destination taken by {existing_transfer_id})")
                self.transfer_model.update(transfer_id, {
                    'status': 'duplicate',
                    'progress': duplicate_message,
                    'end_time': datetime.now().isoformat()
                })
                continue
            
            # Promote this transfer
            normalized_dest = self._normalize_path(dest_path)
            self.active_destinations[normalized_dest] = transfer_id
            self.running_transfers[transfer_id] = normalized_dest
            
            print(f"🎉 PROMOTED: Transfer {transfer_id} from queue")
            print(f"📊 Queue status: {len(self.running_transfers)}/{self.MAX_CONCURRENT_TRANSFERS} running")
            
            # Emit WebSocket event if available
            if self.socketio:
                self.socketio.emit('transfer_promoted', {
                    'transfer_id': transfer_id,
                    'message': 'Transfer promoted from queue'
                })
            
            # Start the actual transfer by calling the coordinator
            # The coordinator will update status from 'queued' to 'pending' then to 'running'
            if self.coordinator:
                import threading
                # Start in a separate thread to avoid blocking
                threading.Thread(
                    target=self.coordinator.start_queued_transfer,
                    args=(transfer_id,),
                    daemon=True
                ).start()
            
            # Only promote one transfer at a time
            break
    
    def get_queue_status(self) -> Dict:
        """Get current queue status"""
        with self.lock:
            # Get all transfers from database
            all_transfers = self.transfer_model.get_all()
            
            running_transfers = [
                t for t in all_transfers 
                if t['status'] == 'running'
            ]
            
            queued_transfers = [
                t for t in all_transfers 
                if t['status'] == 'queued'
            ]
            
            return {
                'max_concurrent': self.MAX_CONCURRENT_TRANSFERS,
                'running_count': len(running_transfers),
                'queued_count': len(queued_transfers),
                'available_slots': max(0, self.MAX_CONCURRENT_TRANSFERS - len(running_transfers)),
                'running_transfer_ids': [t['transfer_id'] for t in running_transfers],
                'queued_transfer_ids': [t['transfer_id'] for t in queued_transfers],
                'active_destinations': list(self.active_destinations.values())
            }
    
    def force_unregister_stale_transfers(self):
        """
        Cleanup method to remove stale entries from tracking
        Should be called on app startup or periodically
        """
        with self.lock:
            all_transfers = self.transfer_model.get_all()
            
            # Build set of actually running transfer IDs
            actually_running = {
                t['transfer_id'] for t in all_transfers 
                if t['status'] == 'running'
            }
            
            # Remove any tracked transfers that are not actually running
            stale_transfers = []
            for transfer_id in list(self.running_transfers.keys()):
                if transfer_id not in actually_running:
                    stale_transfers.append(transfer_id)
            
            for transfer_id in stale_transfers:
                dest_path = self.running_transfers[transfer_id]
                del self.running_transfers[transfer_id]
                
                if dest_path in self.active_destinations:
                    if self.active_destinations[dest_path] == transfer_id:
                        del self.active_destinations[dest_path]
                
                print(f"🧹 Cleaned up stale transfer tracking: {transfer_id}")
            
            if stale_transfers:
                print(f"✅ Removed {len(stale_transfers)} stale transfer entries")
                # Try to promote queued transfers after cleanup
                self._promote_next_queued_transfer()

