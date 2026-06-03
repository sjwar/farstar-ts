from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import Any

from .. import shell


class ProtocolAdapter:
    """Base class for a managed tunnel transport."""

    def __init__(self, spec: dict[str, Any], config: dict[str, Any], logger: logging.Logger):
        self.spec = spec
        self.config = config
        self.log = logger
        self.name = str(spec["name"])
        self.type = str(spec["type"])
        self.role = str(config.get("role"))
        self.peer_host = str(config.get("peer", {}).get("host", ""))

    @property
    def state_dir(self) -> Path:
        base = Path(self.config.get("paths", {}).get("protocol_state_dir", "/var/lib/autotunnel-x/protocols"))
        path = base / self.safe_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def safe_name(self) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.name)

    @property
    def service_name(self) -> str:
        return f"autotunnel-tunnel-{self.safe_name}.service"

    @property
    def unit_path(self) -> Path:
        return Path("/etc/systemd/system") / self.service_name

    def credential_errors(self) -> list[str]:
        creds = self.config.get("credentials", {})
        return [key for key in self.spec.get("credential_keys", []) if not creds.get(key)]

    def deploy(self) -> dict[str, Any]:
        missing = self.credential_errors()
        if missing:
            return {"status": "waiting_for_credentials", "missing": missing}
        self.render()
        shell.run(["systemctl", "daemon-reload"], timeout=20)
        return {"status": "deployed"}

    def render(self) -> None:
        raise NotImplementedError

    def start(self) -> None:
        if self.credential_errors():
            return
        shell.run(["systemctl", "enable", "--now", self.service_name], timeout=60)

    def stop(self) -> None:
        shell.run(["systemctl", "disable", "--now", self.service_name], timeout=60)

    def status(self) -> str:
        result = shell.run(["systemctl", "is-active", self.service_name], timeout=10)
        return "running" if result.stdout.strip() == "active" else "stopped"

    def write_unit(self, content: str) -> None:
        shell.atomic_write(self.unit_path, content, mode=0o644)

    def systemd_unit(self, *, description: str, exec_start: str, exec_stop: str | None = None, after: str = "network-online.target", service_type: str = "simple", remain: bool = False) -> str:
        stop_line = f"ExecStop={exec_stop}\n" if exec_stop else ""
        remain_line = "RemainAfterExit=yes\n" if remain else ""
        return f"""[Unit]
Description={description}
After={after}
Wants=network-online.target

[Service]
Type={service_type}
{remain_line}ExecStart={exec_start}
{stop_line}Restart=on-failure
RestartSec=5
TimeoutStartSec=90
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""

    def docker_unit(self, *, image: str, command: str, volumes: list[str] | None = None, env: dict[str, str] | None = None) -> str:
        volume_args = " ".join(f"-v {shlex.quote(v)}" for v in (volumes or []))
        env_args = " ".join(f"-e {shlex.quote(k)}={shlex.quote(str(v))}" for k, v in (env or {}).items())
        container = f"atx-{self.safe_name}"
        exec_start_pre = f"/usr/bin/docker rm -f {container} >/dev/null 2>&1 || true"
        exec_start = (
            f"/usr/bin/docker run --rm --name {container} --network host --cap-add NET_ADMIN --cap-add NET_RAW "
            f"{env_args} {volume_args} {shlex.quote(image)} {command}"
        )
        return f"""[Unit]
Description=AutoTunnel-X {self.name} container
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
ExecStartPre=/bin/bash -lc '{exec_start_pre}'
ExecStart=/bin/bash -lc {shlex.quote(exec_start)}
ExecStop=/bin/bash -lc '/usr/bin/docker rm -f {container} >/dev/null 2>&1 || true'
Restart=on-failure
RestartSec=5
TimeoutStartSec=120
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""

    def q(self, value: Any) -> str:
        return shlex.quote(str(value))

    def local_port(self) -> int:
        return int(self.spec.get("local_port", self.spec.get("listen_port", 0)))

    def listen_port(self) -> int:
        return int(self.spec.get("listen_port", 0))

    def shared_secret(self) -> str:
        return str(self.config.get("credentials", {}).get("shared_secret", "autotunnel-x"))
