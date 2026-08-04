#!/usr/bin/env python3
"""
DragonCP Admin Account Model
Data access for the accounts allowed to sign in to the web interface.

Accounts are created and maintained from the server with
`scripts/manage_admins.py`. There is deliberately no account-management UI:
the right to create administrators is the right to reach the server, which is
a stronger boundary than any role we could enforce in the browser.

Rows are never deleted. The activity trail refers back to them, so an admin
who leaves is disabled and keeps their history.
"""

import re
import sqlite3
from typing import Dict, List, Optional


# Usernames appear next to automated actors in the activity trail. Reserving the
# automation prefixes here means a human can never be created with a name that
# reads like the scheduler or a webhook did the work.
RESERVED_USERNAME_PREFIXES = ('auto', 'system')
RESERVED_USERNAMES = {'auto', 'automated', 'system', 'unknown', 'none', 'null'}

USERNAME_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9._-]{2,31}$')

MIN_PASSWORD_LENGTH = 10


class AdminAccountError(ValueError):
    """A rejected account operation, with a message meant for a human."""


def validate_username(username: str) -> str:
    """
    Normalise and check a username, or explain why it cannot be used.

    Returns the cleaned username. Raises AdminAccountError otherwise.
    """
    cleaned = (username or '').strip()

    if not USERNAME_PATTERN.match(cleaned):
        raise AdminAccountError(
            "Username must start with a letter, be 3-32 characters, and contain "
            "only letters, numbers, dots, dashes or underscores."
        )

    lowered = cleaned.lower()

    if lowered in RESERVED_USERNAMES:
        raise AdminAccountError(f"'{cleaned}' is reserved and cannot be used as a username.")

    for prefix in RESERVED_USERNAME_PREFIXES:
        if lowered.startswith(prefix):
            raise AdminAccountError(
                f"Usernames cannot start with '{prefix}' — that prefix is reserved for "
                "automated activity so people and automation stay distinguishable."
            )

    return cleaned


def validate_password(password: str) -> str:
    """Check a new password meets the minimum bar, or say what is wrong."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise AdminAccountError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if password.strip() != password:
        raise AdminAccountError("Password cannot start or end with a space.")
    return password


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict]:
    if row is None:
        return None
    account = dict(row)
    account['is_active'] = bool(account.get('is_active', 0))
    account['must_change_password'] = bool(account.get('must_change_password', 0))
    return account


class AdminAccount:
    """Read and write the admin_account table."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ----- reads -----------------------------------------------------------

    def find_by_username(self, username: str) -> Optional[Dict]:
        """Look up an account by name. Matching ignores case."""
        if not username:
            return None
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM admin_account WHERE username = ?',
                (username.strip(),)
            ).fetchone()
        return _row_to_dict(row)

    def find_by_id(self, account_id: int) -> Optional[Dict]:
        """Look up an account by its stable id."""
        if account_id is None:
            return None
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM admin_account WHERE id = ?',
                (account_id,)
            ).fetchone()
        return _row_to_dict(row)

    def list_all(self) -> List[Dict]:
        """Every account, enabled first, then alphabetical."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM admin_account ORDER BY is_active DESC, username COLLATE NOCASE'
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def count_enabled(self) -> int:
        """
        How many accounts can currently sign in.

        Zero is what hands sign-in back to the credentials in the environment
        file — see auth.py. That covers both a fresh install and the case where
        every account has been disabled.
        """
        with self.db.get_connection() as conn:
            row = conn.execute(
                'SELECT COUNT(*) AS total FROM admin_account WHERE is_active = 1'
            ).fetchone()
        return int(row['total'] if row else 0)

    def count_all(self) -> int:
        """How many accounts exist, enabled or not."""
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT COUNT(*) AS total FROM admin_account').fetchone()
        return int(row['total'] if row else 0)

    # ----- writes ----------------------------------------------------------

    def create(
        self,
        username: str,
        password_hash: str,
        must_change_password: bool = True,
        role: str = 'admin',
        is_active: bool = True,
    ) -> Dict:
        """
        Add an account. Raises AdminAccountError if the name is taken.

        New accounts are flagged to change their password on first sign-in,
        because the password was chosen by whoever ran the script rather than
        by the person who will be using it.

        `is_active=False` creates the account switched off. That is the safe way
        to hand credentials over: the temporary password is inert until someone
        enables the account, so it cannot be used by anyone who saw it in
        passing — a terminal scrollback, a chat log, an assistant transcript —
        before the intended person gets to it.
        """
        cleaned = validate_username(username)

        with self.db.get_connection() as conn:
            try:
                conn.execute(
                    '''
                    INSERT INTO admin_account
                        (username, password_hash, role, is_active, token_version,
                         must_change_password, password_changed_at)
                    VALUES (?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                    ''',
                    (
                        cleaned,
                        password_hash,
                        role,
                        1 if is_active else 0,
                        1 if must_change_password else 0,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise AdminAccountError(f"An account named '{cleaned}' already exists.")

        return self.find_by_username(cleaned)

    def rename(self, old_username: str, new_username: str) -> Dict:
        """
        Change an account's username, keeping its id and its history.

        Retires the account's existing sign-in sessions: a token issued under
        the old name would otherwise keep presenting it.
        """
        cleaned = validate_username(new_username)
        account = self.find_by_username(old_username)

        if account is None:
            raise AdminAccountError(f"No account named '{old_username}'.")

        if account['username'].lower() == cleaned.lower():
            # Same name in a different case — allowed, and worth supporting so a
            # capitalisation can be corrected.
            if account['username'] == cleaned:
                raise AdminAccountError(f"'{cleaned}' is already the username.")

        with self.db.get_connection() as conn:
            try:
                conn.execute(
                    '''
                    UPDATE admin_account
                       SET username = ?,
                           token_version = token_version + 1,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?
                    ''',
                    (cleaned, account['id']),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise AdminAccountError(f"An account named '{cleaned}' already exists.")

        return self.find_by_id(account['id'])

    def set_password(
        self,
        account_id: int,
        password_hash: str,
        must_change_password: bool = False,
    ) -> Dict:
        """
        Replace an account's password and retire its existing sessions.

        Callers who are changing their own password need to issue themselves a
        fresh token afterwards, since this invalidates the one they arrived with.
        """
        with self.db.get_connection() as conn:
            conn.execute(
                '''
                UPDATE admin_account
                   SET password_hash = ?,
                       must_change_password = ?,
                       token_version = token_version + 1,
                       password_changed_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                ''',
                (password_hash, 1 if must_change_password else 0, account_id),
            )
            conn.commit()

        return self.find_by_id(account_id)

    def set_active(self, account_id: int, is_active: bool) -> Dict:
        """
        Enable or disable an account.

        Disabling retires the account's sessions so it takes effect at once
        rather than whenever the person's token happens to expire.
        """
        with self.db.get_connection() as conn:
            if is_active:
                conn.execute(
                    '''
                    UPDATE admin_account
                       SET is_active = 1, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?
                    ''',
                    (account_id,),
                )
            else:
                conn.execute(
                    '''
                    UPDATE admin_account
                       SET is_active = 0,
                           token_version = token_version + 1,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?
                    ''',
                    (account_id,),
                )
            conn.commit()

        return self.find_by_id(account_id)

    def record_login(self, account_id: int) -> None:
        """Stamp a successful sign-in."""
        with self.db.get_connection() as conn:
            conn.execute(
                'UPDATE admin_account SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?',
                (account_id,),
            )
            conn.commit()
