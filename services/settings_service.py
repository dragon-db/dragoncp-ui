#!/usr/bin/env python3
"""
Reading and writing settings, on the right side of the boundary.

`settings_registry` says where each setting lives; this reads and writes it.
Nothing else in the application needs to know which store a value came from.

The one rule worth stating: a DB-backed setting is read from the database on
every use, not cached. Changing the retention rule or an auto-sync toggle has
to take effect on the next transfer without a restart — that is the entire
point of it being in the database, and caching it would quietly undo that.
"""

from typing import Any, Dict, List, Optional, Tuple

import settings_registry as registry
from settings_registry import DB, ENV, REDACTED, Setting


class SettingsService:
    """One reader and one writer for both stores."""

    def __init__(self, config, settings_model):
        self.config = config
        self.settings = settings_model

    # ---- reading ----------------------------------------------------------

    def get(self, key: str, default: Optional[str] = None) -> str:
        setting = registry.get(key)
        if setting is None:
            # Not in the registry: fall back to the env file rather than
            # pretending it does not exist. Anything reaching here is a key the
            # registry has not caught up with yet.
            return self.config.get(key, default or '')

        if setting.store == DB:
            stored = self.settings.get(key)
            # A stored empty string is an ANSWER, not an absence: it is how an
            # operator clears a webhook URL or an icon. Treating it as missing
            # sent the request back to the env file, so clearing the Discord
            # webhook in the UI silently kept posting to the old one.
            if stored is not None:
                return stored
            # With no row at all, an env-file value is honoured as the default,
            # so an existing install keeps working before anything is saved and
            # a fresh one can be seeded from the file.
            from_env = self.config.get(key, '')
            if from_env not in (None, ''):
                return from_env
            return setting.default if default is None else default

        value = self.config.get(key, '')
        if value in (None, ''):
            return setting.default if default is None else default
        return value

    def get_bool(self, key: str, default: bool = False) -> bool:
        # `get(key)` with no default so the registry's own default applies; the
        # caller's is only reached when the registry has nothing either.
        raw = self.get(key)
        if raw in (None, ''):
            return default
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')

    def get_int(self, key: str, default: int = 0) -> int:
        raw = self.get(key)
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return default
        setting = registry.get(key)
        if setting:
            if setting.minimum is not None:
                value = max(setting.minimum, value)
            if setting.maximum is not None:
                value = min(setting.maximum, value)
        return value

    # ---- writing ----------------------------------------------------------

    def set_many(self, payload: Dict[str, Any]) -> Tuple[Dict[str, str], List[str], List[str]]:
        """
        Write the editable settings in a payload.

        Returns (saved, refused, errors). Env-backed keys are refused BY NAME
        rather than ignored, so the UI can say which ones and why instead of
        reporting a save that half happened.
        """
        refused: List[str] = []
        errors: List[str] = []
        pending: Dict[str, str] = {}

        for key, value in (payload or {}).items():
            setting = registry.get(key)
            if setting is None:
                refused.append(key)
                continue
            if not setting.editable:
                refused.append(key)
                continue
            # A redacted placeholder coming back means "unchanged", not "set it
            # to the literal string <redacted>".
            if setting.sensitive and value == REDACTED:
                continue
            try:
                pending[key] = registry.coerce(setting, value)
            except ValueError as error:
                errors.append(str(error))

        # Validate the WHOLE payload before writing any of it. Coercing and
        # committing key by key meant one bad value at the end of a form left
        # every setting before it already changed, while the response said the
        # save had failed — so the screen and the database disagreed.
        if errors:
            return {}, refused, errors

        if pending:
            writer = getattr(self.settings, 'write_many', None)
            if callable(writer):
                writer(pending)
            else:
                for key, stored in pending.items():
                    self.settings.set(key, stored)

        return dict(pending), refused, errors

    def set(self, key: str, value: Any) -> str:
        saved, refused, errors = self.set_many({key: value})
        if errors:
            raise ValueError(errors[0])
        if refused:
            raise PermissionError(
                f"{key} is set in the environment file and cannot be changed here"
            )
        return saved.get(key, '')

    # ---- describing, for the UI ------------------------------------------

    def describe(self) -> Dict:
        """
        Every setting, its value, and whether it can be changed here.

        Env-backed secrets are omitted entirely rather than redacted — there is
        nothing a reader could do with a redacted value they cannot change, and
        listing them only advertises what is on the server.
        """
        groups: Dict[str, Dict] = {
            key: {'id': key, 'label': label, 'settings': []}
            for key, label in registry.GROUPS
        }

        for setting in registry.SETTINGS:
            if setting.store == ENV and setting.hidden:
                continue
            groups[setting.group]['settings'].append(self._describe_one(setting))

        return {
            'groups': [g for g in groups.values() if g['settings']],
            'stores': {
                'env': {
                    'label': 'Environment file',
                    'description': (
                        'Set once when the installation is built — where the media lives, how to '
                        'reach the remote, and everything that is a security boundary. Shown here '
                        'read-only; change them in dragoncp_env.env on the server and restart.'
                    ),
                },
                'db': {
                    'label': 'Application settings',
                    'description': (
                        'Changed while running. Saved to the database, effective immediately, and '
                        'shared by every operator and every background job.'
                    ),
                },
            },
        }

    def _describe_one(self, setting: Setting) -> Dict:
        # No default passed, so the registry's own default is what shows when
        # nothing is stored. Passing '' here suppressed it and made a setting
        # with a real default look empty.
        value = self.get(setting.key)
        if setting.sensitive:
            shown: Any = REDACTED if value else ''
        elif setting.kind == 'boolean':
            shown = str(value).strip().lower() in ('1', 'true', 'yes', 'on')
        else:
            shown = value

        described = {
            'key': setting.key,
            'store': setting.store,
            'group': setting.group,
            'label': setting.label,
            'description': setting.description,
            'kind': setting.kind,
            'editable': setting.editable,
            'sensitive': setting.sensitive,
            'value': shown,
        }
        if setting.minimum is not None:
            described['minimum'] = setting.minimum
        if setting.maximum is not None:
            described['maximum'] = setting.maximum
        if setting.store == DB:
            # No row at all, rather than a row someone deliberately emptied.
            described['is_default'] = self.settings.get(setting.key) is None
        return described

    def flat(self, include_env: bool = True) -> Dict[str, str]:
        """
        Every visible setting as a plain key -> value map.

        The shape the legacy static UI reads. It is what production still
        serves, so the current API returns this alongside the grouped payload
        rather than breaking that page. Sensitive values are redacted; env
        secrets marked hidden are omitted entirely, as they are in `describe`.
        """
        values: Dict[str, str] = {}
        for setting in registry.SETTINGS:
            if setting.store == ENV:
                if setting.hidden:
                    continue
                if not include_env:
                    continue
            value = self.get(setting.key)
            values[setting.key] = REDACTED if (setting.sensitive and value) else value
        return values

    def env_only(self) -> Dict[str, str]:
        """
        What the environment file holds, for the legacy UI's comparison column.

        It used to contrast the env file against a per-browser overlay. There is
        no overlay any more, so this is simply the env-backed settings — which
        is also exactly what that column was trying to show.
        """
        values: Dict[str, str] = {}
        for setting in registry.SETTINGS:
            if setting.store != ENV or setting.hidden:
                continue
            value = self.get(setting.key)
            values[setting.key] = REDACTED if (setting.sensitive and value) else value
        return values

    # ---- one-time adoption ------------------------------------------------

    def adopt_env_defaults(self) -> List[str]:
        """
        Copy DB-eligible values found in the env file into the database, once.

        Run at startup. Without it, moving a setting across the boundary would
        change behaviour on the way over: the env value would keep working as a
        fallback until someone saved something, and then silently stop being
        the source of truth. Copying it makes the database authoritative
        immediately, with the value the installation already had.

        Only writes keys with no row at all, so it never overwrites a
        deliberate choice, and it is safe to run on every start. A row holding
        an empty string counts as a choice — that is how a value is cleared,
        and re-adopting over it put the env value back on every restart.
        """
        adopted = []
        for setting in registry.SETTINGS:
            if setting.store != DB:
                continue
            if self.settings.get(setting.key) is not None:
                continue
            from_env = self.config.get(setting.key, '')
            if from_env in (None, ''):
                continue
            try:
                self.settings.set(setting.key, registry.coerce(setting, from_env))
                adopted.append(setting.key)
            except ValueError:
                continue
        return adopted
