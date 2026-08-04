#!/usr/bin/env python3
"""
DragonCP Backup Routes

Two surfaces over one store:

  * the current API, shaped around slots and versions, which the React page uses
  * a compatibility layer at the old paths, so the legacy static UI keeps
    listing and restoring against the new tree instead of breaking

SECURITY: relative paths in a restore selection are validated here with
security.validate_relative_path and again inside the planner. Everything else
the client sends is an identifier looked up in the index — no path from a
request is ever joined onto the filesystem directly.
"""

from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request

from activity_log import record
from auth import require_auth
from security import validate_relative_path

backups_bp = Blueprint('backups', __name__)

# Set by app.py
transfer_coordinator = None


def init_backup_routes(app_transfer_coordinator):
    global transfer_coordinator
    transfer_coordinator = app_transfer_coordinator


def _service():
    return transfer_coordinator.backups


def _fail(message: str, code: int = 400):
    return jsonify({'status': 'error', 'message': message}), code


def _capture_label(capture_id: str) -> str:
    """
    Name a backup version for the activity trail.

    Read before the action wherever the action removes it: once the files and
    the index entry are gone, the recorded entry is the only place that says
    what was deleted, and an id on its own tells nobody anything.
    """
    try:
        capture = _service().captures.get(capture_id)
        if capture:
            parts = [capture.get('title') or capture.get('slot_key') or capture_id]
            season = capture.get('season_number')
            episode = capture.get('episode_number')
            if season is not None and episode is not None:
                parts.append(f"S{int(season):02d}E{int(episode):02d}")
            elif season is not None:
                parts.append(f"Season {int(season)}")
            return ' '.join(str(p) for p in parts if p)
    except Exception:
        pass
    return capture_id


def _retention_phrase(rule: Dict) -> str:
    """The retention rule as a sentence fragment, for the activity trail."""
    if not rule or not rule.get('enabled'):
        return 'off'
    keep = rule.get('keep')
    grace = rule.get('grace_hours')
    parts = [f"keep {keep} version(s) per item" if keep is not None else 'enabled']
    if grace:
        parts.append(f"after a {grace}h grace period")
    return ', '.join(parts)


def _selected_files(payload: Dict) -> Optional[List[str]]:
    """
    The file selection from a request body.

    None means every file in the capture. An explicitly empty list is rejected
    rather than silently meaning "all" — the old plan endpoint treated `[]` as
    falsy and planned a restore of everything, which is the opposite of what
    ticking nothing means.
    """
    files = payload.get('files')
    if files is None:
        return None
    if not isinstance(files, list):
        raise ValueError("'files' must be a list of relative paths")
    if not files:
        raise ValueError('Nothing was selected')
    for entry in files:
        if not isinstance(entry, str) or not validate_relative_path(entry):
            raise ValueError(f'Invalid file path rejected: {entry}')
    return files


# ===========================================================================
# Overview and browsing
# ===========================================================================

@backups_bp.route('/backups/overview')
@require_auth
def api_backups_overview():
    """Totals, disk pressure, the retention rule, and what is on the disk."""
    try:
        return jsonify({'status': 'success', **_service().overview()})
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error building the backups overview: {error}")
        return _fail(f'Failed to load the overview: {error}', 500)


@backups_bp.route('/backups/titles')
@require_auth
def api_backups_titles():
    try:
        library = request.args.get('library') or None
        return jsonify({'status': 'success', 'titles': _service().titles(library)})
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to list titles: {error}', 500)


@backups_bp.route('/backups/seasons')
@require_auth
def api_backups_seasons():
    library = request.args.get('library')
    title = request.args.get('title')
    if not library or not title:
        return _fail('library and title are required')
    try:
        return jsonify({
            'status': 'success',
            'seasons': _service().seasons(library, title),
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to list seasons: {error}', 500)


@backups_bp.route('/backups/slots')
@require_auth
def api_backups_slots():
    try:
        season = request.args.get('season', type=int)
        return jsonify({
            'status': 'success',
            **_service().slots(
                library=request.args.get('library') or None,
                title=request.args.get('title') or None,
                season=season,
                search=request.args.get('search') or None,
                # Clamped at both ends: a negative limit reaches SQLite as
                # "no limit", which is the opposite of what it asks for.
                limit=max(1, min(request.args.get('limit', 200, type=int) or 200, 1000)),
                offset=max(request.args.get('offset', 0, type=int) or 0, 0),
                # 'size' puts the biggest first, which is the order you want
                # when the question is "what do I delete to get space back".
                sort='size' if request.args.get('sort') == 'size' else 'recent',
            ),
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to list backups: {error}', 500)


@backups_bp.route('/backups/slot')
@require_auth
def api_backups_slot():
    slot_key = request.args.get('slot_key')
    if not slot_key:
        return _fail('slot_key is required')
    try:
        result = _service().slot(slot_key)
        if not result['captures']:
            return _fail('No backups for this item', 404)
        return jsonify({'status': 'success', **result})
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to load the version history: {error}', 500)


@backups_bp.route('/backups/captures/<capture_id>')
@require_auth
def api_backups_capture(capture_id):
    try:
        # Named `capture`, not `record`: the module-level `record` is the
        # activity recorder, and a local of the same name would silently shadow
        # it for the whole function the moment anyone added a call here.
        capture = _service().capture(capture_id)
        if not capture:
            return _fail('Backup not found', 404)
        return jsonify({'status': 'success', 'capture': capture})
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to load the backup: {error}', 500)


@backups_bp.route('/backups/unsorted')
@require_auth
def api_backups_unsorted():
    """Files that could not be identified. Kept, listed, never guessed at."""
    try:
        return jsonify({'status': 'success', 'captures': _service().unsorted()})
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to list unsorted files: {error}', 500)


# ===========================================================================
# Restore
# ===========================================================================

@backups_bp.route('/backups/captures/<capture_id>/plan', methods=['POST'])
@require_auth
def api_backups_plan(capture_id):
    """
    Preview. Reads only.

    The same function backs this and the restore itself, so what is approved is
    what runs.
    """
    try:
        files = _selected_files(request.json or {})
    except ValueError as error:
        return _fail(str(error))
    try:
        return jsonify({'status': 'success', 'plan': _service().plan_restore(capture_id, files)})
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error planning a restore for {capture_id}: {error}")
        return _fail(f'Failed to plan the restore: {error}', 500)


@backups_bp.route('/backups/captures/<capture_id>/restore', methods=['POST'])
@require_auth
def api_backups_restore(capture_id):
    """
    Start a restore.

    Returns as soon as the run is accepted. It goes through the transfer queue,
    so progress and logs arrive the same way every other transfer's do.
    """
    try:
        files = _selected_files(request.json or {})
    except ValueError as error:
        return _fail(str(error))
    try:
        label = _capture_label(capture_id)
        ok, message, detail = _service().restore(capture_id, files)
        if ok:
            record('backup.restore', f"Restored {label} from a backup",
                   target_type='backup_capture', target_id=capture_id, target_label=label,
                   detail={'files': len(files) if files else None})
        if not ok:
            return jsonify({'status': 'error', 'message': message, 'plan': detail}), 400
        return jsonify({'status': 'success', 'message': message, **detail})
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error restoring {capture_id}: {error}")
        return _fail(f'Failed to restore: {error}', 500)


# ===========================================================================
# Managing captures
# ===========================================================================

@backups_bp.route('/backups/captures/<capture_id>/pin', methods=['POST'])
@require_auth
def api_backups_pin(capture_id):
    """Pinned versions are never removed by retention."""
    payload = request.json or {}
    pinned = bool(payload.get('pinned', True))
    try:
        label = _capture_label(capture_id)
        ok, message = _service().set_pinned(capture_id, pinned)
        if ok:
            record('backup.pin' if pinned else 'backup.unpin',
                   f"{'Pinned' if pinned else 'Unpinned'} the backup of {label}",
                   target_type='backup_capture', target_id=capture_id, target_label=label)
        return (jsonify({'status': 'success', 'message': message})
                if ok else _fail(message, 404))
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to update the pin: {error}', 500)


@backups_bp.route('/backups/captures/<capture_id>/delete', methods=['POST'])
@require_auth
def api_backups_delete(capture_id):
    """
    Remove one version — its files and its index entry, always together.

    There is no record-only option. The index is derived from the tree, so
    deleting a row on its own frees nothing and the entry returns at the next
    rebuild.
    """
    try:
        label = _capture_label(capture_id)
        ok, message = _service().delete_capture(capture_id)
        if ok:
            record('backup.delete', f"Deleted the backup of {label}",
                   target_type='backup_capture', target_id=capture_id, target_label=label)
            return jsonify({'status': 'success', 'message': message})
        # Unknown id is a 404 here as it is on the pin and detail routes; a
        # failure to remove the files is a 400.
        return _fail(message, 404 if message == 'Backup not found' else 400)
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to delete the backup: {error}', 500)


# ===========================================================================
# Housekeeping
# ===========================================================================

def _id_list(payload: Dict, key: str) -> Optional[List[str]]:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"'{key}' must be a list")
    cleaned = [v for v in value if isinstance(v, str) and v.strip()]
    if not cleaned:
        raise ValueError(f"'{key}' was empty")
    return cleaned


@backups_bp.route('/backups/delete/preview', methods=['POST'])
@require_auth
def api_backups_delete_preview():
    """
    What a deletion would remove, and how much space it would free.

    Reads only. Deleting a backup has no undo — those files are the last copy of
    that version — so the numbers go in front of the operator first.
    """
    payload = request.json or {}
    try:
        capture_ids = _id_list(payload, 'capture_ids')
        slot_keys = _id_list(payload, 'slot_keys')
    except ValueError as error:
        return _fail(str(error))
    if not capture_ids and not slot_keys:
        return _fail('Select something to delete')

    try:
        return jsonify({
            'status': 'success',
            **_service().preview_delete(
                capture_ids=capture_ids,
                slot_keys=slot_keys,
                keep_newest=max(0, int(payload.get('keep_newest') or 0)),
                include_pinned=bool(payload.get('include_pinned')),
            ),
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to work out what would be deleted: {error}', 500)


@backups_bp.route('/backups/delete', methods=['POST'])
@require_auth
def api_backups_delete_many():
    """
    Remove several versions at once — the space-reclaiming action.

    Accepts explicit `capture_ids`, or `slot_keys` to clear whole items, with
    `keep_newest` to leave the most recent N of each. Pinned versions are held
    back unless `include_pinned` is set, and the count held back is reported.
    """
    payload = request.json or {}
    try:
        capture_ids = _id_list(payload, 'capture_ids')
        slot_keys = _id_list(payload, 'slot_keys')
    except ValueError as error:
        return _fail(str(error))
    if not capture_ids and not slot_keys:
        return _fail('Select something to delete')

    try:
        result = _service().delete_many(
            capture_ids=capture_ids,
            slot_keys=slot_keys,
            keep_newest=max(0, int(payload.get('keep_newest') or 0)),
            include_pinned=bool(payload.get('include_pinned')),
        )
        record('backup.bulk_delete',
               f"Deleted {result['deleted_count']} backup version(s), "
               f"reclaiming {result['reclaimed'] / 1e9:.2f} GB",
               target_type='backup_capture',
               detail={'deleted_count': result['deleted_count'],
                       'reclaimed_bytes': result['reclaimed'],
                       'skipped_pinned': result['skipped_pinned'],
                       'by_slot': bool(slot_keys)})

        pinned_note = (
            f", {result['skipped_pinned']} pinned version(s) left alone"
            if result['skipped_pinned'] else ''
        )
        return jsonify({
            'status': 'success',
            'message': (
                f"Deleted {result['deleted_count']} version(s), "
                f"reclaiming {result['reclaimed'] / 1e9:.2f} GB{pinned_note}"
            ),
            **result,
        })
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error deleting backups: {error}")
        return _fail(f'Failed to delete: {error}', 500)


@backups_bp.route('/backups/unsorted/delete', methods=['POST'])
@require_auth
def api_backups_clear_unsorted():
    """Throw away everything that could not be identified."""
    payload = request.json or {}
    if not payload.get('confirm'):
        return _fail('Clearing the unidentified files must be confirmed')
    try:
        result = _service().clear_unsorted()
        record('backup.clear_unsorted',
               f"Cleared {result['deleted_count']} unidentified backup item(s)",
               target_type='backup_capture',
               detail={'deleted_count': result['deleted_count'],
                       'reclaimed_bytes': result['reclaimed']})
        return jsonify({
            'status': 'success',
            'message': (
                f"Removed {result['deleted_count']} unidentified item(s), "
                f"reclaiming {result['reclaimed'] / 1e9:.2f} GB"
            ),
            **result,
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to clear the unidentified files: {error}', 500)


@backups_bp.route('/backups/rebuild', methods=['POST'])
@require_auth
def api_backups_rebuild():
    """
    Regenerate the index from the tree.

    Reads the disk and writes only the index — it moves no files and deletes no
    media. Safe to run at any time, and running it twice leaves the same index.
    """
    try:
        result = _service().rebuild_index()
        record('backup.rebuild_index', 'Rebuilt the backup index from the files on disk',
               target_type='backup_capture', detail=dict(result) if isinstance(result, dict) else None)
        return jsonify({
            'status': 'success',
            'message': (
                f"Indexed {result['indexed']} version(s), "
                f"{result['files']} file(s)"
                + (f", removed {result['removed']} stale entry(s)" if result['removed'] else '')
                + (f", repaired {result['repaired']} duplicate id(s)"
                   if result.get('repaired') else '')
            ),
            **result,
        })
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error rebuilding the backup index: {error}")
        return _fail(f'Failed to rebuild the index: {error}', 500)


@backups_bp.route('/backups/retention')
@require_auth
def api_backups_retention():
    try:
        service = _service()
        return jsonify({
            'status': 'success',
            'retention': service.retention.describe(),
            'disk': service.retention.disk_usage(),
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to read the retention rule: {error}', 500)


@backups_bp.route('/backups/retention', methods=['POST'])
@require_auth
def api_backups_save_retention():
    """
    Persist the retention rule.

    Stored in the database, so it survives a restart AND is visible to the
    background thread that applies it after a transfer — neither of which is
    true of a value kept in the browser session.
    """
    payload = request.json or {}
    try:
        keep = payload.get('keep')
        grace = payload.get('grace_hours')
        enabled = payload.get('enabled')
        rule = _service().save_retention(
            keep=None if keep is None else int(keep),
            grace_hours=None if grace is None else int(grace),
            enabled=None if enabled is None else bool(enabled),
        )
        record('backup.retention_save',
               f"Changed the backup retention rule to {_retention_phrase(rule)}",
               target_type='setting', target_id='backup_retention', detail=dict(rule))
        return jsonify({'status': 'success', 'message': 'Retention saved', 'retention': rule})
    except (TypeError, ValueError) as error:
        return _fail(f'Invalid retention value: {error}')
    except RuntimeError as error:
        return _fail(str(error))
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to save retention: {error}', 500)


def _retention_overrides(payload: Dict):
    """
    `keep` and `grace_hours` from a request body, as integers.

    The policy clamps them, but it cannot clamp a string: `"5"` arriving from a
    form would sail past the bounds and reach the comparison as text. Converted
    here, the same way the save endpoint already does it, so preview and apply
    cannot disagree with each other or with what was saved.
    """
    keep = payload.get('keep')
    grace = payload.get('grace_hours')
    return (
        None if keep is None else int(keep),
        None if grace is None else int(grace),
    )


@backups_bp.route('/backups/retention/preview', methods=['POST'])
@require_auth
def api_backups_retention_preview():
    payload = request.json or {}
    try:
        keep, grace = _retention_overrides(payload)
    except (TypeError, ValueError) as error:
        return _fail(f'Invalid retention value: {error}')
    try:
        return jsonify({
            'status': 'success',
            **_service().retention_preview(keep=keep, grace_hours=grace),
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to preview retention: {error}', 500)


@backups_bp.route('/backups/retention/apply', methods=['POST'])
@require_auth
def api_backups_retention_apply():
    payload = request.json or {}
    try:
        keep, grace = _retention_overrides(payload)
    except (TypeError, ValueError) as error:
        return _fail(f'Invalid retention value: {error}')
    try:
        result = _service().retention_apply(keep=keep, grace_hours=grace)
        record('backup.retention_apply',
               f"Applied the retention rule, removing {result['deleted_count']} old version(s)",
               target_type='backup_capture',
               detail={'deleted_count': result['deleted_count'],
                       'reclaimed_bytes': result['reclaimed'],
                       'keep': keep, 'grace_hours': grace})
        return jsonify({
            'status': 'success',
            'message': (
                f"Removed {result['deleted_count']} old version(s), "
                f"reclaiming {result['reclaimed'] / 1e9:.2f} GB"
            ),
            **result,
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to apply retention: {error}', 500)


@backups_bp.route('/backups/migration/plan', methods=['POST'])
@require_auth
def api_backups_migration_plan():
    """
    What adopting the old per-transfer folders would do. Moves nothing.

    Always run before applying: identity is being inferred for files that in
    some cases have no transfer record left to check the inference against.
    """
    try:
        return jsonify({'status': 'success', **_service().migration_plan()})
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error planning the backup migration: {error}")
        return _fail(f'Failed to plan the migration: {error}', 500)


@backups_bp.route('/backups/migration/apply', methods=['POST'])
@require_auth
def api_backups_migration_apply():
    payload = request.json or {}
    if not payload.get('confirm'):
        return _fail('Migration must be confirmed after reviewing the preview')
    try:
        result = _service().migration_apply()
        if result.get('applied'):
            record('backup.migrate', 'Migrated the old per-transfer backup folders',
                   target_type='backup_capture',
                   detail={k: v for k, v in result.items() if isinstance(v, (int, str, bool))})
        # A refused migration is not a success with a zero count. It comes back
        # `applied: false` with the reason, and reporting "Moved 0 file(s)"
        # over the top of that reads as "there was nothing to do".
        if not result.get('applied'):
            return jsonify({
                'status': 'error',
                'message': result.get('blocked') or 'Migration did not run',
                **result,
            }), 409
        return jsonify({
            'status': 'success',
            'message': (
                f"Moved {result['moved_count']} file(s) and removed "
                f"{result['removed_folders']} old folder(s)"
            ),
            **result,
        })
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error applying the backup migration: {error}")
        return _fail(f'Failed to migrate: {error}', 500)


# ===========================================================================
# Compatibility — the legacy static UI's endpoints, backed by the new store
# ===========================================================================
#
# The legacy UI is still what production serves. Rather than let its Backups
# page break, these map captures into the shape it already renders. A capture
# id takes the place of the old backup id everywhere, so its list -> files ->
# plan -> restore flow keeps working against the new tree.

def _as_legacy_backup(capture: Dict) -> Dict:
    season = capture.get('season_number')
    return {
        'backup_id': capture['capture_id'],
        'transfer_id': capture.get('source_transfer_id') or capture['capture_id'],
        'media_type': capture.get('library'),
        'folder_name': capture.get('title'),
        'season_name': (
            None if season is None
            else ('Specials' if season == 0 else f"Season {season:02d}")
        ),
        'backup_path': capture.get('capture_path'),
        'dest_path': '',
        'source_path': '',
        'file_count': capture.get('file_count', 0),
        'total_size': capture.get('total_size', 0),
        'status': 'restored' if capture.get('restored_at') else 'ready',
        'created_at': capture.get('captured_at'),
        'restored_at': capture.get('restored_at'),
        'pinned': bool(capture.get('pinned')),
    }


@backups_bp.route('/backups')
@require_auth
def api_list_backups():
    """Legacy list. Newest versions first, across every slot."""
    try:
        limit = max(1, min(request.args.get('limit', 100, type=int) or 100, 1000))
        captures = transfer_coordinator.capture_model.recent(limit=limit)
        rows = [_as_legacy_backup(c) for c in captures]
        return jsonify({'status': 'success', 'backups': rows, 'total': len(rows)})
    except Exception as error:  # noqa: BLE001
        print(f"❌ Error listing backups: {error}")
        return _fail(f'Failed to list backups: {error}', 500)


@backups_bp.route('/backups/<backup_id>')
@require_auth
def api_get_backup(backup_id):
    try:
        capture = _service().capture(backup_id)
        if not capture:
            return _fail('Backup not found', 404)
        return jsonify({'status': 'success', 'backup': _as_legacy_backup(capture)})
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to get the backup: {error}', 500)


@backups_bp.route('/backups/<backup_id>/files')
@require_auth
def api_get_backup_files(backup_id):
    try:
        capture = _service().capture(backup_id)
        if not capture:
            return _fail('Backup not found', 404)
        files = [
            {
                'relative_path': f['relative_path'],
                'original_path': f.get('original_path') or '',
                'file_size': f.get('file_size', 0),
                'modified_time': f.get('modified_time', 0),
                'context_display': capture.get('display') or '',
            }
            for f in capture.get('files', [])
        ]
        return jsonify({'status': 'success', 'files': files, 'total': len(files)})
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to get the backup files: {error}', 500)


@backups_bp.route('/backups/<backup_id>/plan', methods=['POST'])
@require_auth
def api_plan_backup_restore(backup_id):
    """Legacy plan shape, from the current planner."""
    payload = request.json or {}
    files = payload.get('files')
    if files is not None and not isinstance(files, list):
        return _fail("'files' must be a list of relative paths")
    # The legacy UI sends [] to mean "everything"; the current API rejects it.
    # Normalising here keeps that page working without softening the new rule.
    files = files or None
    try:
        plan = _service().plan_restore(backup_id, files)
        operations = [
            {
                'backup_relative': op['relative_path'],
                'backup_full': '',
                'copy_to': op['target'],
                'target_delete': op['replaces'],
                'context_display': op['display'],
            }
            for op in plan.get('operations', [])
        ]
        return jsonify({
            'status': 'success',
            'plan': {'operations': operations, 'blocked': plan.get('blocked')},
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to plan the restore: {error}', 500)


@backups_bp.route('/backups/<backup_id>/restore', methods=['POST'])
@require_auth
def api_restore_backup(backup_id):
    payload = request.json or {}
    files = payload.get('files')
    if files is not None:
        if not isinstance(files, list):
            return _fail("'files' must be a list of relative paths")
        if not files:
            return _fail('Empty file selection not allowed')
        for entry in files:
            if not isinstance(entry, str) or not validate_relative_path(entry):
                return _fail(f'Invalid file path rejected: {entry}')
    try:
        label = _capture_label(backup_id)
        ok, message, _detail = _service().restore(backup_id, files)
        if ok:
            record('backup.restore', f"Restored {label} from a backup",
                   target_type='backup_capture', target_id=backup_id, target_label=label,
                   detail={'files': len(files) if files else None, 'legacy_endpoint': True})
        return (jsonify({'status': 'success', 'message': message})
                if ok else _fail(message))
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to restore: {error}', 500)


@backups_bp.route('/backups/<backup_id>/delete', methods=['POST'])
@require_auth
def api_delete_backup(backup_id):
    """
    Legacy delete.

    The old page offered "delete the record" and "delete the files" as separate
    choices. There is no longer a record to keep without its files — the index
    is derived from the tree — so both requests mean the same thing and any
    `delete_record` / `delete_files` flags in the body are ignored.
    """
    try:
        label = _capture_label(backup_id)
        ok, message = _service().delete_capture(backup_id)
        if ok:
            record('backup.delete', f"Deleted the backup of {label}",
                   target_type='backup_capture', target_id=backup_id, target_label=label,
                   detail={'legacy_endpoint': True})
        return (jsonify({'status': 'success', 'message': message})
                if ok else _fail(message))
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to delete the backup: {error}', 500)


@backups_bp.route('/backups/reindex', methods=['POST'])
@require_auth
def api_reindex_backups():
    """Legacy name for the index rebuild."""
    try:
        result = _service().rebuild_index()
        record('backup.rebuild_index', 'Rebuilt the backup index from the files on disk',
               target_type='backup_capture', detail={'legacy_endpoint': True})
        return jsonify({
            'status': 'success',
            'message': f"Indexed {result['indexed']} version(s).",
            'imported': result['indexed'],
            'skipped': result['removed'],
            **result,
        })
    except Exception as error:  # noqa: BLE001
        return _fail(f'Failed to rebuild the index: {error}', 500)
