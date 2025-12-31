#!/usr/bin/env python3
"""
DragonCP Backup Service
Handles backup restore, delete, reindex, and context-aware file matching operations
"""

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class BackupService:
    """Service for backup operations and context-aware restoration"""
    
    def __init__(self, config, db_manager, backup_model, transfer_model, socketio=None):
        self.config = config
        self.db = db_manager
        self.backup_model = backup_model
        self.transfer_model = transfer_model
        self.socketio = socketio
    
    def finalize_backup_for_transfer(self, transfer_id: str):
        """Scan dynamic backup dir for this transfer and record files in DB if any."""
        transfer = self.transfer_model.get(transfer_id)
        if not transfer:
            return
        dynamic_backup_dir = self._get_dynamic_backup_dir(transfer)
        if not os.path.exists(dynamic_backup_dir):
            return
        # Walk and collect files
        total_size = 0
        files = []
        for root, dirs, filenames in os.walk(dynamic_backup_dir):
            for fname in filenames:
                # skip rsync temp/partial metadata if any other than files within .rsync-partial
                if fname.startswith('.') and os.path.basename(root) == '.rsync-partial':
                    continue
                full_path = os.path.join(root, fname)
                try:
                    rel_path = os.path.relpath(full_path, dynamic_backup_dir)
                except Exception:
                    rel_path = fname
                try:
                    stat = os.stat(full_path)
                    size = stat.st_size
                    mtime = int(stat.st_mtime)
                except Exception:
                    size = 0
                    mtime = 0
                total_size += size
                original_path = os.path.join(transfer['dest_path'], rel_path)
                # Detect media context for smarter restore
                ctx = self._detect_context_from_filename(
                    rel_path,
                    transfer.get('media_type') or '',
                    transfer.get('folder_name') or '',
                    transfer.get('season_name') or None
                )
                files.append({
                    'relative_path': rel_path.replace('\\', '/'),
                    'original_path': original_path.replace('\\', '/'),
                    'file_size': size,
                    'modified_time': mtime,
                    'context_media_type': ctx.get('context_media_type'),
                    'context_title': ctx.get('context_title'),
                    'context_release_year': ctx.get('context_release_year'),
                    'context_series_title': ctx.get('context_series_title'),
                    'context_season': ctx.get('context_season'),
                    'context_episode': ctx.get('context_episode'),
                    'context_absolute': ctx.get('context_absolute'),
                    'context_key': ctx.get('context_key'),
                    'context_display': ctx.get('context_display'),
                })
        file_count = len(files)
        if file_count == 0:
            return
        backup_record = {
            'backup_id': transfer_id,
            'transfer_id': transfer_id,
            'media_type': transfer.get('media_type'),
            'folder_name': transfer.get('folder_name'),
            'season_name': transfer.get('season_name'),
            'source_path': transfer.get('source_path'),
            'dest_path': transfer.get('dest_path'),
            'backup_path': dynamic_backup_dir,
            'file_count': file_count,
            'total_size': total_size,
            'status': 'ready',
            'created_at': datetime.utcnow().isoformat() + 'Z'  # Explicit UTC timestamp
        }
        self.backup_model.create_or_replace_backup(backup_record)
        # Replace existing file list if any
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM backup_file WHERE backup_id = ?', (transfer_id,))
            conn.commit()
        self.backup_model.add_backup_files(transfer_id, files)

    def restore_backup(self, backup_id: str, files: List[str] = None) -> Tuple[bool, str]:
        """Context-aware restore using backup context to safely replace matching media.
        If files is provided, it should be a list of relative paths to restore selectively.
        Steps:
          - Plan matching dest files by context
          - Pre-delete only the context-matched dest file(s)
          - Copy selected backup files into destination (rsync files-from)
        """
        try:
            record = self.backup_model.get(backup_id)
            if not record:
                return False, 'Backup not found'
            backup_path = record['backup_path']
            dest_path = record['dest_path']
            if not os.path.exists(backup_path):
                return False, 'Backup directory not found on disk'
            if not os.path.exists(dest_path):
                try:
                    # Check TEST_MODE before creating restore destination directory
                    if os.environ.get('TEST_MODE', '0') == '1':
                        print(f"🧪 TEST_MODE: Would create restore destination directory: {dest_path}")
                    else:
                        os.makedirs(dest_path, exist_ok=True)
                except Exception as e:
                    return False, f'Failed to create destination: {e}'

            # Build plan
            plan = self.plan_context_restore(backup_id, files)
            operations = plan.get('operations', [])
            if not operations:
                return False, 'No matching files to restore for the selected items'

            # Create a synthetic restore transfer for UI progress/logs
            restore_transfer_id = f"restore_{backup_id}_{int(datetime.now().timestamp())}"
            # Create DB record for visibility
            self.transfer_model.create({
                'transfer_id': restore_transfer_id,
                'media_type': record.get('media_type') or 'backup',
                'folder_name': record.get('folder_name') or '',
                'season_name': record.get('season_name'),
                'source_path': backup_path,
                'dest_path': dest_path,
                'operation_type': 'restore',
                'status': 'running',
                'rsync_process_id': None
            })

            # Emit initial plan summary via socket (include context)
            try:
                if self.socketio:
                    self.socketio.emit('transfer_progress', {
                        'transfer_id': restore_transfer_id,
                        'progress': f"Planning restore: {len(operations)} item(s)",
                        'logs': [
                            f"Plan: {op.get('context_display') or op.get('backup_relative')} -> replace {op['target_delete']}"
                            for op in operations
                        ][:100],
                        'log_count': min(len(operations), 100),
                        'status': 'running'
                    })
            except Exception:
                pass

            # Pre-delete target files with context logging. Show context on next line
            deleted = 0
            for op in operations:
                target = op.get('target_delete')
                if target and os.path.exists(target):
                    try:
                        # Check TEST_MODE before deleting files
                        if os.environ.get('TEST_MODE', '0') == '1':
                            print(f"🧪 TEST_MODE: Would delete file: {target}")
                            ctx_disp = op.get('context_display') or op.get('backup_relative')
                            self.transfer_model.add_log(restore_transfer_id, f"[DRY-RUN] Would delete: {target}\nContext: {ctx_disp}")
                            deleted += 1  # Count as if deleted for simulation
                        else:
                            os.remove(target)
                            deleted += 1
                            ctx_disp = op.get('context_display') or op.get('backup_relative')
                            self.transfer_model.add_log(restore_transfer_id, f"Deleted: {target}\nContext: {ctx_disp}")
                    except Exception as e:
                        self.transfer_model.add_log(restore_transfer_id, f"ERROR deleting {target}: {e}")

            # Prepare rsync with selected files
            rsync_cmd = [
                'rsync', '-av', '--progress', '--size-only', '--no-perms', '--no-owner', '--no-group', '--no-motd'
            ]
            
            # Add --dry-run flag when TEST_MODE is enabled
            if os.environ.get('TEST_MODE', '0') == '1':
                rsync_cmd.append("--dry-run")
                print("🧪 TEST_MODE enabled - rsync restore will run in dry-run mode (no actual file transfers)")
            temp_list_file = None
            # Use backup_relative from operations to ensure we copy exactly those files
            selected_relatives = [op['backup_relative'] for op in operations]
            if selected_relatives:
                # Check TEST_MODE before creating temporary files
                if os.environ.get('TEST_MODE', '0') == '1':
                    print(f"🧪 TEST_MODE: Would create temporary file list with {len(selected_relatives)} files")
                    # In test mode, create a dummy path but don't create the actual file
                    temp_path = f"/tmp/test_mode_dummy_file_{len(selected_relatives)}.txt"
                    rsync_cmd.extend(['-r', f"--files-from={temp_path}"])
                    temp_list_file = None  # Don't track for cleanup in test mode
                else:
                    temp_fd, temp_path = tempfile.mkstemp(prefix='backup_files_', text=True)
                    os.close(temp_fd)
                    with open(temp_path, 'w', newline='\n') as f:
                        for p in selected_relatives:
                            f.write(p.strip().lstrip('/').replace('\\', '/') + '\n')
                    rsync_cmd.extend(['-r', f"--files-from={temp_path}"])
                    temp_list_file = temp_path

            # Source and destination
            rsync_cmd.extend([f"{backup_path}/", f"{dest_path}/"]) 
            print(f"🔄 Context-aware restore {backup_id}: {' '.join(rsync_cmd)}")
            result = subprocess.run(rsync_cmd, capture_output=True, text=True)
            # Log copy actions per operation (best-effort), include context on next line
            for op in operations:
                ctx_disp = op.get('context_display') or op.get('backup_relative')
                self.transfer_model.add_log(restore_transfer_id, f"Copied: {op.get('backup_relative')} -> {op.get('copy_to')}\nContext: {ctx_disp}")
            if temp_list_file and os.path.exists(temp_list_file):
                try:
                    # Check TEST_MODE before removing temporary file
                    if os.environ.get('TEST_MODE', '0') == '1':
                        print(f"🧪 TEST_MODE: Would remove temporary file: {temp_list_file}")
                    else:
                        os.remove(temp_list_file)
                except Exception:
                    pass

            if result.returncode == 0:
                self.transfer_model.update(restore_transfer_id, {
                    'status': 'completed',
                    'progress': f"Restore completed: {len(operations)} item(s), deleted {deleted}",
                    'end_time': datetime.now().isoformat()
                })
                # Emit completion
                try:
                    if self.socketio:
                        self.socketio.emit('transfer_complete', {
                            'transfer_id': restore_transfer_id,
                            'status': 'completed',
                            'message': f"Restore completed: {len(operations)} items",
                            'logs': self.transfer_model.get(restore_transfer_id).get('logs', [])[-100:],
                            'log_count': len(self.transfer_model.get(restore_transfer_id).get('logs', []))
                        })
                except Exception:
                    pass
                self.backup_model.update(backup_id, {'status': 'restored', 'restored_at': datetime.now().isoformat()})
                return True, 'Restore completed successfully'
            else:
                self.transfer_model.update(restore_transfer_id, {
                    'status': 'failed',
                    'progress': f"Restore failed: {result.stderr or result.stdout}",
                    'end_time': datetime.now().isoformat()
                })
                try:
                    if self.socketio:
                        self.socketio.emit('transfer_complete', {
                            'transfer_id': restore_transfer_id,
                            'status': 'failed',
                            'message': f"Restore failed: {result.stderr or result.stdout}",
                            'logs': self.transfer_model.get(restore_transfer_id).get('logs', [])[-100:],
                            'log_count': len(self.transfer_model.get(restore_transfer_id).get('logs', []))
                        })
                except Exception:
                    pass
                return False, f"Restore failed: {result.stderr or result.stdout}"
        except Exception as e:
            return False, str(e)

    def delete_backup(self, backup_id: str, delete_files: bool = True) -> Tuple[bool, str]:
        """Delete a backup record and optionally remove backup files"""
        try:
            record = self.backup_model.get(backup_id)
            if not record:
                return False, 'Backup not found'
            # This method now only deletes both by default; for independent controls, use delete_backup_options
            if delete_files:
                bpath = record.get('backup_path')
                if bpath and os.path.exists(bpath):
                    try:
                        # Check TEST_MODE before removing backup directory
                        if os.environ.get('TEST_MODE', '0') == '1':
                            print(f"🧪 TEST_MODE: Would remove backup directory: {bpath}")
                        else:
                            shutil.rmtree(bpath)
                    except Exception as e:
                        return False, f'Failed to remove backup directory: {e}'
            with self.db.get_connection() as conn:
                conn.execute('DELETE FROM backup_file WHERE backup_id = ?', (backup_id,))
                conn.commit()
            self.backup_model.update(backup_id, {'status': 'deleted'})
            return True, 'Backup deleted'
        except Exception as e:
            return False, str(e)

    def delete_backup_options(self, backup_id: str, delete_record: bool, delete_files: bool) -> Tuple[bool, str]:
        """Delete backup files and/or DB record independently."""
        try:
            record = self.backup_model.get(backup_id)
            if not record:
                return False, 'Backup not found'
            if delete_files:
                bpath = record.get('backup_path')
                if bpath and os.path.exists(bpath):
                    try:
                        # Check TEST_MODE before removing backup directory
                        if os.environ.get('TEST_MODE', '0') == '1':
                            print(f"🧪 TEST_MODE: Would remove backup directory: {bpath}")
                        else:
                            shutil.rmtree(bpath)
                    except Exception as e:
                        return False, f'Failed to remove backup directory: {e}'
            if delete_record:
                # Remove file rows and high-level record
                with self.db.get_connection() as conn:
                    conn.execute('DELETE FROM backup_file WHERE backup_id = ?', (backup_id,))
                    conn.commit()
                deleted = self.backup_model.delete(backup_id)
                return True, 'Backup record deleted' if deleted else 'Backup record deletion attempted'
            else:
                # Keep record, update status based on files presence
                new_status = 'ready'
                if delete_files:
                    new_status = 'files_removed'
                self.backup_model.update(backup_id, {'status': new_status})
                return True, 'Backup files removed' if delete_files else 'No changes'
        except Exception as e:
            return False, str(e)

    def plan_context_restore(self, backup_id: str, files: List[str] = None) -> Dict:
        """Plan a context-aware restore: return mapping of which dest files will be replaced by which backups.
        Returns dict with operations: [{backup_relative, backup_full, target_delete, copy_to, context_display}]"""
        record = self.backup_model.get(backup_id)
        if not record:
            return {'operations': []}
        backup_path = record['backup_path']
        dest_path = record['dest_path'] or ''
        # Load files with context
        file_rows = self.backup_model.get_files(backup_id)
        if files:
            selected_set = set([p.strip().lstrip('/').replace('\\', '/') for p in files])
            file_rows = [r for r in file_rows if r.get('relative_path') in selected_set]
        ops = []
        for row in file_rows:
            rel = row.get('relative_path')
            backup_full = os.path.join(backup_path, rel)
            copy_to = row.get('original_path') or os.path.join(dest_path, rel)
            # Determine target delete by scanning dest_path for context match
            target = self._find_dest_match_for_context(dest_path, row, fallback_path=copy_to)
            ops.append({
                'backup_relative': rel,
                'backup_full': backup_full,
                'copy_to': copy_to,
                'target_delete': target,
                'context_display': row.get('context_display') or rel
            })
        return {'operations': ops}

    def reindex_backups(self) -> Tuple[int, int]:
        """Scan BACKUP_PATH for existing dynamic backup dirs and import missing ones.
        Returns: (num_imported, num_skipped)
        """
        backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
        imported = 0
        skipped = 0
        if not os.path.isdir(backup_base):
            return (0, 0)
        # Pattern: <safe_folder>_<transfer_id>
        for name in os.listdir(backup_base):
            full = os.path.join(backup_base, name)
            if not os.path.isdir(full):
                continue
            # parse pattern: <safe_folder>_<transfer_XXXXXXXX> (preferred) or <safe_folder>_<XXXXXXXX>
            suffix = None
            safe_folder = None
            if '_' in name:
                idx = name.rfind('_')
                safe_folder = name[:idx]
                suffix = name[idx+1:]
            if not suffix:
                skipped += 1
                continue
            if suffix.startswith('transfer_'):
                proper_id = suffix
                fallback_id = suffix
            else:
                # numeric or other suffix: assume it is timestamp, build proper transfer id
                proper_id = f"transfer_{suffix}"
                fallback_id = suffix
            # already imported with proper id?
            existing_proper = self.backup_model.get(proper_id)
            if existing_proper:
                skipped += 1
                continue
            existing_fallback = None
            if fallback_id != proper_id:
                existing_fallback = self.backup_model.get(fallback_id)
            # compute dest_path if possible from a transfer record
            t = self.transfer_model.get(proper_id)
            if t:
                dest_path = t.get('dest_path')
                media_type = t.get('media_type')
                folder_name = t.get('folder_name')
                season_name = t.get('season_name')
                source_path = t.get('source_path')
            else:
                # Unknown transfer; best-effort import with dest unknown
                dest_path = ''
                media_type = None
                # derive a readable title from safe folder (underscores -> spaces)
                folder_name = (safe_folder or '').replace('_', ' ').strip() or None
                season_name = None
                source_path = ''
            # Walk files for stats
            total_size = 0
            files = []
            # Determine created_at from directory mtime (use UTC to match SQLite CURRENT_TIMESTAMP)
            try:
                dir_stat = os.stat(full)
                # Convert to UTC to match SQLite's CURRENT_TIMESTAMP behavior
                created_utc = datetime.utcfromtimestamp(dir_stat.st_mtime)
                created_iso = created_utc.isoformat() + 'Z'  # Add Z to indicate UTC
            except Exception:
                created_iso = None
            for root, dirs, filenames in os.walk(full):
                for fname in filenames:
                    if fname.startswith('.') and os.path.basename(root) == '.rsync-partial':
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        stat = os.stat(fpath)
                        size = stat.st_size
                        mtime = int(stat.st_mtime)
                    except Exception:
                        size = 0
                        mtime = 0
                    total_size += size
                    rel = os.path.relpath(fpath, full)
                    original_path = os.path.join(dest_path, rel) if dest_path else rel
                    # Derive media_type for context detection priority
                    inferred_media_type = media_type or ('movies' if (safe_folder or '').lower() in ['movies', 'movie'] else None)
                    ctx = self._detect_context_from_filename(
                        rel,
                        inferred_media_type or (media_type or ''),
                        folder_name or safe_folder or '',
                        season_name
                    )
                    files.append({
                        'relative_path': rel.replace('\\', '/'),
                        'original_path': original_path.replace('\\', '/'),
                        'file_size': size,
                        'modified_time': mtime,
                        'context_media_type': ctx.get('context_media_type'),
                        'context_title': ctx.get('context_title'),
                        'context_release_year': ctx.get('context_release_year'),
                        'context_series_title': ctx.get('context_series_title'),
                        'context_season': ctx.get('context_season'),
                        'context_episode': ctx.get('context_episode'),
                        'context_absolute': ctx.get('context_absolute'),
                        'context_key': ctx.get('context_key'),
                        'context_display': ctx.get('context_display'),
                    })
            if not files:
                skipped += 1
                continue
            # If a fallback record exists, update it in-place to avoid duplicates
            if existing_fallback is not None:
                backup_id_to_use = fallback_id
            else:
                backup_id_to_use = proper_id

            backup_record = {
                'backup_id': backup_id_to_use,
                'transfer_id': proper_id,
                'media_type': media_type,
                'folder_name': folder_name,
                'season_name': season_name,
                'source_path': source_path,
                'dest_path': dest_path,
                'backup_path': full,
                'file_count': len(files),
                'total_size': total_size,
                'status': 'ready',
                'created_at': created_iso
            }
            self.backup_model.create_or_replace_backup(backup_record)
            with self.db.get_connection() as conn:
                conn.execute('DELETE FROM backup_file WHERE backup_id = ?', (backup_id_to_use,))
                conn.commit()
            self.backup_model.add_backup_files(backup_id_to_use, files)
            imported += 1
        return (imported, skipped)

    # Helper methods
    def _get_dynamic_backup_dir(self, transfer: Dict) -> str:
        """Get the dynamic backup directory for a transfer"""
        backup_base = self.config.get("BACKUP_PATH", "/tmp/backup")
        safe_folder = self._safe_name(transfer.get('folder_name') or 'transfer')
        backup_id = transfer.get('transfer_id') or f"backup_{os.urandom(4).hex()}"
        return os.path.join(backup_base, f"{safe_folder}_{backup_id}")

    def _safe_name(self, name: str) -> str:
        """Convert a name to a filesystem-safe name"""
        if not name:
            return 'transfer'
        # Reuse simple cleaning similar to _clean_title but stricter for filesystem
        cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_')
        return cleaned or 'transfer'

    def _find_dest_match_for_context(self, dest_root: str, ctx_row: Dict, fallback_path: str) -> Optional[str]:
        """Find a destination file path that matches the provided context, if any.
        Only returns a path if it exists and differs from fallback_path to avoid deleting the same file."""
        try:
            if not dest_root or not os.path.isdir(dest_root):
                return None
            media_type = (ctx_row.get('context_media_type') or '').lower()
            season = ctx_row.get('context_season')
            episode = ctx_row.get('context_episode')
            absolute_num = ctx_row.get('context_absolute')
            series_title = ctx_row.get('context_series_title') or ctx_row.get('context_title')
            # File type safety: treat media vs ancillary differently
            media_ext = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.webm', '.m4v'}
            ancillary_ext = {'.nfo', '.srt', '.ass', '.sub', '.idx', '.txt'}
            try:
                _, backup_ext = os.path.splitext(ctx_row.get('original_path') or '')
            except Exception:
                backup_ext = ''
            # Build patterns
            candidates = []
            for root, dirs, files in os.walk(dest_root):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    # Skip same path as copy target
                    if os.path.normpath(fpath) == os.path.normpath(fallback_path):
                        continue
                    name = fname
                    n = name.lower()
                    # Enforce extension grouping: media replaces media; ancillary replaces ancillary
                    try:
                        _, ext = os.path.splitext(name)
                    except Exception:
                        ext = ''
                    if backup_ext:
                        if (backup_ext.lower() in media_ext and ext.lower() not in media_ext) or \
                           (backup_ext.lower() in ancillary_ext and ext.lower() not in ancillary_ext):
                            continue
                    if media_type == 'movies':
                        # Match Title (YYYY)
                        title = (ctx_row.get('context_title') or '').lower()
                        year = ctx_row.get('context_release_year') or ''
                        if title and year and (f"{title} ({year})" in n):
                            candidates.append(fpath)
                    else:
                        # Series SxxExx
                        if season and episode:
                            sxe = f"s{int(season):02d}e{int(episode):02d}"
                            if sxe in n:
                                # Optionally also check series title prefix before ' - s'
                                if series_title:
                                    prefix = series_title.lower()
                                    if prefix in n:
                                        candidates.append(fpath)
                                    else:
                                        # Accept match with SxxExx even if title not present
                                        candidates.append(fpath)
                                else:
                                    candidates.append(fpath)
                        # Anime absolute
                        if absolute_num:
                            abs_str = f" {int(absolute_num):03d} "
                            if abs_str in n:
                                candidates.append(fpath)
            # Prefer shortest directory depth match
            if not candidates:
                return None
            candidates.sort(key=lambda p: (p.count(os.sep), len(os.path.basename(p))))
            return candidates[0]
        except Exception:
            return None

    def _detect_context_from_filename(self, relative_path: str, media_type: str, folder_name: str, season_name: Optional[str]) -> Dict[str, Optional[str]]:
        """Parse context based on filename patterns and media_type."""
        try:
            base = os.path.basename(relative_path)
            name, _ext = os.path.splitext(base)
            context_media_type = (media_type or '').lower()
            context = {
                'context_media_type': context_media_type,
                'context_title': None,
                'context_release_year': None,
                'context_series_title': None,
                'context_season': None,
                'context_episode': None,
                'context_absolute': None,
                'context_key': None,
                'context_display': None,
            }
            # Movies: Title (YYYY)
            if context_media_type == 'movies':
                m = re.search(r'^(.+?)\s*\((\d{4})\)', name)
                if m:
                    title = m.group(1).strip()
                    year = m.group(2)
                else:
                    # Fallback to folder name if parse fails
                    title = folder_name.strip()
                    ym = re.search(r'\((\d{4})\)', name)
                    year = ym.group(1) if ym else None
                context.update({
                    'context_title': title,
                    'context_release_year': year,
                    'context_display': f"{title} ({year})" if year else title,
                })
                key = f"movie|{self._normalize_key(title)}|Y{year or ''}"
                context['context_key'] = key
                return context

            # Series/Anime: {Series} - SxxExx - ... (Anime may have absolute number segment)
            # Extract series title before " - S"
            parts = name.split(' - ')
            series_title = parts[0].strip() if parts else (folder_name or '').strip()
            # SxxExx
            se = re.search(r'[sS](\d{1,2})[eE](\d{1,2})', name)
            season = se.group(1) if se else (None)
            episode = se.group(2) if se else (None)
            # Absolute number (anime): a 3-digit token between separators
            absnum = None
            for token in parts:
                if re.fullmatch(r'\d{3}', token.strip()):
                    absnum = token.strip()
                    break
            context.update({
                'context_series_title': series_title,
                'context_title': series_title,
                'context_season': season,
                'context_episode': episode,
                'context_absolute': absnum
            })
            disp = series_title
            if season and episode:
                disp += f" - S{int(season):02d}E{int(episode):02d}"
            if absnum:
                disp += f" - {int(absnum):03d}"
            context['context_display'] = disp
            key_parts = [context_media_type or 'series', self._normalize_key(series_title)]
            if season and episode:
                key_parts.append(f"S{int(season):02d}E{int(episode):02d}")
            if absnum:
                key_parts.append(f"A{int(absnum):03d}")
            context['context_key'] = '|'.join(key_parts)
            return context
        except Exception:
            return {
                'context_media_type': (media_type or '').lower(),
                'context_title': folder_name,
                'context_release_year': None,
                'context_series_title': folder_name,
                'context_season': None,
                'context_episode': None,
                'context_absolute': None,
                'context_key': None,
                'context_display': folder_name,
            }

    def _normalize_key(self, s: str) -> str:
        """Normalize a string for use as a context key"""
        if not s:
            return ''
        x = s.lower()
        x = re.sub(r'[^a-z0-9]+', '_', x).strip('_')
        return x

