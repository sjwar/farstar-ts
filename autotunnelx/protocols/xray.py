from __future__ import annotations

import json
from typing import Any

from .. import shell
from .containers import ContainerConfigAdapter


class XrayAdapter(ContainerConfigAdapter):
    image = "teddysun/xray:25.5.16"

    def credential_errors(self) -> list[str]:
        errors = super().credential_errors()
        if self.type == "xray_vless_reality" and self.role == "inbound" and not self.config.get("peer", {}).get("xray_reality_public_key"):
            errors.append("peer_xray_reality_public_key")
        return errors

    def deploy(self) -> dict[str, object]:
        if self.type == "xray_vless_reality":
            self._ensure_reality_keys()
        return super().deploy()

    def build(self) -> tuple[dict[str, str], str]:
        config = self._server_config() if self.role == "outbound" else self._client_config()
        return {"xray.json": json.dumps(config, indent=2)}, f"-config {self.state_dir}/xray.json"

    def _server_config(self) -> dict[str, Any]:
        port = self.listen_port()
        creds = self.config.get("credentials", {})
        tunnel_type = self.type
        inbound: dict[str, Any]
        if tunnel_type.startswith("xray_trojan"):
            inbound = {
                "port": port,
                "listen": "0.0.0.0",
                "protocol": "trojan",
                "settings": {"clients": [{"password": creds.get("trojan_password")}]},
                "streamSettings": self._stream_settings(server=True),
            }
        else:
            inbound = {
                "port": port,
                "listen": "0.0.0.0",
                "protocol": "vless",
                "settings": {"clients": [{"id": creds.get("xray_uuid"), "flow": ""}], "decryption": "none"},
                "streamSettings": self._stream_settings(server=True),
            }
        return {
            "log": {"loglevel": "warning"},
            "inbounds": [inbound],
            "outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}],
        }

    def _client_config(self) -> dict[str, Any]:
        port = self.listen_port()
        local = self.local_port()
        creds = self.config.get("credentials", {})
        tunnel_type = self.type
        outbound: dict[str, Any]
        if tunnel_type.startswith("xray_trojan"):
            outbound = {
                "protocol": "trojan",
                "settings": {"servers": [{"address": self.peer_host, "port": port, "password": creds.get("trojan_password")}]},
                "streamSettings": self._stream_settings(server=False),
            }
        else:
            outbound = {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": self.peer_host,
                            "port": port,
                            "users": [{"id": creds.get("xray_uuid"), "encryption": "none", "flow": ""}],
                        }
                    ]
                },
                "streamSettings": self._stream_settings(server=False),
            }
        return {
            "log": {"loglevel": "warning"},
            "inbounds": [{"listen": "127.0.0.1", "port": local, "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [outbound],
        }

    def _stream_settings(self, *, server: bool) -> dict[str, Any]:
        tunnel_type = self.type
        if "grpc" in tunnel_type:
            return {
                "network": "grpc",
                "security": "tls",
                "tlsSettings": self._tls_settings(server),
                "grpcSettings": {"serviceName": self.spec.get("service_name", self.name)},
            }
        if "ws" in tunnel_type:
            return {
                "network": "ws",
                "security": "tls",
                "tlsSettings": self._tls_settings(server),
                "wsSettings": {"path": self.spec.get("path", "/atx")},
            }
        if "reality" in tunnel_type:
            if server:
                return {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": f"{self.spec.get('sni', 'www.cloudflare.com')}:443",
                        "serverNames": [self.spec.get("sni", "www.cloudflare.com")],
                        "privateKey": self._read_key("reality_privatekey"),
                        "shortIds": [self.config.get("credentials", {}).get("xray_reality_short_id", "a1b2c3d4e5f6a7b8")],
                    },
                }
            return {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "serverName": self.spec.get("sni", "www.cloudflare.com"),
                    "publicKey": self.config.get("peer", {}).get("xray_reality_public_key", ""),
                    "shortId": self.config.get("credentials", {}).get("xray_reality_short_id", "a1b2c3d4e5f6a7b8"),
                    "fingerprint": "chrome",
                },
            }
        return {"network": "tcp", "security": "tls", "tlsSettings": self._tls_settings(server)}

    def _tls_settings(self, server: bool) -> dict[str, Any]:
        if server:
            return {
                "certificates": [
                    {
                        "certificateFile": "/etc/ssl/certs/ssl-cert-snakeoil.pem",
                        "keyFile": "/etc/ssl/private/ssl-cert-snakeoil.key",
                    }
                ]
            }
        return {"serverName": self.spec.get("sni", "www.cloudflare.com"), "allowInsecure": True}

    def _ensure_reality_keys(self) -> None:
        private = self.state_dir / "reality_privatekey"
        public = self.state_dir / "reality_publickey"
        if private.exists() and public.exists():
            return
        result = shell.shell(f"docker run --rm {self.image} x25519", timeout=60)
        priv = ""
        pub = ""
        for line in result.stdout.splitlines():
            lower = line.lower()
            if "private" in lower and ":" in line:
                priv = line.split(":", 1)[1].strip()
            if "public" in lower and ":" in line:
                pub = line.split(":", 1)[1].strip()
        if not priv or not pub:
            return
        shell.atomic_write(private, priv + "\n", mode=0o600)
        shell.atomic_write(public, pub + "\n", mode=0o644)

    def _read_key(self, filename: str) -> str:
        try:
            return (self.state_dir / filename).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return self.config.get("credentials", {}).get("xray_reality_private_key", "")
