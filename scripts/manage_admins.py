#!/usr/bin/env python3
"""
Manage the administrator accounts that can sign in to the DragonCP web interface.

This script is the ONLY way to create, rename, disable or reset an administrator.
There is no account-management screen in the web interface, and that is
deliberate: the right to create administrators is the right to reach the server,
which is a stronger boundary than any role the browser could enforce. The single
account change available in the browser is a signed-in person changing their own
password.

Run it on the machine hosting DragonCP, from the repository root. Changes take
effect immediately — the application reads the account table on every request,
so there is no need to restart it.

Usage:
    venv/bin/python scripts/manage_admins.py list
    venv/bin/python scripts/manage_admins.py show <username>
    venv/bin/python scripts/manage_admins.py add <username>
    venv/bin/python scripts/manage_admins.py add <username> --random --disabled
    venv/bin/python scripts/manage_admins.py rename <old-username> <new-username>
    venv/bin/python scripts/manage_admins.py reset <username>
    venv/bin/python scripts/manage_admins.py disable <username>
    venv/bin/python scripts/manage_admins.py enable <username>

Every command accepts --db either before or after the command name to point at a
database other than the default ./dragoncp.db.

Handing a password to someone else
----------------------------------
When the password will be seen by anything other than the person receiving it —
a shared terminal, a chat message, an AI assistant's transcript — create the
account switched off and turn it on at the moment of handover:

    venv/bin/python scripts/manage_admins.py add priya --random --disabled
    #  ...contact Priya, confirm she is ready to sign in...
    venv/bin/python scripts/manage_admins.py enable priya

Until `enable` runs, the password does nothing. That reduces the window in which
a password seen in passing could be used from however long the account sits
unclaimed to the handover itself. Afterwards, `show priya` reports when she
first signed in; a time you did not expect means somebody got there first, and
`reset` fixes it.

What each command does
----------------------
list      Show every account: name, whether it is enabled, when it last signed
          in, and whether it still owes a password change.

show      The same detail for one account.

add       Create an account. Prompts for a password twice unless --random or
          --password is given. The new account must change its password at first
          sign-in unless --no-force-change is passed, because the password was
          chosen by whoever ran this script rather than by the person using it.
          --disabled creates it switched off, so the temporary password is inert
          until `enable` runs. See "Handing a password to someone else" above.

rename    Change an account's username, keeping its id, its history and its
          password. Use this instead of deleting and recreating: the activity
          trail refers to the account id, so a rename preserves the record while
          a recreate orphans it. Signs the account out everywhere.

reset     Set a new password for someone who is locked out. The account must
          change it again at next sign-in unless --no-force-change is passed.
          Signs the account out everywhere.

disable   Stop an account signing in. Their next request is refused at once;
          a live updates connection drops within about a minute. This is what to do
          when an administrator leaves. It is reversible with `enable`.

enable    Let a disabled account sign in again. It keeps its old password; use
          `reset` if that password should change too.

There is no delete command, on purpose. The activity trail points back at these
rows, so removing one would turn recorded history into references to nobody.
Disable the account instead — it can no longer sign in, and its past actions
still make sense.

The fallback account
--------------------
While no enabled account exists in the database, DragonCP accepts the
DRAGONCP_USERNAME / DRAGONCP_PASSWORD credentials from dragoncp_env.env as a
single administrator, exactly as it did before named accounts existed. Adding
the first enabled account switches that off, and any session opened against the
fallback stops working at that moment.

That fallback is also the way back in if every account gets disabled or the last
password is lost: disable the remaining accounts, or add a new one with this
script, and sign in with the environment credentials in the meantime.

Examples
--------
    # Add a colleague, letting the script pick a strong password to hand over.
    # Switched off until you enable it, so the printed password is inert.
    venv/bin/python scripts/manage_admins.py add priya --random --disabled
    venv/bin/python scripts/manage_admins.py enable priya

    # They forgot it
    venv/bin/python scripts/manage_admins.py reset priya

    # They changed their name
    venv/bin/python scripts/manage_admins.py rename priya priya.n

    # They left the team
    venv/bin/python scripts/manage_admins.py disable priya.n
"""

import argparse
import getpass
import os
import secrets
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from auth import hash_password  # noqa: E402
from models import DatabaseManager  # noqa: E402
from models.admin_account import (  # noqa: E402
    AdminAccount,
    AdminAccountError,
    MIN_PASSWORD_LENGTH,
    validate_password,
    validate_username,
)


GENERATED_PASSWORD_BYTES = 12


def _store(args) -> AdminAccount:
    db_manager = DatabaseManager(args.db)
    return AdminAccount(db_manager)


def _fail(message: str) -> int:
    print(f"❌ {message}")
    return 1


def _collect_password(args, purpose: str) -> str:
    """
    Work out the password to set: generated, given, or typed twice.

    A generated password is printed once — this script does not store anything
    it could show again later, so it has to be copied now.
    """
    if getattr(args, 'random', False):
        password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
        print(f"🔑 Generated password for {purpose}: {password}")
        print("   Copy it now and hand it over securely. It cannot be shown again.")
        return password

    if getattr(args, 'password', None):
        return args.password

    if not sys.stdin.isatty():
        raise AdminAccountError(
            "No password given and nothing to prompt with. "
            "Pass --random, or --password, or run this from a terminal."
        )

    first = getpass.getpass(f"New password for {purpose}: ")
    second = getpass.getpass("Repeat it: ")

    if first != second:
        raise AdminAccountError("The two passwords did not match.")

    return first


def _describe(account: dict) -> str:
    state = "enabled" if account['is_active'] else "DISABLED"
    last_login = account.get('last_login_at') or 'never'
    flags = []
    if account.get('must_change_password'):
        flags.append('must change password')
    suffix = f" ({', '.join(flags)})" if flags else ''
    return (
        f"  #{account['id']:<4} {account['username']:<24} {state:<9} "
        f"last sign-in: {last_login}{suffix}"
    )


def _warn_if_first_account(store: AdminAccount) -> None:
    """Say plainly that the environment fallback has just been switched off."""
    print(
        "\nℹ️  This is the first account that can sign in, so the fallback "
        "credentials\n   in dragoncp_env.env are no longer accepted. Anyone signed "
        "in with them\n   has been signed out."
    )


# ----- commands ------------------------------------------------------------

def cmd_list(args) -> int:
    store = _store(args)
    accounts = store.list_all()

    if not accounts:
        print(
            "No administrator accounts exist.\n"
            "Sign-in is using the fallback credentials from dragoncp_env.env.\n"
            "Create one with: venv/bin/python scripts/manage_admins.py add <username>"
        )
        return 0

    print(f"\n{len(accounts)} account(s):\n")
    for account in accounts:
        print(_describe(account))

    enabled = store.count_enabled()
    print()
    if enabled == 0:
        print(
            "⚠️  No account is enabled. Sign-in has fallen back to the credentials "
            "in dragoncp_env.env."
        )
    return 0


def cmd_show(args) -> int:
    store = _store(args)
    account = store.find_by_username(args.username)

    if account is None:
        return _fail(f"No account named '{args.username}'.")

    print()
    for label, key in (
        ('id', 'id'),
        ('username', 'username'),
        ('role', 'role'),
        ('enabled', 'is_active'),
        ('must change password', 'must_change_password'),
        ('last sign-in', 'last_login_at'),
        ('password changed', 'password_changed_at'),
        ('created', 'created_at'),
        ('updated', 'updated_at'),
    ):
        print(f"  {label:<22} {account.get(key)}")
    print()
    return 0


def cmd_add(args) -> int:
    store = _store(args)

    try:
        username = validate_username(args.username)
        was_empty = store.count_enabled() == 0
        password = _collect_password(args, username)
        validate_password(password)
        account = store.create(
            username,
            hash_password(password),
            must_change_password=not args.no_force_change,
            is_active=not args.disabled,
        )
    except AdminAccountError as error:
        return _fail(str(error))

    state = 'disabled' if not account['is_active'] else 'enabled'
    print(f"\n✅ Created account '{account['username']}' (id {account['id']}, {state}).")
    if account['must_change_password']:
        print("   They will be asked to choose a new password when they first sign in.")

    if not account['is_active']:
        # The whole point of --disabled: the password is inert until this runs,
        # so the window in which a password seen in passing could be used is
        # the handover itself rather than however long it sits unclaimed.
        print(
            "\n   The password will not work until you switch the account on. Do that\n"
            "   when they are ready to sign in:\n"
            f"       venv/bin/python scripts/manage_admins.py enable {account['username']}"
        )
    elif was_empty:
        _warn_if_first_account(store)

    return 0


def cmd_rename(args) -> int:
    store = _store(args)

    try:
        account = store.rename(args.old_username, args.new_username)
    except AdminAccountError as error:
        return _fail(str(error))

    print(
        f"\n✅ Renamed '{args.old_username}' to '{account['username']}' "
        f"(id {account['id']} is unchanged, so their history is intact)."
    )
    print("   They have been signed out and will need to sign in under the new name.")
    return 0


def cmd_reset(args) -> int:
    store = _store(args)
    account = store.find_by_username(args.username)

    if account is None:
        return _fail(f"No account named '{args.username}'.")

    try:
        password = _collect_password(args, account['username'])
        validate_password(password)
    except AdminAccountError as error:
        return _fail(str(error))

    updated = store.set_password(
        account['id'],
        hash_password(password),
        must_change_password=not args.no_force_change,
    )

    print(f"\n✅ Password reset for '{updated['username']}'.")
    print("   Their sessions are refused at once; live connections drop within a minute.")
    if updated['must_change_password']:
        print("   They will be asked to choose their own password when they sign in.")

    if not updated['is_active']:
        print(
            "\n⚠️  This account is disabled, so the new password will not let them in "
            "until you run:\n"
            f"   venv/bin/python scripts/manage_admins.py enable {updated['username']}"
        )

    return 0


def cmd_disable(args) -> int:
    store = _store(args)
    account = store.find_by_username(args.username)

    if account is None:
        return _fail(f"No account named '{args.username}'.")

    if not account['is_active']:
        print(f"ℹ️  '{account['username']}' is already disabled.")
        return 0

    updated = store.set_active(account['id'], False)

    print(f"\n✅ Disabled '{updated['username']}'.")
    print("   Their next request is refused; any live connection drops within a minute.")
    print("   Their recorded history is kept. Re-enable with:")
    print(f"   venv/bin/python scripts/manage_admins.py enable {updated['username']}")

    if store.count_enabled() == 0:
        print(
            "\n⚠️  No enabled account remains. Sign-in has fallen back to the "
            "credentials in\n   dragoncp_env.env until you enable or add one."
        )

    return 0


def cmd_enable(args) -> int:
    store = _store(args)
    account = store.find_by_username(args.username)

    if account is None:
        return _fail(f"No account named '{args.username}'.")

    if account['is_active']:
        print(f"ℹ️  '{account['username']}' is already enabled.")
        return 0

    was_empty = store.count_enabled() == 0
    updated = store.set_active(account['id'], True)

    print(f"\n✅ Enabled '{updated['username']}'. Their previous password still applies.")
    print("   Use `reset` if that password should change too.")

    if was_empty:
        _warn_if_first_account(store)

    return 0


# ----- wiring --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='manage_admins.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--db',
        default='dragoncp.db',
        help='Database file to act on (default: ./dragoncp.db). Accepted either '
             'before or after the command.',
    )

    # Also offered on each subcommand, because `add alice --db x.db` is the
    # order people reach for. SUPPRESS is essential: without it the subparser
    # would apply its own default and silently overwrite a --db given before
    # the command, pointing the run at the wrong database.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--db', default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest='command', required=True)

    subparsers.add_parser('list', parents=[shared], help='Show every account').set_defaults(func=cmd_list)

    show = subparsers.add_parser('show', parents=[shared], help='Show one account in detail')
    show.add_argument('username')
    show.set_defaults(func=cmd_show)

    def add_password_options(sub):
        sub.add_argument(
            '--password',
            help='Set this password instead of prompting. Avoid on a shared machine: '
                 'it will be visible in your shell history and process list.',
        )
        sub.add_argument(
            '--random',
            action='store_true',
            help='Generate a strong password and print it once.',
        )
        sub.add_argument(
            '--no-force-change',
            action='store_true',
            help='Do not require a password change at next sign-in.',
        )

    add = subparsers.add_parser('add', parents=[shared], help='Create an account')
    add.add_argument('username')
    add.add_argument(
        '--disabled',
        action='store_true',
        help='Create the account switched off, so the temporary password does '
             'nothing until you run `enable`. Use this whenever the password '
             'will be visible to anything other than the person receiving it — '
             'a shared terminal, a chat message, an assistant transcript.',
    )
    add_password_options(add)
    add.set_defaults(func=cmd_add)

    rename = subparsers.add_parser(
        'rename', parents=[shared],
        help="Change an account's username, keeping its history",
    )
    rename.add_argument('old_username')
    rename.add_argument('new_username')
    rename.set_defaults(func=cmd_rename)

    reset = subparsers.add_parser('reset', parents=[shared], help="Set a new password for an account")
    reset.add_argument('username')
    add_password_options(reset)
    reset.set_defaults(func=cmd_reset)

    disable = subparsers.add_parser('disable', parents=[shared], help='Stop an account signing in')
    disable.add_argument('username')
    disable.set_defaults(func=cmd_disable)

    enable = subparsers.add_parser('enable', parents=[shared], help='Let a disabled account sign in again')
    enable.add_argument('username')
    enable.set_defaults(func=cmd_enable)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, 'password', None) and getattr(args, 'random', False):
        return _fail('Use either --password or --random, not both.')

    if getattr(args, 'password', None):
        try:
            validate_password(args.password)
        except AdminAccountError as error:
            return _fail(f"{error} (minimum {MIN_PASSWORD_LENGTH} characters)")

    try:
        return args.func(args)
    except AdminAccountError as error:
        return _fail(str(error))
    except KeyboardInterrupt:
        print('\nCancelled.')
        return 130


if __name__ == '__main__':
    sys.exit(main())
