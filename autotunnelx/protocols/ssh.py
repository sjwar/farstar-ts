from __future__ import annotations

from .base import ProtocolAdapter


class AutosshAdapter(ProtocolAdapter):
    def render(self) -> None:
        creds = self.config.get("credentials", {})
        user = creds.get("ssh_user", "root")
        key = creds.get("ssh_key_path", "/root/.ssh/id_ed25519")
        local_port = self.local_port()
        monitor = int(self.spec.get("monitor_port", local_port + 1000))
        if self.role == "inbound":
            tunnel = f"-D 127.0.0.1:{local_port}"
        else:
            tunnel = f"-R 127.0.0.1:{local_port}:127.0.0.1:{local_port}"
        command = (
            f"/usr/bin/autossh -M {monitor} -N -o ServerAliveInterval=15 -o ServerAliveCountMax=3 "
            f"-o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new -i {self.q(key)} "
            f"{tunnel} {self.q(user + '@' + self.peer_host)}"
        )
        self.write_unit(self.systemd_unit(description=f"AutoTunnel-X autossh {self.name}", exec_start=command))
