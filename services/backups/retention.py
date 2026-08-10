#!/usr/bin/env python3
"""
Retention — keep the newest N captures per slot.

This is not an optimisation. The backup disk was measured at 68% full with no
pruning of any kind, and a model where every restore adds a version would fill
it. Keep-N is also the rule that only became expressible once files were
grouped by slot: before, nothing knew that two files were the same episode, so
no per-episode rule could be written at all.

Three things protect a capture from being pruned:

  * it is within the newest N for its slot,
  * it is pinned,
  * it is younger than the grace period — which is what stops an accidental
    sync immediately pushing the copy you wanted off the end of the list.

Nothing is ever removed silently. Every prune returns what it deleted and how
much it reclaimed, and the caller reports it.
"""

import shutil
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional

from .layout import BackupLayout, utc_now
from .reporting import describe_capture

DEFAULT_KEEP = 2
DEFAULT_GRACE_HOURS = 24

# Guard rails. Keep-0 would delete every version the moment it was written,
# which is not a retention policy but a disabled backup system.
MIN_KEEP = 1
MAX_KEEP = 50


@dataclass
class PruneCandidate:
    capture_id: str
    slot_key: str
    display: str
    captured_at: str
    total_size: int
    capture_path: str

    def as_dict(self) -> Dict:
        return {
            'capture_id': self.capture_id,
            'slot_key': self.slot_key,
            'display': self.display,
            'captured_at': self.captured_at,
            'total_size': self.total_size,
            'capture_path': self.capture_path,
        }


@dataclass
class PruneResult:
    keep: int
    grace_hours: int
    candidates: List[PruneCandidate] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    #: The same deletions, described in full — title, paths, files, size. Built
    #: before anything is removed, because afterwards there is nothing left to
    #: read. `deleted` stays a plain id list so existing callers are unaffected.
    deleted_items: List[Dict] = field(default_factory=list)
    reclaimed: int = 0
    errors: List[str] = field(default_factory=list)
    applied: bool = False

    def as_dict(self) -> Dict:
        return {
            'keep': self.keep,
            'grace_hours': self.grace_hours,
            'applied': self.applied,
            'candidates': [c.as_dict() for c in self.candidates],
            'candidate_count': len(self.candidates),
            'candidate_size': sum(c.total_size for c in self.candidates),
            'deleted': self.deleted,
            'deleted_items': self.deleted_items,
            'deleted_count': len(self.deleted),
            'reclaimed': self.reclaimed,
            'errors': self.errors,
        }


class RetentionPolicy:
    """Reads the configured rule and applies it."""

    def __init__(self, config, layout: BackupLayout, capture_model, settings=None):
        self.config = config
        self.layout = layout
        self.captures = capture_model
        self.settings = settings

    # ---- settings ---------------------------------------------------------

    def keep(self) -> int:
        return self._clamp_int('BACKUP_RETENTION_KEEP', DEFAULT_KEEP, MIN_KEEP, MAX_KEEP)

    def grace_hours(self) -> int:
        return self._clamp_int('BACKUP_RETENTION_GRACE_HOURS', DEFAULT_GRACE_HOURS, 0, 24 * 30)

    def enabled(self) -> bool:
        raw = self._setting('BACKUP_RETENTION_ENABLED')
        if raw is None or raw == '':
            return True
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')

    def _setting(self, key: str) -> Optional[str]:
        """
        The value from wherever it lives.

        `self.settings` is the settings resolver, which already knows this is a
        database setting and already applies the env file as its default. The
        `config` fallback below is only for a policy constructed without one —
        the tests do that, and so would any caller that has not been wired up.
        """
        if self.settings is not None:
            try:
                return self.settings.get(key)
            except Exception:  # noqa: BLE001 - fall through to config
                pass
        return self.config.get(key)

    def _clamp_int(self, key: str, default: int, low: int, high: int) -> int:
        raw = self._setting(key)
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return default
        return max(low, min(high, value))

    def describe(self) -> Dict:
        return {
            'enabled': self.enabled(),
            'keep': self.keep(),
            'grace_hours': self.grace_hours(),
            # False when there is no writable store wired up, in which case the
            # rule can only be changed in the env file and a restart.
            'editable': self.settings is not None and hasattr(self.settings, 'set_many'),
        }

    def save(self, keep: Optional[int] = None, grace_hours: Optional[int] = None,
             enabled: Optional[bool] = None) -> Dict:
        """
        Persist the rule.

        Written to `app_settings` — the database — rather than the env file,
        because that is the only store that both survives a restart and is
        visible to the background thread that applies the rule after a
        transfer. A value in the Flask session would be invisible to it, and a
        value in the env file would need a redeploy to change.
        """
        if self.settings is None or not hasattr(self.settings, 'set_many'):
            raise RuntimeError(
                'No settings store is available, so the retention rule can only '
                'be changed in the environment file'
            )

        # Written through the resolver's own writer, which owns the bounds and
        # the boolean spelling. Reaching for a `set_bool` the resolver does not
        # have is how this crashed the first time.
        payload = {}
        if keep is not None:
            payload['BACKUP_RETENTION_KEEP'] = keep
        if grace_hours is not None:
            payload['BACKUP_RETENTION_GRACE_HOURS'] = grace_hours
        if enabled is not None:
            payload['BACKUP_RETENTION_ENABLED'] = enabled

        if payload:
            saved, refused, errors = self.settings.set_many(payload)
            if errors:
                raise ValueError('; '.join(errors))
            if refused:
                raise RuntimeError(
                    f"Not writable here: {', '.join(sorted(refused))}"
                )
            del saved

        return self.describe()

    # ---- the rule ---------------------------------------------------------

    def candidates(self, keep: Optional[int] = None,
                   grace_hours: Optional[int] = None) -> PruneResult:
        """What the rule would remove. Reads only."""
        keep = self.keep() if keep is None else max(MIN_KEEP, min(MAX_KEEP, keep))
        grace = self.grace_hours() if grace_hours is None else max(0, grace_hours)
        cutoff = (utc_now() - timedelta(hours=grace)).isoformat().replace('+00:00', 'Z')

        result = PruneResult(keep=keep, grace_hours=grace)
        for row in self.captures.prunable(keep, cutoff):
            result.candidates.append(PruneCandidate(
                capture_id=row['capture_id'],
                slot_key=row.get('member_slot_key') or row.get('slot_key') or '',
                display=self._display(row),
                captured_at=row.get('captured_at') or '',
                total_size=row.get('total_size') or 0,
                capture_path=row.get('capture_path') or '',
            ))
        return result

    def apply(self, keep: Optional[int] = None,
              grace_hours: Optional[int] = None) -> PruneResult:
        """
        Remove what the rule selects, reporting every deletion.

        Each version is described before it is touched. This runs unattended
        after a sync, so the entry it leaves behind is the only thing that will
        ever say which episode went — reading the row and its files after
        `delete()` would find nothing.
        """
        result = self.candidates(keep=keep, grace_hours=grace_hours)
        result.applied = True

        for candidate in result.candidates:
            try:
                path = self.layout.absolute(candidate.capture_path)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{candidate.display}: {error}")
                continue

            described = self._describe(candidate, path)

            try:
                shutil.rmtree(path, ignore_errors=False)
            except FileNotFoundError:
                # Already gone from disk; the index row still has to go.
                pass
            except OSError as error:
                result.errors.append(f"{candidate.display}: {error}")
                continue

            self.layout.prune_empty_dirs(path)
            self.captures.delete(candidate.capture_id)
            result.deleted.append(candidate.capture_id)
            result.deleted_items.append(described)
            result.reclaimed += candidate.total_size

        return result

    def _describe(self, candidate: PruneCandidate, capture_dir: str) -> Dict:
        """
        One about-to-be-deleted version, in full.

        Failing to read the files must not stop the prune: the disk pressure
        this exists to relieve is real, and a version that cannot be described
        is still recorded by id, name and path.
        """
        try:
            files = self.captures.files(candidate.capture_id)
        except Exception:  # noqa: BLE001 - a thinner record beats no deletion
            files = []
        record = self.captures.get(candidate.capture_id) or {}
        return describe_capture(
            {**record, **candidate.as_dict()},
            files=files,
            display=candidate.display,
            capture_dir=capture_dir,
        )

    @staticmethod
    def _display(row: Dict) -> str:
        from .identity import SlotIdentity
        return SlotIdentity(
            library=row.get('library') or '',
            title=row.get('title') or '',
            season=row.get('season_number'),
            episode=row.get('episode_number'),
            year=row.get('release_year'),
        ).display

    # ---- disk pressure ----------------------------------------------------

    def disk_usage(self) -> Optional[Dict]:
        """
        Free space on the backup device.

        Reported, never acted on. Pruning keyed to free space fires at
        unpredictable moments, which for a recovery tool is exactly the wrong
        property — the operator sees the number and decides.
        """
        base = self.layout.base_or_none()
        if not base:
            return None
        try:
            total, used, free = shutil.disk_usage(base)
        except OSError:
            return None
        return {
            'total': total,
            'used': used,
            'free': free,
            'percent_used': round(used / total * 100, 1) if total else 0,
        }
