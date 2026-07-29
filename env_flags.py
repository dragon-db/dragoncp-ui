#!/usr/bin/env python3
"""
One reading of boolean environment variables, shared by everything that needs one.

This exists because there were two. The startup banner and the runtime profile
read `TEST_MODE` permissively - `1`, `true`, `yes` and `on` all counted - while
every safety check that actually puts rsync into `--dry-run`, or skips a delete,
compared against the exact string `'1'`. So `TEST_MODE=true` produced an
installation that announced itself as test mode, logged itself as test mode, and
copied and deleted files for real.

The permissive reading wins, deliberately. Someone who writes `TEST_MODE=true`
means it, and the two possible mistakes are not equal: treating a truthy value as
off runs real transfers while claiming otherwise, whereas treating it as on runs
a dry run when someone wanted a real copy. Only one of those loses data.
"""

import os


# Written the way people actually write booleans in an env file.
TRUE_VALUES = {'1', 'true', 'yes', 'on'}


def env_flag(name: str, default: bool = False) -> bool:
    """Whether a boolean environment variable is set to something truthy."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in TRUE_VALUES


def test_mode_enabled() -> bool:
    """
    Whether this installation is in test mode.

    Read live rather than captured at import, because the tests and the CLI both
    set it after the modules are loaded.
    """
    return env_flag('TEST_MODE', default=False)
