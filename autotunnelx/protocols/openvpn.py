from __future__ import annotations

import hashlib
from pathlib import Path

from .. import shell
from .base import ProtocolAdapter


class OpenVPNAdapter(ProtocolAdapter):
    def render(self) -> None:
        key_path = self.state_dir / "static.key"
        shell.atomic_write(key_path, self._static_key(), mode=0o600)
        proto = str(self.spec.get("proto", "udp"))
        client_proto = str(self.spec.get("client_proto", "udp"))
        role_proto = proto if self.role == "outbound" else client_proto
        iface = self.spec.get("interface", f"tun-{self.safe_name}")
        local = str(self.spec.get("local_tunnel_ip"))
        peer = str(self.spec.get("peer_tunnel_ip"))
        port = self.listen_port()
        remote = f"--remote {self.q(self.peer_host)} {port} --nobind" if self.role == "inbound" else f"--local 0.0.0.0 --port {port}"
        command = (
            f"/usr/sbin/openvpn --dev {self.q(iface)} --ifconfig {self.q(local)} {self.q(peer)} "
            f"--proto {self.q(role_proto)} {remote} --secret {self.q(key_path)} "
            "--keepalive 10 30 --persist-key --persist-tun --verb 3"
        )
        self.write_unit(self.systemd_unit(description=f"AutoTunnel-X OpenVPN {self.name}", exec_start=command))

    def _static_key(self) -> str:
        seed = (self.shared_secret() + ":" + self.name).encode("utf-8")
        material = ""
        counter = 0
        while len(material) < 2048:
            material += hashlib.sha512(seed + str(counter).encode("ascii")).hexdigest()
            counter += 1
        lines = [material[i : i + 32] for i in range(0, 2048, 32)]
        return "-----BEGIN OpenVPN Static key V1-----\n" + "\n".join(lines) + "\n-----END OpenVPN Static key V1-----\n"
