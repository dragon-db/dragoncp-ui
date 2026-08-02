#!/usr/bin/env python3
"""
The settings boundary, in one place.

Two stores, and only two:

  ENV  — things that do not change once an installation is set up: where the
         media lives, how to reach the remote, and everything that is a
         security boundary. Editing these is a deliberate act on the server.
  DB   — things an operator changes while running it: automation toggles,
         notification targets, retention, timeouts. Editable from the UI,
         effective immediately, visible to background threads.

There used to be a third — a per-browser Flask session — and it was the source
of a persistent lie: `config.get()` only consulted it when an HTTP request was
in flight, so every background thread (the transfer monitor, the auto-sync
scheduler, the backup sorter) silently fell through to the env file. Sixteen
settings appeared editable in the UI and were ignored by the machinery that
used them. That store is gone; this registry replaces it.

Adding a setting means adding one row here. Nothing else needs to know where a
value lives — `SettingsResolver.get()` answers that from this table.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ENV = 'env'
DB = 'db'


@dataclass(frozen=True)
class Setting:
    key: str
    store: str                      # ENV | DB
    group: str
    label: str
    description: str
    kind: str = 'text'              # text | password | number | boolean | path
    default: str = ''
    sensitive: bool = False
    #: Only meaningful for DB settings — the bounds the UI and the writer clamp to.
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    #: ENV settings that are secrets are never sent to the client at all, not
    #: even redacted, because there is nothing a reader could do with them.
    hidden: bool = False
    aliases: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def editable(self) -> bool:
        return self.store == DB


# ===========================================================================
# ENV — constant for an installation
# ===========================================================================

_ENV_SETTINGS: List[Setting] = [
    # ---- credentials and secrets -----------------------------------------
    # These stay in the env file deliberately. The database is not an
    # encrypted store, and a secret editable from a web form is a secret
    # editable by anyone who reaches that form — including with a session
    # minted by the very key they would be changing.
    Setting('SECRET_KEY', ENV, 'security', 'Flask session key',
            'Signs the session cookie. Read once at startup, so a change needs a restart.',
            kind='password', sensitive=True, hidden=True),
    Setting('JWT_SECRET_KEY', ENV, 'security', 'Token signing key',
            'Signs API tokens. Changing it logs everyone out.',
            kind='password', sensitive=True, hidden=True),
    Setting('JWT_EXPIRY_HOURS', ENV, 'security', 'Token lifetime (hours)',
            'How long a login lasts before it has to be refreshed.',
            kind='number', default='24'),
    Setting('DRAGONCP_USERNAME', ENV, 'security', 'Operator username',
            'The single admin login.'),
    Setting('DRAGONCP_PASSWORD', ENV, 'security', 'Operator password',
            'Plain-text password, used when no hash is set.',
            kind='password', sensitive=True, hidden=True),
    Setting('DRAGONCP_PASSWORD_HASH', ENV, 'security', 'Operator password hash',
            'Preferred over the plain-text password when present.',
            kind='password', sensitive=True, hidden=True),
    Setting('WEBHOOK_SECRET', ENV, 'security', 'Webhook signing secret',
            'Verifies Radarr/Sonarr requests. One of the two public-facing controls.',
            kind='password', sensitive=True, hidden=True),
    Setting('WEBHOOK_ALLOWED_IPS', ENV, 'security', 'Webhook IP allowlist',
            'The other public-facing control. Comma-separated.'),
    Setting('CORS_ORIGINS', ENV, 'security', 'Allowed origins',
            'Which origins may call the API. Read once at startup.'),
    Setting('SSH_HOST_KEY_CHECKING', ENV, 'security', 'SSH host-key policy',
            'strict | accept-new | auto-add. Protects against a substituted remote host.',
            default='accept-new'),
    Setting('SSH_KNOWN_HOSTS_FILE', ENV, 'security', 'Known hosts file',
            'Where verified remote host keys are kept.', kind='path'),

    # ---- the remote ------------------------------------------------------
    Setting('REMOTE_IP', ENV, 'remote', 'Remote host',
            'The media server this pulls from.'),
    Setting('REMOTE_USER', ENV, 'remote', 'Remote user', 'SSH username.'),
    Setting('REMOTE_PASSWORD', ENV, 'remote', 'Remote password',
            'Used when no SSH key is configured.', kind='password', sensitive=True, hidden=True),
    Setting('SSH_KEY_PATH', ENV, 'remote', 'SSH key', 'Private key used to connect.',
            kind='path'),

    # ---- where the media lives -------------------------------------------
    # These are the security boundary: `get_all_allowed_paths()` returns
    # exactly this set, and every traversal check validates against it. They
    # are read-only in the UI on purpose — widening the only boundary that
    # stops a crafted webhook writing outside the media directories should not
    # be possible from a browser.
    Setting('MOVIE_PATH', ENV, 'library', 'Movies (remote)',
            'Source directory on the remote host.', kind='path'),
    Setting('TVSHOW_PATH', ENV, 'library', 'TV Shows (remote)',
            'Source directory on the remote host.', kind='path'),
    Setting('ANIME_PATH', ENV, 'library', 'Anime (remote)',
            'Source directory on the remote host.', kind='path'),
    Setting('MOVIE_DEST_PATH', ENV, 'library', 'Movies (local)',
            'Where movies are written. Part of the path-traversal boundary.', kind='path'),
    Setting('TVSHOW_DEST_PATH', ENV, 'library', 'TV Shows (local)',
            'Where series are written. Part of the path-traversal boundary.', kind='path'),
    Setting('ANIME_DEST_PATH', ENV, 'library', 'Anime (local)',
            'Where anime is written. Part of the path-traversal boundary.', kind='path'),
    Setting('BACKUP_PATH', ENV, 'library', 'Backups',
            'Where displaced media is kept. Required — without it, transfers refuse to start.',
            kind='path'),

    # ---- disk reporting --------------------------------------------------
    Setting('DISK_PATH_1', ENV, 'disks', 'Disk 1', 'Local path to report usage for.',
            kind='path'),
    Setting('DISK_PATH_2', ENV, 'disks', 'Disk 2', 'Local path to report usage for.',
            kind='path'),
    Setting('DISK_PATH_3', ENV, 'disks', 'Disk 3', 'Local path to report usage for.',
            kind='path'),
    Setting('DISK_API_ENDPOINT', ENV, 'disks', 'Remote disk API',
            'Endpoint reporting the remote host’s free space.'),
    Setting('DISK_API_TOKEN', ENV, 'disks', 'Remote disk API token',
            'Bearer token for that endpoint.', kind='password', sensitive=True, hidden=True),

    # ---- runtime ---------------------------------------------------------
    Setting('TEST_MODE', ENV, 'runtime', 'Test mode',
            'Every write becomes a dry run. Read from the process environment at startup.',
            kind='boolean', default='0'),
]


# ===========================================================================
# DB — what an operator changes while running it
# ===========================================================================

_DB_SETTINGS: List[Setting] = [
    Setting('AUTO_SYNC_MOVIES', DB, 'automation', 'Auto-sync movies',
            'Start a transfer as soon as Radarr reports a new movie.',
            kind='boolean', default='false'),
    Setting('AUTO_SYNC_SERIES', DB, 'automation', 'Auto-sync TV shows',
            'Start a transfer once a season’s episodes have settled.',
            kind='boolean', default='false'),
    Setting('AUTO_SYNC_ANIME', DB, 'automation', 'Auto-sync anime',
            'Start a transfer once a season’s episodes have settled.',
            kind='boolean', default='false'),
    # SECONDS, not minutes — `AutoSyncScheduler.schedule_job` adds it straight
    # to `time.time()`. The bounds are the ones the webhook settings route was
    # already applying; they live here now so there is one clamp rather than a
    # route that enforced 30-900 and a reader that enforced nothing.
    Setting('SERIES_ANIME_SYNC_WAIT_TIME', DB, 'automation', 'Batch wait (seconds)',
            'How long to wait for more episodes of a season before starting a transfer.',
            kind='number', default='60', minimum=30, maximum=900),

    Setting('DISCORD_NOTIFICATIONS_ENABLED', DB, 'notifications', 'Discord notifications',
            'Send a message when a transfer finishes, fails or a rename completes.',
            kind='boolean', default='false'),
    Setting('DISCORD_WEBHOOK_URL', DB, 'notifications', 'Discord webhook URL',
            'Where those messages go.', kind='password', sensitive=True),
    Setting('DISCORD_APP_URL', DB, 'notifications', 'App URL',
            'Used to link back to this app from a notification.',
            default='http://localhost:5000'),
    Setting('DISCORD_ICON_URL', DB, 'notifications', 'Notification icon',
            'Image shown beside the message.'),
    Setting('DISCORD_MANUAL_SYNC_THUMBNAIL_URL', DB, 'notifications',
            'Manual-sync thumbnail', 'Image used for manually started transfers.'),

    Setting('BACKUP_RETENTION_ENABLED', DB, 'backups', 'Prune old versions',
            'Remove old backup versions automatically once a new one is stored.',
            kind='boolean', default='true'),
    Setting('BACKUP_RETENTION_KEEP', DB, 'backups', 'Versions to keep',
            'How many previous versions of each movie or episode to keep.',
            kind='number', default='2', minimum=1, maximum=50),
    Setting('BACKUP_RETENTION_GRACE_HOURS', DB, 'backups', 'Grace period (hours)',
            'How long a new version is protected from the rule above.',
            kind='number', default='24', minimum=0, maximum=720),

    Setting('WEBSOCKET_TIMEOUT_MINUTES', DB, 'runtime', 'Realtime idle timeout (minutes)',
            'How long the realtime connection stays open with no activity.',
            kind='number', default='30', minimum=5, maximum=60),
]


SETTINGS: Tuple[Setting, ...] = tuple(_ENV_SETTINGS + _DB_SETTINGS)
BY_KEY: Dict[str, Setting] = {s.key: s for s in SETTINGS}

#: Keys an operator may write. Everything else is refused, by key, at the route.
EDITABLE_KEYS: Tuple[str, ...] = tuple(s.key for s in SETTINGS if s.editable)

#: Keys that used to be settable through the removed session store and are now
#: read-only. Named so the API can say *why* rather than just refusing.
ENV_ONLY_KEYS: Tuple[str, ...] = tuple(s.key for s in SETTINGS if not s.editable)

GROUPS: Tuple[Tuple[str, str], ...] = (
    ('remote', 'Remote host'),
    ('library', 'Media directories'),
    ('disks', 'Disk reporting'),
    ('security', 'Security'),
    ('automation', 'Automation'),
    ('notifications', 'Notifications'),
    ('backups', 'Backups'),
    ('runtime', 'Runtime'),
)

REDACTED = '<redacted>'


def get(key: str) -> Optional[Setting]:
    return BY_KEY.get(key)


def is_editable(key: str) -> bool:
    setting = BY_KEY.get(key)
    return bool(setting and setting.editable)


def coerce(setting: Setting, value: Any) -> str:
    """
    Turn a submitted value into what gets stored, or raise ValueError.

    Numbers are clamped rather than rejected: an operator typing 999 into a
    field that tops out at 60 meant "as high as it goes", and refusing the
    whole save over it helps nobody.
    """
    if setting.kind == 'boolean':
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return 'true' if str(value).strip().lower() in ('1', 'true', 'yes', 'on') else 'false'

    if setting.kind == 'number':
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{setting.label} must be a number")
        if setting.minimum is not None:
            number = max(setting.minimum, number)
        if setting.maximum is not None:
            number = min(setting.maximum, number)
        return str(number)

    if value is None:
        return ''
    text = str(value)
    if '\0' in text:
        raise ValueError(f"{setting.label} contains an invalid character")
    return text.strip()
