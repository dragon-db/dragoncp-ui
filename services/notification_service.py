#!/usr/bin/env python3
"""
DragonCP Notification Service

Turns things that happened into announcements. It knows rsync logs and transfer
rows; it knows nothing about Discord.

Until 2.3.0 this file built Discord embeds by hand in three places, each with
its own copy of the enabled check, the webhook URL read, the colour constants,
the field truncation and the error handling. All of that moved to
`services/connectors/adapters/discord.py`, which is now the only file in the
application that knows what an embed is.

What stayed is the part that is genuinely about this application: reading
rsync's summary output, pulling errors out of a log, and deciding which title
and poster describe a transfer.
"""

import re
from typing import Dict, List, Optional

from services.connectors import notify
from services.connectors.events import (
    ACCENT_RENAME,
    FAILURE,
    SUCCESS,
    WARNING,
    Event,
    Field,
)


class NotificationService:
    """Announcements about transfers, renames and backup retention."""

    def __init__(self, config, settings, transfer_model, webhook_model, series_webhook_model=None):
        self.config = config
        self.settings = settings
        self.transfer_model = transfer_model
        self.webhook_model = webhook_model
        self.series_webhook_model = series_webhook_model

    def parse_transfer_logs(self, logs: List[str]) -> Dict:
        """Parse rsync transfer logs to extract transfer statistics"""
        try:
            stats = {
                'total_transferred_size': None,
                'avg_speed': None,
                'regular_files_transferred': None,
                'deleted_files': None,
                'bytes_sent': None,
                'bytes_received': None
            }

            if not logs:
                return stats

            # Look through the logs for summary information (usually at the end)
            for line in reversed(logs):
                # Extract transfer statistics from rsync output
                # Number of regular files transferred: "Number of regular files transferred: 1"
                if 'Number of regular files transferred:' in line:
                    match = re.search(r'Number of regular files transferred:\s*(\d+)', line)
                    if match:
                        stats['regular_files_transferred'] = int(match.group(1))

                # Number of deleted files: "Number of deleted files: 0"
                if 'Number of deleted files:' in line:
                    match = re.search(r'Number of deleted files:\s*(\d+)', line)
                    if match:
                        stats['deleted_files'] = int(match.group(1))

                # Total file size: "Total file size: 3.70G bytes"
                if 'Total transferred file size:' in line:
                    match = re.search(r'Total transferred file size:\s*([0-9.,]+[KMGT]?)\s*bytes', line)
                    if match:
                        stats['total_transferred_size'] = match.group(1)

                # Speed and bytes info: "sent 103 bytes  received 3.70G bytes  4.68M bytes/sec"
                if 'sent' in line and 'bytes' in line and 'received' in line and 'bytes/sec' in line:
                    match = re.search(r'sent\s+([0-9.,]+[KMGT]?)\s+bytes\s+received\s+([0-9.,]+[KMGT]?)\s+bytes\s+([0-9.,]+[KMGT]?)\s+bytes/sec', line)
                    if match:
                        stats['bytes_sent'] = match.group(1)
                        stats['bytes_received'] = match.group(2)
                        stats['avg_speed'] = match.group(3) + ' bytes/sec'

            print(f"📊 Parsed transfer stats: {stats}")
            return stats

        except Exception as e:
            print(f"❌ Error parsing transfer logs: {e}")
            return {}

    def extract_rsync_errors(self, logs: List[str]) -> List[str]:
        """Extract rsync error messages from transfer logs"""
        try:
            errors = []

            if not logs:
                return errors

            # Look for rsync errors in logs
            for line in logs:
                line = line.strip()

                # Capture rsync error lines (case-insensitive)
                if 'rsync:' in line.lower() and ('error' in line.lower() or 'failed' in line.lower()):
                    # Clean up the error message
                    errors.append(line)

                # Capture specific error patterns
                elif 'no space left on device' in line.lower():
                    errors.append(line)
                elif 'permission denied' in line.lower():
                    errors.append(line)
                elif 'connection refused' in line.lower():
                    errors.append(line)
                elif 'timeout' in line.lower() and 'rsync' in line.lower():
                    errors.append(line)

            # Limit to last 10 errors to avoid overly long messages
            if len(errors) > 10:
                errors = errors[-10:]

            print(f"🔍 Extracted {len(errors)} error messages from logs")
            return errors

        except Exception as e:
            print(f"❌ Error extracting rsync errors: {e}")
            return []

    # -- announcements -------------------------------------------------------

    def send_discord_notification(self, transfer_id: str, transfer_status: str,
                                  sync_label: Optional[str] = None):
        """Announce a finished or failed transfer.

        The name is kept because four callers use it and it is not Discord's
        any more than it is anyone else's — where this ends up is a routing
        decision now, not a decision made here.

        `sync_label` is what the sync engine knows about how this sync started
        ("Automated Sync", "Auto-scanner", "Manual Sync"). Without it the label
        is guessed from the webhook row, which is all older callers had.
        """
        try:
            transfer = self.transfer_model.get(transfer_id)
            if not transfer:
                print(f"❌ Transfer {transfer_id} not found for notification")
                return

            # Only completed and failed transfers are announced. Cancelled and
            # paused ones are things the operator did on purpose and already
            # knows about.
            if transfer_status not in ('completed', 'failed'):
                return

            logs = transfer.get('logs', [])
            stats = self.parse_transfer_logs(logs)
            errors = self.extract_rsync_errors(logs) if transfer_status == 'failed' else []

            title = transfer.get('parsed_title', transfer.get('folder_name', 'Unknown'))
            poster_url, requested_by, is_auto_sync = self._webhook_context(
                transfer_id, transfer.get('media_type', '')
            )
            sync_type = sync_label or ('Automated Sync' if is_auto_sync else 'Manual Sync')

            if transfer_status == 'failed':
                fields = [Field('Folder Path', transfer.get('dest_path', 'Unknown'))]

                if errors:
                    detail = '\n'.join(errors)
                else:
                    # No recognised rsync error: the progress line is the best
                    # description of what went wrong that exists.
                    detail = transfer.get('progress', 'Unknown error')
                fields.append(Field('Error Details', detail, monospace=True))

                if (stats.get('regular_files_transferred') is not None
                        or stats.get('deleted_files') is not None):
                    fields.append(Field(
                        'Partial Transfer Stats',
                        f"Transferred: {stats.get('regular_files_transferred', 'N/A')}\n"
                        f"Deleted: {stats.get('deleted_files', 'N/A')}",
                        inline=True, monospace=True,
                    ))

                event_key, severity = 'transfer.failed', FAILURE
                author = f"{sync_type} - FAILED ❌"
            else:
                fields = [
                    Field('Folder Synced', transfer.get('dest_path', 'Unknown')),
                    Field(
                        'Files Info',
                        f"Transferred files: {stats.get('regular_files_transferred', 'N/A')}\n"
                        f"Deleted Files: {stats.get('deleted_files', 'N/A')}",
                        inline=True, monospace=True,
                    ),
                    Field(
                        'Speed Info',
                        f"Transferred: {stats.get('total_transferred_size', 'N/A')}\n"
                        f"Avg Speed: {stats.get('avg_speed', 'N/A')}",
                        inline=True, monospace=True,
                    ),
                ]
                event_key, severity = 'transfer.completed', SUCCESS
                author = sync_type

            if requested_by:
                fields.append(Field('Requested by', requested_by, inline=True))

            notify(Event(
                key=event_key,
                severity=severity,
                title=title,
                fields=tuple(fields),
                author=author,
                thumbnail_url=poster_url,
                context={'transfer_id': transfer_id},
            ))

        except Exception as e:
            print(f"❌ Error announcing transfer {transfer_id}: {e}")
            import traceback
            traceback.print_exc()

    def _webhook_context(self, transfer_id: str, media_type: str):
        """Poster, requester and whether this ran by itself.

        A transfer that came from a Radarr/Sonarr notification carries a poster
        image and the name of whoever asked for it. Finding that means looking
        in whichever notification table matches the media type.
        """
        poster_url: Optional[str] = None
        requested_by: Optional[str] = None
        is_auto_sync = False

        try:
            if media_type == 'movies':
                notifications = self.webhook_model.get_all()
                match = next(
                    (n for n in notifications if n.get('transfer_id') == transfer_id), None
                )
                if match:
                    poster_url = match.get('poster_url') or None
                    requested_by = match.get('requested_by')
                    # A movie sync driven by a notification is always automatic.
                    is_auto_sync = True

            elif media_type in ('series', 'anime', 'tvshows') and self.series_webhook_model:
                notifications = self.series_webhook_model.get_all()
                match = next(
                    (n for n in notifications if n.get('transfer_id') == transfer_id), None
                )
                if match:
                    poster_url = match.get('poster_url') or None
                    requested_by = match.get('requested_by')
                    # A season only counts as automatic if it went through the
                    # wait-and-batch scheduler. One an operator pressed sync on
                    # is a manual sync that happens to have a poster.
                    is_auto_sync = match.get('auto_sync_scheduled_at') is not None
        except Exception as e:
            print(f"⚠️  Could not read the notification behind {transfer_id}: {e}")

        return poster_url, requested_by, is_auto_sync

    def send_rename_discord_notification(self, rename_result: Dict):
        """Announce a finished rename run.

        Args:
            rename_result: what the rename produced — series_title, total_files,
                success_count, failed_count, status ('completed' | 'partial' |
                'failed'), renamed_files, media_type.
        """
        try:
            series_title = rename_result.get('series_title', 'Unknown Series')
            total_files = rename_result.get('total_files', 0)
            success_count = rename_result.get('success_count', 0)
            failed_count = rename_result.get('failed_count', 0)
            status = rename_result.get('status', 'unknown')
            renamed_files = rename_result.get('renamed_files', [])
            media_type = rename_result.get('media_type', 'series')

            if status == 'completed':
                severity, status_icon, status_text = SUCCESS, '✅', 'Completed'
            elif status == 'partial':
                severity, status_icon, status_text = WARNING, '⚠️', 'Partial'
            else:
                severity, status_icon, status_text = FAILURE, '❌', 'Failed'

            # Result names only. The old name is on screen in the app; what the
            # operator wants from a message is what the files are called now.
            lines = []
            for file_info in renamed_files[:5]:
                mark = '✓' if file_info.get('status') == 'success' else '✗'
                lines.append(f"{mark} {file_info.get('new_name', 'Unknown')}")
            if len(renamed_files) > 5:
                lines.append(f"... and {len(renamed_files) - 5} more files")
            rename_summary = '\n'.join(lines) if lines else 'No files renamed'

            notify(Event(
                key='rename.finished',
                severity=severity,
                # A finished rename and a finished sync are both successes and
                # were given different colours on purpose, so a glance tells
                # them apart.
                accent=ACCENT_RENAME if status == 'completed' else None,
                title=series_title,
                fields=(
                    Field('Media Type', (media_type or 'series').upper(), inline=True),
                    Field('Rename Status', f"{status_icon} {status_text}", inline=True),
                    Field(
                        'Files Summary',
                        f"Total: {total_files}\nRenamed: {success_count}\n"
                        f"Failed: {failed_count}",
                        monospace=True,
                    ),
                    Field('Renamed Files', rename_summary, monospace=True),
                ),
                author='File Rename',
                footer='DragonCP Rename Operation',
                context={'status': status},
            ))

        except Exception as e:
            print(f"❌ Error announcing rename: {e}")
            import traceback
            traceback.print_exc()

    def send_backup_retention_notification(self, summary: Dict):
        """Announce that the retention sweep deleted stored backup versions.

        This is the only deletion in the application that nobody asked for: it
        runs by itself after a sync, on the one feature whose promise is that
        nothing is destroyed. Everything else can be found by looking; this has
        to come and find the operator, which is why it is pushed rather than
        left in the trail.

        Args:
            summary: what was removed — deleted_count, reclaimed_bytes, items
                (each with a display name and paths), and the keep / grace_hours
                rule that selected them.
        """
        try:
            items = summary.get('items') or []
            deleted_count = summary.get('deleted_count') or len(items)
            if not deleted_count:
                return

            reclaimed = summary.get('reclaimed_bytes') or 0

            # Names, not just a count. "Removed 3 old versions" and "removed the
            # only copy of the thing you were looking for" read identically when
            # the titles are left out, and this message exists to be read in a
            # hurry.
            listed = []
            for item in items[:8]:
                display = item.get('display') or item.get('capture_id') or 'Unknown'
                listed.append(f"• {display}  ({self._format_size(item.get('total_size') or 0)})")
            if len(items) > 8:
                listed.append(f"… and {len(items) - 8} more")
            removed_text = '\n'.join(listed) if listed else 'No detail recorded'

            # The library path of the first thing removed, so the message says
            # where on disk this happened without listing every path.
            location = None
            for item in items:
                for file_info in item.get('files') or []:
                    location = file_info.get('original_path') or file_info.get('backup_path')
                    if location:
                        break
                if location:
                    break

            rule_parts = []
            if summary.get('keep') is not None:
                rule_parts.append(f"keep {summary['keep']} per item")
            if summary.get('grace_hours'):
                rule_parts.append(f"{summary['grace_hours']}h grace")

            fields = [
                Field('Removed', f"{deleted_count} stored version(s)",
                      inline=True, monospace=True),
                Field('Space Reclaimed', self._format_size(reclaimed),
                      inline=True, monospace=True),
                Field('Deleted Media', removed_text, monospace=True),
            ]
            if location:
                fields.append(Field('Library Location', location, monospace=True))
            if rule_parts:
                fields.append(Field('Retention Rule', ', '.join(rule_parts), monospace=True))

            notify(Event(
                key='backup.retention_deleted',
                severity=WARNING,
                title='🧹 Automatic backup cleanup',
                summary=(
                    'Old restore points were deleted to keep the backup disk within '
                    'its retention rule. This cannot be undone.'
                ),
                fields=tuple(fields),
                author='Backup Retention',
                footer='DragonCP Backup Retention',
                context={'deleted_count': deleted_count},
            ))

        except Exception as e:  # noqa: BLE001 - see the docstring; must not raise
            print(f"❌ Error announcing backup retention: {e}")
            import traceback
            traceback.print_exc()

    @staticmethod
    def _format_size(num_bytes) -> str:
        """Bytes as something readable in a chat message."""
        try:
            size = float(num_bytes or 0)
        except (TypeError, ValueError):
            return '0 B'
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if size < 1024 or unit == 'TB':
                return f"{size:.0f} {unit}" if unit == 'B' else f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"
