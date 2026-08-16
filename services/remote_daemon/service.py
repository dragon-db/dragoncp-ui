#!/usr/bin/env python3
"""
Owning the transfer server on the remote host from here.

Install it, start and stop it, ask how it is, and take it away again. Everything
it runs is generated on this machine and pushed, so there is never a question of
what is over there — and taking it away is a complete statement rather than a
best guess. See `layout.py` for the list of everything installed.

The control channel is SSH, which is the right tool for it: the payload is a few
kilobytes of configuration, so the speed ceiling that started this whole project
is irrelevant here, and it keeps working when the transfer server itself is
unreachable — which is exactly when it is needed.

Supervision is not written here. The account already permits services that
restart on failure and survive a reboot, and every other application on that
host is run that way. A supervisor of our own would need a supervisor.

SECURITY
- The password is generated here, never chosen, and kept in a file this
  application owns at owner-only permissions. It is pushed over the file
  transfer channel, never on a command line.
- The address allowed to connect comes from the environment file and is never
  written to the database, never returned to a browser, and never logged.
- Every library is published read only, so nothing can be written, replaced or
  deleted through this channel.
"""

import os
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from typing import Callable, Dict, List, Optional, Tuple

from ssh import SSHManager

from . import layout, probe, render

#: Where the generated password is kept on this machine. It sits beside the
#: managed known_hosts file and for the same reason: it is neither a constant an
#: operator sets nor a preference they change, but a credential this application
#: generates and owns. Excluded from version control.
SECRET_FILENAME = 'dragoncp_rsyncd.secret'

#: How long a health answer is reused. Long enough that a batch of queued
#: transfers asks once rather than once each; short enough that the panel is not
#: reporting yesterday's news.
PROBE_CACHE_SECONDS = 20.0

#: Every remote command is prefixed with this. A non-interactive session usually
#: has the user service manager's address set already, but "usually" is not a
#: property to build the start button on.
_USER_ENV = 'export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"; '


def _app_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RemoteDaemonError(Exception):
    """Something went wrong that the operator needs to read."""


class RemoteDaemonService:
    """Install, control and inspect the transfer server on the remote host."""

    def __init__(self, config, settings_service):
        self.config = config
        self.settings = settings_service
        self._probe_cache: Optional[Tuple[float, probe.ProbeResult]] = None
        self._lock = threading.Lock()
        # Held while a transfer is deciding to use the server, and while the
        # idle shutdown decides to stop it. Separate from the cache lock, which
        # is taken for microseconds; this one is held across SSH round trips.
        self._use_lock = threading.RLock()

    # ---- configuration ----------------------------------------------------

    @property
    def host(self) -> str:
        return (self.config.get('REMOTE_IP') or '').strip()

    @property
    def port(self) -> int:
        try:
            return int(str(self.settings.get('RSYNC_DAEMON_PORT')).strip())
        except (TypeError, ValueError):
            return 0

    @property
    def access_mode(self) -> str:
        mode = (self.settings.get('FAST_TRANSPORT_ACCESS_MODE') or '').strip().lower()
        return mode if mode in (render.ACCESS_RESTRICTED, render.ACCESS_PASSWORD_ONLY) \
            else render.ACCESS_RESTRICTED

    @property
    def allowed_address(self) -> str:
        """
        The one address permitted to connect.

        Read from the environment file only. It is never copied into the
        database and never returned to a browser — the operator treats it as
        private, and a value that exists in one place is a value that can only
        leak from one place.
        """
        return (self.config.get('RSYNC_DAEMON_ALLOWED_IP') or '').strip()

    @property
    def start_at_boot(self) -> bool:
        """
        Whether the service is registered to come up on its own.

        Off by default. The transfer server only needs to be listening while a
        transfer is running, and a port that is open for minutes a day is a much
        smaller thing to defend than one that is open always.
        """
        return (self.settings.get('FAST_TRANSPORT_LIFECYCLE') or '').strip().lower() == 'always'

    def module_roots(self) -> List[Tuple[str, str]]:
        return layout.module_roots(self.settings)

    def configured(self) -> Tuple[bool, str]:
        """Whether there is enough here to install anything."""
        if not self.host:
            return False, 'No remote host is configured'
        if not self.port:
            return False, 'No port is configured for the transfer server'
        if not self.module_roots():
            return False, 'No media directories are configured on the remote host'
        if self.access_mode == render.ACCESS_RESTRICTED and not self.allowed_address:
            return False, (
                'No allowed address is set. Add RSYNC_DAEMON_ALLOWED_IP to the '
                'environment file, or switch to password-only access.'
            )
        return True, ''

    # ---- the generated password -------------------------------------------

    def _secret_file(self) -> str:
        return os.path.join(_app_dir(), SECRET_FILENAME)

    def password(self, create: bool = True) -> str:
        """
        The transfer server's password, generated on first use.

        Generated rather than chosen: this is the credential protecting a
        read-only view of the media library, and the one way it becomes weak is
        someone picking it.
        """
        path = self._secret_file()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    existing = handle.read().strip()
                if existing:
                    return existing
            except OSError as error:
                raise RemoteDaemonError(f"Could not read the stored password: {error}")
        if not create:
            return ''
        return self.rotate_password()

    def rotate_password(self) -> str:
        """Generate and store a new password. Reinstall is what applies it."""
        path = self._secret_file()
        value = secrets.token_urlsafe(32)
        try:
            # Created owner-only from the outset rather than chmod'ed afterwards,
            # so the secret never exists at the umask's default permissions.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as handle:
                # Narrowed BEFORE the secret is written, not after. The mode
                # passed to os.open only applies when the file is created, so
                # rotating over an existing world-readable file would otherwise
                # write the new password into it at the old permissions and only
                # narrow them afterwards — a window a crash can stop inside.
                os.fchmod(handle.fileno(), 0o600)
                handle.write(value + '\n')
        except OSError as error:
            raise RemoteDaemonError(f"Could not store the password: {error}")
        return value

    def _password_state(self) -> Tuple[bool, Optional[str]]:
        """
        Whether a password is stored, and what is wrong if something is.

        Returns (stored, problem). "Not generated yet" and "generated but this
        process cannot read it" are different situations needing different
        actions, and collapsing both to False said "no password" about a file
        sitting right there — while the security check beside it, which only
        stats the file, went on reporting it as fine.
        """
        path = self._secret_file()
        if not os.path.exists(path):
            return False, None
        try:
            self.password(create=False)
            return True, None
        except RemoteDaemonError as error:
            return True, str(error)

    def password_file_ok(self) -> bool:
        """rsync refuses a password file others can read, and so should we."""
        path = self._secret_file()
        try:
            mode = os.stat(path).st_mode
        except OSError:
            return False
        return not (mode & (stat.S_IRWXG | stat.S_IRWXO))

    # ---- the SSH control channel ------------------------------------------

    @contextmanager
    def _ssh(self):
        """
        A connection for one operation.

        Deliberately not the browse session. That one only exists while an
        operator has connected in the UI, and the checks and restarts here run
        from background threads with nobody watching.
        """
        manager = SSHManager(
            self.host,
            self.config.get('REMOTE_USER'),
            self.config.get('REMOTE_PASSWORD', ''),
            self.config.get('SSH_KEY_PATH', ''),
            host_key_policy=self.config.get('SSH_HOST_KEY_CHECKING', 'accept-new'),
            known_hosts_file=self.config.get('SSH_KNOWN_HOSTS_FILE', ''),
        )
        if not manager.connect():
            raise RemoteDaemonError(
                'Could not reach the remote host over SSH. Check the host, user and key.'
            )
        try:
            yield manager
        finally:
            manager.disconnect()

    @staticmethod
    def _run(ssh, command: str) -> Tuple[int, str, str]:
        return ssh.execute_command(_USER_ENV + command)

    @staticmethod
    def _home(ssh) -> str:
        code, out, _ = ssh.execute_command('printf %s "$HOME"')
        home = (out or '').strip()
        if code != 0 or not home:
            raise RemoteDaemonError('Could not determine the remote home directory')
        return home

    @staticmethod
    def _rsync_binary(ssh) -> str:
        code, out, _ = ssh.execute_command('command -v rsync')
        binary = (out or '').strip().splitlines()[0] if out else ''
        if code != 0 or not binary:
            raise RemoteDaemonError('rsync is not installed on the remote host')
        return binary

    # ---- what address does the remote see us as ---------------------------

    def detect_address(self) -> str:
        """
        Ask the remote host which address our connection arrives from.

        This is why the address never has to be typed or looked up anywhere: the
        far end already knows it, and asking it is both exact and private — the
        value is never sent to a third party to be told what it is.
        """
        with self._ssh() as ssh:
            code, out, _ = ssh.execute_command(
                'printf %s "${SSH_CONNECTION%% *}"'
            )
            address = (out or '').strip()
            if code != 0 or not address:
                raise RemoteDaemonError(
                    'The remote host did not report the address this connection came from'
                )
            return address

    # ---- install and remove ------------------------------------------------

    def install(self) -> Tuple[bool, str]:
        """
        Generate everything, push it, register the service and start it.

        Safe to run repeatedly — it is how a configuration change is applied, so
        it overwrites rather than refusing when something is already there.
        """
        ok, why = self.configured()
        if not ok:
            return False, why

        roots = self.module_roots()
        password = self.password()

        with self._ssh() as ssh:
            home = self._home(ssh)
            binary = self._rsync_binary(ssh)

            missing = self._missing_roots(ssh, roots)
            if missing:
                return False, (
                    'These media directories do not exist on the remote host: '
                    + ', '.join(missing)
                )

            # SECURITY: shell-quoted like every other remote path in this
            # application. The home directory is not attacker-controlled today,
            # but the rule exists so that no path reaches a remote shell
            # unquoted — and an exception is how the rule stops being one.
            directory = ssh._quote_remote_path(layout.remote_dir(home))
            units = ssh._quote_remote_path(layout.unit_dir(home))
            code, _, err = self._run(
                ssh, f'mkdir -p {directory} {units} && chmod 700 {directory}'
            )
            if code != 0:
                return False, f"Could not create the remote directory: {err or code}"

            files = [
                (layout.conf_path(home),
                 render.render_conf(home, self.port, self.access_mode,
                                    self.allowed_address, roots), 0o600),
                (layout.secrets_path(home), render.render_secrets(password), 0o600),
                (layout.unit_path(home),
                 render.render_unit(home, binary, self.port), 0o644),
            ]
            for path, content, mode in files:
                written, error = ssh.write_file(path, content, mode)
                if not written:
                    return False, f"Could not write {path}: {error}"

            code, _, err = self._run(ssh, 'systemctl --user daemon-reload')
            if code != 0:
                return False, f"Could not register the service: {err or code}"

            # Registering it to start on its own is a separate decision from
            # installing it, so that "only while transfers run" is a real
            # setting rather than something an operator has to remember to undo.
            action = 'enable' if self.start_at_boot else 'disable'
            code, _, err = self._run(ssh, f'systemctl --user {action} {layout.UNIT_NAME}')
            if code != 0:
                return False, (
                    f"Installed, but could not set it to {action} at boot: {err or code}. "
                    'Its start-up behaviour is not what the settings say.'
                )

            code, _, err = self._run(ssh, f'systemctl --user restart {layout.UNIT_NAME}')
            if code != 0:
                return False, f"Installed, but the transfer server would not start: {err or code}"

        self._forget_probe()
        result = self._probe_now(retries=3)

        # Installing starts it so the result can be verified, but on demand
        # means on demand: an install with nothing to transfer must not leave a
        # port listening. Released after the check, not before it.
        released = False
        if not self.start_at_boot:
            # Whether it actually stopped, not merely whether we asked. `release`
            # swallows a failed stop on purpose — it is housekeeping that runs
            # after a transfer and must not raise — so taking the attempt as the
            # answer told operators the port was closed when it was still open.
            released = self.release(lambda: False)

        # The tense matters. After the release above it is no longer answering,
        # and saying that it is sends an operator to look for a listening port
        # that this method just closed on purpose.
        if result.ok:
            return True, (
                'The transfer server is installed and working. It is stopped again '
                'until a transfer needs it.'
                if released else 'The transfer server is installed and answering'
            )
        if result.state == probe.BLOCKED:
            return True, (
                'Installed, but it refused this address. '
                'Check the allowed address, or switch to password-only access.'
            )
        return True, f"Installed, but it did not answer: {result.detail}"

    def _missing_roots(self, ssh, roots: List[Tuple[str, str]]) -> List[str]:
        """
        Which libraries point at something that is not there.

        Publishing a path that does not exist produces a transfer server that
        starts cleanly and then fails every transfer, which is a much worse thing
        to debug than a refusal at install time.
        """
        missing = []
        for name, root in roots:
            quoted = ssh._quote_remote_path(root)
            code, _, _ = ssh.execute_command(f'test -d {quoted}')
            if code != 0:
                missing.append(name)
        return missing

    def uninstall(self) -> Tuple[bool, str]:
        """
        Stop it, unregister it, and remove everything this application put there.

        Removes exactly the paths `layout.installed_paths` lists. Written at the
        same time as the installer, because an installer that can leave things
        behind on a machine we have no root on is the thing worth being careful
        about.
        """
        with self._ssh() as ssh:
            home = self._home(ssh)

            # Refuse to remove the configuration while the service is still up.
            # Deleting the files under a running daemon leaves a listener with
            # no configuration to inspect and no unit to stop it by — the worst
            # of both, and it used to be reported as a successful removal.
            code, _, err = self._run(ssh, f'systemctl --user stop {layout.UNIT_NAME}')
            if code != 0:
                return False, (
                    f"Could not stop the transfer server, so nothing was removed: "
                    f"{err or code}"
                )
            if self._probe_now().running:
                return False, (
                    'The transfer server is still answering after being asked to '
                    'stop, so nothing was removed.'
                )

            code, _, err = self._run(ssh, f'systemctl --user disable {layout.UNIT_NAME}')
            # Not fatal — the service is already stopped and the files are about
            # to go — but not silent either. A failed disable leaves the boot
            # link behind pointing at a unit that will not exist, which the
            # service manager complains about on every start until somebody
            # removes it by hand. Reported in the result rather than swallowed.
            disable_problem = '' if code == 0 else (err or f'exit {code}')

            for path in layout.installed_paths(home):
                quoted = ssh._quote_remote_path(path)
                code, _, err = ssh.execute_command(f'rm -rf {quoted}')
                if code != 0:
                    return False, f"Could not remove {path}: {err or code}"
            self._run(ssh, 'systemctl --user daemon-reload')

            leftovers = []
            for path in layout.installed_paths(home):
                quoted = ssh._quote_remote_path(path)
                code, _, _ = ssh.execute_command(f'test -e {quoted}')
                if code == 0:
                    leftovers.append(path)

        self._forget_probe()
        if leftovers:
            return False, 'Some files could not be removed: ' + ', '.join(leftovers)
        if disable_problem:
            # Reported as NOT successful, even though the files did go. Something
            # this application installed is still registered with the service
            # manager and needs a person, and a green toast plus a successful
            # activity entry is how that gets forgotten. The message carries the
            # nuance the flag cannot.
            return False, (
                'The transfer server\'s files were removed, but its start-at-boot '
                f'registration could not be cancelled ({disable_problem}). The service '
                'manager will report a missing unit until it is removed by hand.'
            )
        return True, 'The transfer server was removed from the remote host'

    # ---- run control -------------------------------------------------------

    def start(self) -> Tuple[bool, str]:
        return self._service_action('start', 'started')

    def stop(self) -> Tuple[bool, str]:
        return self._service_action('stop', 'stopped')

    def restart(self) -> Tuple[bool, str]:
        return self._service_action('restart', 'restarted')

    def _service_action(self, action: str, past: str) -> Tuple[bool, str]:
        with self._ssh() as ssh:
            code, _, err = self._run(ssh, f'systemctl --user {action} {layout.UNIT_NAME}')
            if code != 0:
                return False, f"Could not {action} the transfer server: {err or code}"
        self._forget_probe()
        if action == 'stop':
            return True, f"The transfer server was {past}"
        result = self._probe_now(retries=3)
        if result.ok:
            return True, f"The transfer server was {past} and is answering"
        return True, f"The transfer server was {past}, but it is not answering: {result.detail}"

    def ensure_running(self) -> Tuple[bool, str]:
        """
        Make it answer if it can, with one bounded attempt.

        Used before a transfer. One attempt, not a retry loop: a transfer
        waiting on a server that is never coming back should fall through to the
        route that works, not sit there.

        Holds the use lock, so a transfer starting can never interleave with the
        idle shutdown in `release`.
        """
        with self._use_lock:
            result = self.health()
            if result.ok:
                return True, 'Ready'
            if result.state in (probe.BLOCKED, probe.AUTH_FAILED):
                # It is up and it is refusing us. Restarting a service that is
                # running perfectly well cannot change its mind, and doing it
                # anyway would throw away what the check established.
                return False, result.detail
            started, message = self.start()
            if not started:
                return False, message
            return self.health(refresh=True).ok, message

    @contextmanager
    def borrowed(self, still_needed: Optional[Callable[[], bool]] = None):
        """
        Use the transfer server for one short job, then let it go.

        For work that starts the server but owns no completion watcher to stop
        it — a standalone safety dry run, an Explore rehearsal. Those move
        metadata, take seconds, and used to leave an on-demand server listening
        until some unrelated transfer happened to finish. That is the opposite
        of what "only while transfers run" promises.

        `still_needed` defaults to "nothing else is using it", and a caller with
        a better answer (the coordinator knows about queued transfers) passes
        its own.
        """
        try:
            yield
        finally:
            self.release(still_needed or (lambda: False))

    def release(self, still_needed: Callable[[], bool]) -> bool:
        """
        Switch it off once nothing needs it, if it is meant to run on demand.

        Returns True only when the server is actually stopped now — so a caller
        that wants to TELL somebody the port is closed has something truthful to
        read. False covers every other outcome: told to stay up, still needed,
        or the stop failed.

        `still_needed` is asked INSIDE the lock, and starting a transfer takes
        the same lock, so the answer cannot go stale between the question and
        the shutdown. Worst case a transfer whose row does not exist yet finds
        the server stopped and starts it again — a second of SSH, not a failure.

        Never raises. This is housekeeping that runs after a transfer has
        already finished; a server that stays up costs a listening port, and
        that is not worth turning a completed transfer into an error. The return
        value is how a caller learns that anyway.
        """
        if self.start_at_boot:
            # Told to stay up. Nothing to do.
            return False
        try:
            with self._use_lock:
                if still_needed():
                    return False
                # Deliberately NOT conditioned on the health check. `running` is
                # only true for the three answers that prove the daemon spoke to
                # us; an unclassified rsync error reads as not-running while the
                # daemon is listening perfectly well, and an install that had
                # just started it would then skip the shutdown entirely. Asking
                # the service manager to stop something already stopped costs
                # one round trip and always succeeds.
                stopped, message = self.stop()
                if stopped:
                    print('🛑 Transfer server stopped — nothing left to transfer')
                else:
                    print(f"⚠️  Could not stop the transfer server: {message}")
                return stopped
        except Exception as error:  # noqa: BLE001 - housekeeping must not raise
            print(f"⚠️  Could not stop the transfer server: {error}")
            return False

    # ---- choosing a route for one transfer --------------------------------

    def route_for(self, source_path: str, trailing_slash: bool = True
                  ) -> Optional[Tuple[str, List[str]]]:
        """
        The address and extra arguments for pulling `source_path` over this
        server, or None to say "use SSH".

        Returns None — meaning fall back — for every reason a transfer might not
        be able to take this route:

          * the operator has not switched it on
          * it is not configured, or no password has been generated
          * the path is not inside a published library, so there is no library
            to ask for. Failing closed here matters: a path we cannot place is
            one we should not be inventing an address for.
          * it is not running, will not accept us, or could not be started

        The caller does not need to know which of those happened; the panel
        already explains it, and a transfer's job is to run, not to diagnose.
        """
        if not self.settings.get_bool('FAST_TRANSPORT_ENABLED'):
            return None
        configured, _ = self.configured()
        if not configured:
            return None
        if not self.password(create=False):
            return None

        placed = layout.source_for(self.settings, source_path)
        if placed is None:
            return None
        module, relative = placed

        ready, _ = self.ensure_running()
        if not ready:
            return None

        source = layout.daemon_source(self.host, module, relative, trailing_slash)
        return source, [
            f'--port={self.port}',
            '--password-file', self._secret_file(),
        ]

    # ---- health ------------------------------------------------------------

    def health(self, refresh: bool = False) -> probe.ProbeResult:
        """The cached answer to "will it talk to us right now?"."""
        with self._lock:
            cached = self._probe_cache
            if not refresh and cached and (time.monotonic() - cached[0]) < PROBE_CACHE_SECONDS:
                return cached[1]
        result = self._probe_now()
        with self._lock:
            self._probe_cache = (time.monotonic(), result)
        return result

    def _probe_now(self, retries: int = 1) -> probe.ProbeResult:
        roots = self.module_roots()
        if not roots:
            return probe.ProbeResult(
                probe.UNREACHABLE, 'No media directories are configured')
        module = roots[0][0]
        result = probe.ProbeResult(probe.UNREACHABLE, 'Not checked')
        for attempt in range(max(1, retries)):
            result = probe.probe(self.host, self.port, module, self._secret_file())
            if result.running:
                break
            if attempt + 1 < retries:
                # A service that has just been asked to start needs a moment to
                # bind before a refusal means anything.
                time.sleep(1.0)
        return result

    def _forget_probe(self) -> None:
        with self._lock:
            self._probe_cache = None

    # ---- what the panel shows ---------------------------------------------

    def status(self, refresh: bool = True) -> Dict:
        """
        Everything the remote panel needs, in one answer.

        Reports four separate facts that are easy to conflate and need different
        responses: is it configured, is it installed, is it running, and will it
        talk to us. A server that is running and refusing us is not a server that
        is down, and telling an operator to restart it would waste the finding.
        """
        configured, why = self.configured()
        roots = self.module_roots()
        password_stored, password_problem = self._password_state()

        state: Dict = {
            'configured': configured,
            'configuration_problem': why,
            'host_set': bool(self.host),
            'port': self.port,
            'access_mode': self.access_mode,
            'has_allowed_address': bool(self.allowed_address),
            'start_at_boot': self.start_at_boot,
            'enabled_for_transfers': self.settings.get_bool('FAST_TRANSPORT_ENABLED'),
            'libraries': [name for name, _ in roots],
            # Never allowed to raise. An unreadable password file is something
            # status exists to REPORT, and reading it here used to happen before
            # the guarded section below — so the one situation the panel most
            # needs to describe was the one that made it return a 500 instead.
            'password_stored': password_stored,
            'password_problem': password_problem,
            # Only meaningful when the file can actually be read; an unreadable
            # one is reported by password_problem instead of being called secure.
            'password_file_secure': self.password_file_ok() and not password_problem,
            'installed': None,
            'service_state': None,
            'service_enabled': None,
            'lifecycle_matches': None,
            'up_to_date': None,
            'address_matches': None,
            'detected_address_differs': None,
            'health': self.health(refresh=refresh).to_dict(),
            'reachable_over_ssh': None,
            'problem': None,
        }

        try:
            with self._ssh() as ssh:
                state['reachable_over_ssh'] = True
                home = self._home(ssh)
                conf = ssh.read_file(layout.conf_path(home))
                unit_present, _, _ = ssh.execute_command(
                    f'test -f {ssh._quote_remote_path(layout.unit_path(home))}')
                state['installed'] = bool(conf) and unit_present == 0

                _, active, _ = self._run(ssh, f'systemctl --user is-active {layout.UNIT_NAME}')
                _, enabled, _ = self._run(ssh, f'systemctl --user is-enabled {layout.UNIT_NAME}')
                state['service_state'] = (active or '').strip() or 'unknown'
                state['service_enabled'] = (enabled or '').strip() or 'unknown'

                # Whether it will come back on its own matches the setting that
                # says it should. This is NOT part of the configuration
                # fingerprint, because it is not in the configuration file — it
                # is a fact about the service manager, so it has to be asked of
                # the service manager. Without this, a server set to "always"
                # but actually disabled reported itself fully up to date and
                # then failed to return after a reboot.
                if state['installed'] and state['service_enabled'] != 'unknown':
                    actually_enabled = state['service_enabled'].startswith('enabled')
                    state['lifecycle_matches'] = actually_enabled == self.start_at_boot

                if conf:
                    expected = render.fingerprint(
                        self.port, self.access_mode, self.allowed_address, roots)
                    matches = render.installed_fingerprint(conf) == expected
                    # A settings change that has not been applied is a settings
                    # change that has not been applied, whichever half of it
                    # drifted.
                    state['up_to_date'] = matches and state['lifecycle_matches'] is not False

                # Ask the far end what address we arrive from and compare it with
                # what the transfer server is told to allow. This is what turns
                # "the fast route stopped working" into "your address changed".
                if self.access_mode == render.ACCESS_RESTRICTED and self.allowed_address:
                    _, seen, _ = ssh.execute_command('printf %s "${SSH_CONNECTION%% *}"')
                    seen = (seen or '').strip()
                    if seen:
                        state['address_matches'] = seen == self.allowed_address
                        state['detected_address_differs'] = seen != self.allowed_address
        except RemoteDaemonError as error:
            state['reachable_over_ssh'] = False
            state['problem'] = str(error)
        except Exception as error:  # noqa: BLE001 - a status call must always answer
            state['reachable_over_ssh'] = False
            state['problem'] = f"Could not inspect the remote host: {error}"

        state['summary'] = self._summarise(state)
        return state

    @staticmethod
    def _summarise(state: Dict) -> str:
        """One sentence an operator can act on, in the order that matters."""
        if not state['configured']:
            return state['configuration_problem']
        if state['reachable_over_ssh'] is False:
            return state['problem'] or 'The remote host cannot be reached'
        if not state['installed']:
            return 'Not installed on the remote host yet'
        health = state['health']
        if health['state'] == probe.AUTH_FAILED:
            return ('Running, but it is not accepting our password — reinstall '
                    'to push the current one')
        if health['state'] == probe.BLOCKED:
            # rsync will not distinguish "you may not see this" from "it is not
            # there", so the answer is assembled from what is known here. The
            # address is checked first because it is by far the likelier of the
            # two on an installation that was working yesterday.
            if state.get('detected_address_differs'):
                return ('Running, but this connection now comes from a different '
                        'address than the one it allows — update the allowed '
                        'address or switch to password-only access')
            if state['up_to_date'] is False:
                return ('Running, but with older settings than the ones here — '
                        'reinstall to apply them')
            return ('Running, but it will not serve this library. Check the '
                    'allowed address and the configured media directories.')
        if health['ok'] and state.get('lifecycle_matches') is False:
            return (
                'Answering, but it is set to '
                + ('stay off at boot when it should stay on'
                   if state['start_at_boot'] else 'start at boot when it should not')
                + ' — reinstall to apply'
            )
        if health['ok'] and state['up_to_date'] is False:
            return 'Answering, but its settings are older than the ones here — reinstall to apply them'
        if health['ok']:
            return 'Installed and answering'
        if state['service_state'] == 'active':
            return f"The service is running but not answering: {health['detail']}"
        return 'Installed but not running'
