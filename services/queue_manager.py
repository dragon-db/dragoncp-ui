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

    def _is_path_queue_transfer(self, transfer: Dict) -> bool:
        """Determine whether a queued transfer is waiting on a destination-path conflict."""
        queue_reason = (transfer.get('queue_reason') or '').lower()
        if queue_reason:
            return queue_reason == 'path'

        progress_msg = (transfer.get('progress') or '').lower()
        return (
            'same destination' in progress_msg or
            'same path' in progress_msg or
            ('waiting for' in progress_msg and 'complete' in progress_msg)
        )

    def _register_running_transfer_internal(self, transfer_id: str, dest_path: str,
                                            enforce_capacity: bool = True) -> Tuple[bool, str]:
        """Reserve a destination and register a transfer as running (lock must be held)."""
        normalized_dest = self._normalize_path(dest_path)
        existing_transfer_id = self.active_destinations.get(normalized_dest)

        if existing_transfer_id and existing_transfer_id != transfer_id:
            return (False, 'duplicate')

        existing_dest = self.running_transfers.get(transfer_id)
        if existing_dest == normalized_dest:
            self.active_destinations[normalized_dest] = transfer_id
            return (True, 'running')

        if enforce_capacity and transfer_id not in self.running_transfers and not self.can_start_transfer():
            return (False, 'capacity')

        if existing_dest and existing_dest in self.active_destinations:
            if self.active_destinations[existing_dest] == transfer_id:
                del self.active_destinations[existing_dest]

        self.active_destinations[normalized_dest] = transfer_id
        self.running_transfers[transfer_id] = normalized_dest
        return (True, 'running')

    def ensure_running_transfer_registered(self, transfer_id: str, dest_path: str,
                                           enforce_capacity: bool = True) -> Tuple[bool, str]:
        """Ensure a transfer is represented in in-memory running state before rsync starts."""
        with self.lock:
            return self._register_running_transfer_internal(
                transfer_id,
                dest_path,
                enforce_capacity=enforce_capacity
            )

    def _restore_queued_reservations_internal(self, queued_records: List[Dict]) -> int:
        """Restore one queued reservation per destination path (lock must be held)."""
        restored_count = 0

        queued_records.sort(key=lambda t: t.get('created_at', t.get('start_time', '')))

        for transfer in queued_records:
            transfer_id = transfer['transfer_id']
            dest_path = transfer.get('dest_path')
            if not dest_path:
                continue

            normalized_dest = self._normalize_path(dest_path)
            if normalized_dest in self.active_destinations:
                continue

            self.active_destinations[normalized_dest] = transfer_id
            restored_count += 1

        return restored_count
    
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
                registered, status = self._register_running_transfer_internal(
                    transfer_id,
                    dest_path,
                    enforce_capacity=False
                )
                if registered:
                    print(f"✅ Transfer {transfer_id} registered as RUNNING -> {dest_path}")
                    return (True, status)

                print(f"⚠️  Failed to register transfer {transfer_id} as running: {status}")
                return (False, status)
            else:
                # Transfer should be queued
                # IMPORTANT: Still reserve the destination to prevent duplicate queued transfers
                self.active_destinations[normalized_dest] = transfer_id
                print(f"⏳ Transfer {transfer_id} should be QUEUED -> {dest_path}")
                print(f"   (Currently {len(self.running_transfers)}/{self.MAX_CONCURRENT_TRANSFERS} transfers running)")
                print(f"   Destination reserved to prevent duplicates")
                return (False, 'queued')
    
    def unregister_transfer(self, transfer_id: str, dest_path: str = None):
        """
        Unregister a completed/failed/cancelled transfer and promote next queued transfer
        
        Args:
            transfer_id: The transfer ID to unregister
            dest_path: The destination path (used for path-specific queue promotion)
        """
        completed_dest_path = dest_path  # Track for path-specific promotion
        
        with self.lock:
            # Remove from running transfers
            if transfer_id in self.running_transfers:
                stored_dest_path = self.running_transfers[transfer_id]
                if not completed_dest_path:
                    completed_dest_path = stored_dest_path
                del self.running_transfers[transfer_id]
                
                # Remove from active destinations
                if stored_dest_path in self.active_destinations:
                    if self.active_destinations[stored_dest_path] == transfer_id:
                        del self.active_destinations[stored_dest_path]
                
                print(f"✅ Transfer {transfer_id} unregistered")
                print(f"📊 Queue status: {len(self.running_transfers)}/{self.MAX_CONCURRENT_TRANSFERS} running")
            else:
                # Handle queued/cancelled transfers that never ran
                # Still need to remove from active_destinations
                for stored_dest_path, tid in list(self.active_destinations.items()):
                    if tid == transfer_id:
                        if not completed_dest_path:
                            completed_dest_path = stored_dest_path
                        del self.active_destinations[stored_dest_path]
                        print(f"✅ Queued transfer {transfer_id} unregistered (freed destination)")
                        break
            
            # After unregistering, promote queued transfers
            # Priority: Path-specific queue first, then general slot queue
            if completed_dest_path:
                self._promote_same_path_queued(completed_dest_path)
            
            # Then check for general slot-based queue promotion
            self._promote_next_queued_transfer()
    
    def _promote_same_path_queued(self, dest_path: str):
        """
        Internal method to promote QUEUED_PATH transfers for a specific destination path
        
        This is called when a transfer for a specific path completes. It looks for
        queued transfers waiting for this exact path, and promotes ONE of them
        (oldest first) directly into the normal queued-transfer start flow.
        
        Args:
            dest_path: The destination path that just became available
        """
        if not self.coordinator:
            print(f"⏸️  Cannot promote same-path queued transfers for {dest_path} without coordinator")
            return
        
        # Check if we have capacity for another transfer
        if len(self.running_transfers) >= self.MAX_CONCURRENT_TRANSFERS:
            print(f"⏸️  Path {dest_path} freed, but max transfers ({self.MAX_CONCURRENT_TRANSFERS}) reached")
            return
        
        # Get all queued transfers from database (both transfer records and webhook notifications)
        all_transfers = self.transfer_model.get_all()
        
        # Filter for transfers with status='queued' and same dest_path
        queued_path_transfers = [
            t for t in all_transfers
            if t['status'] == 'queued' and self._normalize_path(t.get('dest_path', '')) == self._normalize_path(dest_path)
        ]
        
        # Prefer explicit/fallback path-queue entries first, then oldest first.
        queued_path_transfers.sort(
            key=lambda t: (
                0 if self._is_path_queue_transfer(t) else 1,
                t.get('created_at', t.get('start_time', ''))
            )
        )
        
        if not queued_path_transfers:
            print(f"✅ No QUEUED_PATH transfers found for {dest_path}")
            return
        
        # Promote the oldest one
        queued_transfer = queued_path_transfers[0]
        transfer_id = queued_transfer['transfer_id']
        
        # Re-check for duplicate destination (safety check)
        is_duplicate, existing_transfer_id = self._check_duplicate_destination_internal(dest_path, transfer_id)
        if is_duplicate:
            print(f"⚠️  Path {dest_path} still has active transfer {existing_transfer_id}, cannot promote yet")
            return

        registered, register_status = self._register_running_transfer_internal(
            transfer_id,
            dest_path,
            enforce_capacity=True
        )
        if not registered:
            print(f"⚠️  Could not reserve queue state for promoted path transfer {transfer_id}: {register_status}")
            return

        print(f"🎉 PROMOTING QUEUED_PATH: Transfer {transfer_id} for path {dest_path}")
        
        # Emit WebSocket event if available
        if self.socketio:
            self.socketio.emit('transfer_promoted', {
                'transfer_id': transfer_id,
                'message': f'Transfer promoted from path queue for {dest_path}',
                'queue_type': 'path'
            })
        
        # Start the transfer by calling the coordinator
        if self.coordinator:
            import threading
            threading.Thread(
                target=self.coordinator.start_queued_transfer,
                args=(transfer_id,),
                daemon=True
            ).start()
    
    def _promote_next_queued_transfer(self):
        """
        Internal method to promote next general queued transfer (should be called with lock held)
        
        This promotes transfers in QUEUED_SLOT state (waiting for any slot to free up).
        It's called after path-specific promotion to fill remaining capacity.
        """
        if not self.coordinator:
            print("⏸️  Cannot promote queued transfers without coordinator")
            return

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
            is_path_queue = self._is_path_queue_transfer(queued_transfer)
            
            # Re-check for duplicate destination (using internal method since we hold the lock)
            is_duplicate, existing_transfer_id = self._check_duplicate_destination_internal(dest_path, transfer_id)
            if is_duplicate:
                if is_path_queue:
                    # This is a QUEUED_PATH transfer waiting for this specific path to complete
                    # Don't mark as duplicate - just skip it and keep it in queue
                    # It will be promoted by _promote_same_path_queued() when the path completes
                    print(f"⏭️  Skipping QUEUED_PATH transfer {transfer_id} (path {dest_path} still occupied by {existing_transfer_id})")
                    continue
                else:
                    # This is a QUEUED_SLOT transfer that now encounters a path conflict
                    # Convert it to QUEUED_PATH instead of marking as duplicate
                    existing_transfer = self.transfer_model.get(existing_transfer_id)
                    if existing_transfer:
                        existing_title = existing_transfer.get('parsed_title') or existing_transfer.get('folder_name') or 'Unknown'
                        if existing_transfer.get('season_name'):
                            existing_info = f"{existing_title} - {existing_transfer['season_name']}"
                        else:
                            existing_info = existing_title
                        queue_message = f'Queued: Waiting for "{existing_info}" to complete (same destination path)'
                    else:
                        queue_message = f'Queued: Waiting for path to be available: {dest_path}'
                    
                    print(f"🔄 Converting QUEUED_SLOT → QUEUED_PATH for {transfer_id} (destination taken by {existing_transfer_id})")
                    self.transfer_model.update(transfer_id, {
                        'queue_reason': 'path',  # Convert from 'slot' to 'path'
                        'progress': queue_message
                    })
                    
                    # Update webhook notification status from QUEUED_SLOT to QUEUED_PATH
                    # Get the transfer record to find the notification(s)
                    transfer = self.transfer_model.get(transfer_id)
                    if transfer and transfer.get('media_type') in ['tvshows', 'anime', 'series']:
                        # Use the already-initialized series_webhook_model from coordinator
                        if self.coordinator and self.coordinator.series_webhook_model:
                            updated = self.coordinator.series_webhook_model.update_notifications_by_transfer_id(
                                transfer_id,
                                {'status': 'QUEUED_PATH'}
                            )
                            if updated:
                                print(f"   ✅ Updated {updated} webhook notification(s) to QUEUED_PATH")
                    
                    # Skip promotion for now - will be picked up by _promote_same_path_queued()
                    continue
            
            # Promote this transfer
            registered, register_status = self._register_running_transfer_internal(
                transfer_id,
                dest_path,
                enforce_capacity=True
            )
            if not registered:
                print(f"⚠️  Could not reserve queue state for promoted transfer {transfer_id}: {register_status}")
                continue

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
        Cleanup method to remove stale entries from tracking and rebuild queue state.
        Should be called on app startup or periodically.
        """
        with self.lock:
            all_transfers = self.transfer_model.get_all()
            running_records = [
                t for t in all_transfers
                if t['status'] == 'running'
            ]
            queued_records = [
                t for t in all_transfers
                if t['status'] == 'queued'
            ]

            # Build set of actually running transfer IDs
            actually_running = {
                t['transfer_id'] for t in running_records
            }
            
            # Remove any tracked transfers that are not actually running
            stale_transfers = []
            for transfer_id in list(self.running_transfers.keys()):
                if transfer_id not in actually_running:
                    stale_transfers.append(transfer_id)
            
            for transfer_id in stale_transfers:
                dest_path = self.running_transfers[transfer_id]
                print(f"🧹 Cleaned up stale transfer tracking: {transfer_id}")

            # Rebuild queue state from database so restart recovery preserves
            # running reservations and queued destination ownership.
            self.running_transfers = {}
            self.active_destinations = {}

            restored_count = 0
            for transfer in running_records:
                transfer_id = transfer['transfer_id']
                dest_path = transfer.get('dest_path')
                if not dest_path:
                    continue

                registered, status = self._register_running_transfer_internal(
                    transfer_id,
                    dest_path,
                    enforce_capacity=False
                )
                if registered:
                    restored_count += 1
                else:
                    print(f"⚠️  Could not restore running transfer {transfer_id}: {status}")

            restored_queued_count = self._restore_queued_reservations_internal(queued_records)

            if stale_transfers:
                print(f"✅ Removed {len(stale_transfers)} stale transfer entries")

            if restored_count:
                print(f"🔄 Restored {restored_count} running transfer reservation(s) from database")

            if restored_queued_count:
                print(f"🧾 Restored {restored_queued_count} queued destination reservation(s) from database")

            while self.coordinator and len(self.running_transfers) < self.MAX_CONCURRENT_TRANSFERS:
                running_before = len(self.running_transfers)
                self._promote_next_queued_transfer()
                if len(self.running_transfers) == running_before:
                    break
