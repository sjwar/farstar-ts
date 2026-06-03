from __future__ import annotations

import base64
import os
from pathlib import Path

from .. import shell
from .base import ProtocolAdapter


class WireGuardAdapter(ProtocolAdapter):
    def credential_errors(self) -> list[str]:
        errors = super().credential_errors()
        peer_key = self.spec.get("peer_public_key") or self.config.get("peer", {}).get("wireguard_public_key")
        if not peer_key:
            errors.append("peer_public_key")
        return errors

    def deploy(self) -> dict[str, object]:
        self._ensure_keys()
        return super().deploy()

    def render(self) -> None:
        iface = str(self.spec.get("interface", "atxwg0"))
        conf_path = Path("/etc/wireguard") / f"{iface}.conf"
        private_key = (self.state_dir / "privatekey").read_text(encoding="utf-8").strip()
        peer_key = self.spec.get("peer_public_key") or self.config.get("peer", {}).get("wireguard_public_key")
        listen_port = self.listen_port()
        endpoint = ""
        if self.role == "inbound":
            endpoint = f"Endpoint = {self.peer_host}:{listen_port}\nPersistentKeepalive = 20\n"
        content = f"""[Interface]
PrivateKey = {private_key}
Address = {self.spec.get("local_tunnel_ip")}
ListenPort = {listen_port}
MTU = 1420

[Peer]
PublicKey = {peer_key}
AllowedIPs = {self.spec.get("peer_tunnel_ip")}/32
{endpoint}"""
        shell.atomic_write(conf_path, content, mode=0o600)
        self.write_unit(
            self.systemd_unit(
                description=f"AutoTunnel-X WireGuard {iface}",
                exec_start=f"/usr/bin/wg-quick up {self.q(iface)}",
                exec_stop=f"/usr/bin/wg-quick down {self.q(iface)}",
                service_type="oneshot",
                remain=True,
            )
        )

    def _ensure_keys(self) -> None:
        private = self.state_dir / "privatekey"
        public = self.state_dir / "publickey"
        if private.exists() and public.exists():
            return
        result = shell.run(["wg", "genkey"], timeout=10)
        if result.ok and result.stdout:
            key = result.stdout.strip()
        else:
            key = base64.b64encode(os.urandom(32)).decode("ascii")
        shell.atomic_write(private, key + "\n", mode=0o600)
        pub = shell.run(["bash", "-lc", f"cat {self.q(private)} | wg pubkey"], timeout=10)
        if pub.ok and pub.stdout:
            shell.atomic_write(public, pub.stdout.strip() + "\n", mode=0o644)
