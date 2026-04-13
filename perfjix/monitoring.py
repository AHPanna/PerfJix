"""
Server-side resource monitors (local Docker or remote SSH).

Copyright (c) 2026 PNAX.io Lab
Author: Panna <panna@pnax.io>
License: MIT
"""
import logging
import socket
import subprocess
import threading
import time


class LocalMonitor:
    """Polls `docker stats` on the local machine in a background thread."""

    def __init__(self, stats):
        self._stats = stats
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                output = subprocess.check_output(
                    [
                        "docker", "stats", "--no-stream",
                        "--format", "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.NetIO}}",
                    ],
                    stderr=subprocess.DEVNULL,
                ).decode("utf-8")
                for line in output.strip().split("\n"):
                    self._stats.update_from_docker_line(line)
            except Exception:
                pass
            time.sleep(3)


class SSHMonitor:
    """
    Polls `docker stats` on a *remote* machine over SSH using paramiko.

    Supports optional jump / bastion hosts for reaching VMs behind a gateway.

    Parameters
    ----------
    stats     : TestStats
    ssh_host  : str  – target host IP or hostname
    ssh_user  : str  – SSH login user (default: 'root')
    ssh_key   : str  – path to private key (default: '~/.ssh/id_ed25519')
    ssh_jump  : str  – optional bastion, e.g. 'user@bastion.host' or 'host:port'
    """

    _DOCKER_CMD = (
        "docker stats --no-stream "
        "--format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.NetIO}}'"
    )

    def __init__(
        self,
        stats,
        ssh_host: str,
        ssh_user: str = "root",
        ssh_key: str = "~/.ssh/id_ed25519",
        ssh_jump: str | None = None,
        ssh_jump_user: str | None = None,
        ssh_jump_key: str | None = None,
    ):
        """
        Parameters
        ----------
        ssh_jump_user : str, optional
            Login user for the bastion host. Falls back to *ssh_user* if not set.
        ssh_jump_key  : str, optional
            Private key path for the bastion host. Falls back to *ssh_key* if not set.
        """
        self._stats = stats
        self._host = ssh_host
        self._user = ssh_user
        self._jump = ssh_jump
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

        import os
        self._key_path = os.path.expanduser(ssh_key) if ssh_key else None
        # Jump-host credentials (fall back to target credentials if not supplied)
        self._jump_user = ssh_jump_user or ssh_user
        self._jump_key_path = os.path.expanduser(ssh_jump_key) if ssh_jump_key else self._key_path

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    def _make_direct_client(self, paramiko):
        """Connect directly to the target host."""
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(hostname=self._host, port=22, username=self._user, timeout=10)
        if self._key_path:
            kwargs["key_filename"] = self._key_path
        c.connect(**kwargs)
        return None, c  # (bastion, target)

    def _make_jump_client(self, paramiko):
        """Connect to target through a jump/bastion host."""
        # Parse  [user@]host[:port]  — user@ in the string takes lowest priority
        jump_user = self._jump_user
        jump_str = self._jump
        if "@" in jump_str:
            _, jump_str = jump_str.split("@", 1)  # user already resolved via _jump_user
        jump_host, jump_port = jump_str, 22
        if ":" in jump_host:
            jump_host, p = jump_host.rsplit(":", 1)
            jump_port = int(p)

        # 1 – Connect to bastion with its own credentials
        bastion = paramiko.SSHClient()
        bastion.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        bkw = dict(hostname=jump_host, port=jump_port, username=jump_user, timeout=10)
        if self._jump_key_path:
            bkw["key_filename"] = self._jump_key_path
        bastion.connect(**bkw)

        # 2 – Tunnel to target via bastion transport
        chan = bastion.get_transport().open_channel(
            "direct-tcpip", (self._host, 22), ("127.0.0.1", 0)
        )

        # 3 – Connect target through the tunnel
        target = paramiko.SSHClient()
        target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        tkw = dict(hostname=self._host, port=22, username=self._user, timeout=10, sock=chan)
        if self._key_path:
            tkw["key_filename"] = self._key_path
        target.connect(**tkw)
        return bastion, target

    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            import paramiko
        except ImportError:
            logging.error("[SSHMonitor] paramiko not installed. Run: pip install paramiko")
            return

        bastion, client = None, None
        _first_connect = True

        while not self._stop.is_set():
            try:
                if client is None:
                    if _first_connect:
                        logging.info("[SSHMonitor] Polling remote docker stats …")
                        _first_connect = False
                    else:
                        logging.debug("[SSHMonitor] Reconnecting …")
                    if self._jump:
                        bastion, client = self._make_jump_client(paramiko)
                    else:
                        bastion, client = self._make_direct_client(paramiko)
                    logging.debug("[SSHMonitor] SSH session established.")

                _, stdout, stderr = client.exec_command(self._DOCKER_CMD, timeout=15)
                output = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace").strip()
                if err:
                    logging.debug(f"[SSHMonitor] stderr: {err}")

                for line in output.strip().split("\n"):
                    self._stats.update_from_docker_line(line)

            except (paramiko.SSHException, socket.error, EOFError) as e:
                logging.warning(f"[SSHMonitor] Connection lost ({e}), reconnecting …")
                self._close(client, bastion)
                client, bastion = None, None
                time.sleep(5)
                continue
            except Exception as e:
                logging.warning(f"[SSHMonitor] Unexpected error: {e}")

            time.sleep(3)

        self._close(client, bastion)
        logging.info("[SSHMonitor] Stopped.")

    @staticmethod
    def _close(*clients) -> None:
        for c in clients:
            try:
                if c:
                    c.close()
            except Exception:
                pass
