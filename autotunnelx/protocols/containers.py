from __future__ import annotations

import json
from typing import Any

import yaml

from .. import shell
from .base import ProtocolAdapter


class ContainerConfigAdapter(ProtocolAdapter):
    image = "alpine:3.20"

    def render(self) -> None:
        config_files, command = self.build()
        volumes = ["/etc/ssl:/etc/ssl:ro"]
        for name, content in config_files.items():
            path = self.state_dir / name
            shell.atomic_write(path, content, mode=0o640)
        if config_files:
            volumes.append(f"{self.state_dir}:{self.state_dir}:ro")
        self.write_unit(self.docker_unit(image=self.image, command=command, volumes=volumes))

    def build(self) -> tuple[dict[str, str], str]:
        raise NotImplementedError


class FrpAdapter(ContainerConfigAdapter):
    image = "fatedier/frps:v0.59.0"

    def build(self) -> tuple[dict[str, str], str]:
        token = self.shared_secret()
        port = self.listen_port()
        local = self.local_port()
        if self.role == "outbound":
            self.image = "fatedier/frps:v0.59.0"
            cfg = f"""bindPort = {port}
auth.method = "token"
auth.token = "{token}"
transport.tcpMux = true
log.to = "console"
"""
            return {"frps.toml": cfg}, f"-c {self.state_dir}/frps.toml"
        self.image = "fatedier/frpc:v0.59.0"
        cfg = f"""serverAddr = "{self.peer_host}"
serverPort = {port}
auth.method = "token"
auth.token = "{token}"
transport.tcpMux = true
log.to = "console"

[[proxies]]
name = "{self.name}-socks"
type = "tcp"
localIP = "127.0.0.1"
localPort = {local}
remotePort = {local}
"""
        return {"frpc.toml": cfg}, f"-c {self.state_dir}/frpc.toml"


class RatholeAdapter(ContainerConfigAdapter):
    image = "rapiz1/rathole:v0.5.0"

    def build(self) -> tuple[dict[str, str], str]:
        token = self.shared_secret()
        port = self.listen_port()
        local = self.local_port()
        if self.role == "outbound":
            cfg = f"""[server]
bind_addr = "0.0.0.0:{port}"
default_token = "{token}"

[server.services.socks]
bind_addr = "127.0.0.1:{local}"
"""
        else:
            cfg = f"""[client]
remote_addr = "{self.peer_host}:{port}"
default_token = "{token}"

[client.services.socks]
local_addr = "127.0.0.1:{local}"
"""
        return {"rathole.toml": cfg}, f"{self.state_dir}/rathole.toml"


class ChiselAdapter(ContainerConfigAdapter):
    image = "jpillora/chisel:1.10.1"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        if self.role == "outbound":
            return {}, f"server --host 0.0.0.0 --port {port} --reverse --auth atx:{self.shared_secret()}"
        return {}, f"client --auth atx:{self.shared_secret()} {self.peer_host}:{port} R:socks:{local}"


class GostAdapter(ContainerConfigAdapter):
    image = "gostorg/gost:3.0.0"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        secret = self.shared_secret()
        tunnel_type = self.type
        if tunnel_type == "gost_udp":
            proto = "udp"
        elif tunnel_type == "gost_ws_tls":
            proto = "wss"
        else:
            proto = "tcp"

        if self.role == "outbound":
            cfg = {
                "services": [
                    {
                        "name": self.name,
                        "addr": f":{port}",
                        "handler": {"type": "socks5", "auth": {"username": "atx", "password": secret}},
                        "listener": {"type": proto},
                    }
                ]
            }
        else:
            cfg = {
                "services": [
                    {
                        "name": self.name,
                        "addr": f"127.0.0.1:{local}",
                        "handler": {"type": "socks5"},
                        "listener": {"type": "tcp"},
                        "forwarder": {
                            "nodes": [
                                {
                                    "name": "peer",
                                    "addr": f"{self.peer_host}:{port}",
                                    "connector": {"type": "socks5", "auth": {"username": "atx", "password": secret}},
                                    "dialer": {"type": proto},
                                }
                            ]
                        },
                    }
                ]
            }
        return {"gost.yaml": yaml.safe_dump(cfg, sort_keys=False)}, f"-C {self.state_dir}/gost.yaml"


class WSTunnelAdapter(ContainerConfigAdapter):
    image = "ghcr.io/erebe/wstunnel:latest"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        if self.role == "outbound":
            return {}, f"server ws://0.0.0.0:{port}"
        return {}, f"client -L socks5://127.0.0.1:{local} ws://{self.peer_host}:{port}"


class ShadowTLSAdapter(ContainerConfigAdapter):
    image = "ghcr.io/ihciah/shadow-tls:latest"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        password = self.config.get("credentials", {}).get("shadowtls_password", self.shared_secret())
        sni = self.spec.get("sni", "www.microsoft.com")
        if self.role == "outbound":
            return {}, f"--v3 server --listen 0.0.0.0:{port} --server 127.0.0.1:{local} --password {password} --wildcard-sni {sni}"
        return {}, f"--v3 client --listen 127.0.0.1:{local} --server {self.peer_host}:{port} --password {password} --sni {sni}"


class Hysteria2Adapter(ContainerConfigAdapter):
    image = "tobyxdd/hysteria:v2.6.1"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        password = self.config.get("credentials", {}).get("hysteria_password", self.shared_secret())
        if self.role == "outbound":
            cfg = {
                "listen": f":{port}",
                "auth": {"type": "password", "password": password},
                "tls": {"cert": "/etc/ssl/certs/ssl-cert-snakeoil.pem", "key": "/etc/ssl/private/ssl-cert-snakeoil.key"},
                "masquerade": {"type": "proxy", "proxy": {"url": "https://www.apple.com/", "rewriteHost": True}},
            }
            return {"hysteria.yaml": yaml.safe_dump(cfg, sort_keys=False)}, f"server -c {self.state_dir}/hysteria.yaml"
        cfg = {
            "server": f"{self.peer_host}:{port}",
            "auth": password,
            "tls": {"sni": self.spec.get("sni", "www.apple.com"), "insecure": True},
            "socks5": {"listen": f"127.0.0.1:{local}"},
        }
        return {"hysteria.yaml": yaml.safe_dump(cfg, sort_keys=False)}, f"client -c {self.state_dir}/hysteria.yaml"


class TuicAdapter(ContainerConfigAdapter):
    image = "ghcr.io/tuic-protocol/tuic:latest"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        creds = self.config.get("credentials", {})
        uuid = creds.get("tuic_uuid")
        password = creds.get("tuic_password")
        if self.role == "outbound":
            cfg = {
                "server": f"0.0.0.0:{port}",
                "users": {uuid: password},
                "certificate": "/etc/ssl/certs/ssl-cert-snakeoil.pem",
                "private_key": "/etc/ssl/private/ssl-cert-snakeoil.key",
                "congestion_control": "bbr",
                "alpn": ["h3"],
            }
        else:
            cfg = {
                "relay": {"server": f"{self.peer_host}:{port}", "uuid": uuid, "password": password},
                "local": {"server": f"127.0.0.1:{local}"},
                "tls": {"sni": self.spec.get("sni", "www.mozilla.org"), "disable_sni": False, "insecure": True},
                "congestion_control": "bbr",
            }
        return {"tuic.json": json.dumps(cfg, indent=2)}, f"-c {self.state_dir}/tuic.json"


class JuicityAdapter(ContainerConfigAdapter):
    image = "ghcr.io/juicity/juicity:latest"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        creds = self.config.get("credentials", {})
        uuid = creds.get("juicity_uuid")
        password = creds.get("juicity_password")
        if self.role == "outbound":
            cfg = {
                "listen": f":{port}",
                "users": {uuid: password},
                "certificate": "/etc/ssl/certs/ssl-cert-snakeoil.pem",
                "private_key": "/etc/ssl/private/ssl-cert-snakeoil.key",
                "congestion_control": "bbr",
            }
            return {"juicity.json": json.dumps(cfg, indent=2)}, f"server -c {self.state_dir}/juicity.json"
        cfg = {
            "listen": f"127.0.0.1:{local}",
            "server": f"{self.peer_host}:{port}",
            "uuid": uuid,
            "password": password,
            "sni": self.spec.get("sni", "www.google.com"),
            "allow_insecure": True,
            "congestion_control": "bbr",
        }
        return {"juicity.json": json.dumps(cfg, indent=2)}, f"client -c {self.state_dir}/juicity.json"


class CloudflaredAdapter(ContainerConfigAdapter):
    image = "cloudflare/cloudflared:2026.5.0"

    def build(self) -> tuple[dict[str, str], str]:
        creds = self.config.get("credentials", {})
        token = creds.get("cloudflared_token", "")
        hostname = creds.get("cloudflared_hostname", self.peer_host)
        if self.role == "outbound":
            return {}, f"tunnel --no-autoupdate run --token {token}"
        local = self.local_port()
        return {}, f"access tcp --hostname {hostname} --url 127.0.0.1:{local}"


class NaiveProxyAdapter(ContainerConfigAdapter):
    image = "p3terx/naiveproxy:latest"

    def build(self) -> tuple[dict[str, str], str]:
        port = self.listen_port()
        local = self.local_port()
        password = self.shared_secret()
        if self.role == "outbound":
            cfg = {
                "listen": f"http://0.0.0.0:{port}",
                "users": {"atx": password},
                "padding": True,
            }
        else:
            cfg = {
                "listen": f"socks://127.0.0.1:{local}",
                "proxy": f"https://atx:{password}@{self.peer_host}:{port}",
                "host-resolver-rules": "MAP * 1.1.1.1",
            }
        return {"naive.json": json.dumps(cfg, indent=2)}, f"{self.state_dir}/naive.json"


class IodineAdapter(ContainerConfigAdapter):
    image = "networkboot/iodine:latest"

    def build(self) -> tuple[dict[str, str], str]:
        domain = self.config.get("credentials", {}).get("dns_tunnel_domain", "")
        password = self.shared_secret()
        if self.role == "outbound":
            return {}, f"iodined -f -P {password} 10.72.53.1 {domain}"
        return {}, f"iodine -f -P {password} {self.peer_host} {domain}"


class Dnscat3Adapter(ContainerConfigAdapter):
    image = "ruby:3.3-alpine"

    def build(self) -> tuple[dict[str, str], str]:
        domain = self.config.get("credentials", {}).get("dns_tunnel_domain", "")
        secret = self.shared_secret()
        install = "gem install dnscat3 >/dev/null 2>&1 || gem install dnscat2 >/dev/null"
        if self.role == "outbound":
            return {}, f"sh -lc '{install}; dnscat3-server --dns domain={domain} --secret={secret}'"
        local = self.local_port()
        return {}, f"sh -lc '{install}; dnscat3 --dns server={self.peer_host},port=53 --secret={secret} --socks 127.0.0.1:{local}'"


class ArvanCdnAdapter(GostAdapter):
    def build(self) -> tuple[dict[str, str], str]:
        self.spec["type"] = "gost_ws_tls"
        cdn_host = self.config.get("credentials", {}).get("cdn_host") or self.peer_host
        port = self.listen_port()
        local = self.local_port()
        secret = self.shared_secret()
        if self.role == "outbound":
            cfg = {
                "services": [
                    {
                        "name": self.name,
                        "addr": f":{port}",
                        "handler": {"type": "socks5", "auth": {"username": "atx", "password": secret}},
                        "listener": {"type": "wss"},
                    }
                ]
            }
        else:
            cfg = {
                "services": [
                    {
                        "name": self.name,
                        "addr": f"127.0.0.1:{local}",
                        "handler": {"type": "socks5"},
                        "listener": {"type": "tcp"},
                        "forwarder": {
                            "nodes": [
                                {
                                    "name": "cdn-peer",
                                    "addr": f"{cdn_host}:{port}",
                                    "connector": {"type": "socks5", "auth": {"username": "atx", "password": secret}},
                                    "dialer": {"type": "wss", "tls": {"serverName": cdn_host}},
                                }
                            ]
                        },
                    }
                ]
            }
        return {"arvan-gost.yaml": yaml.safe_dump(cfg, sort_keys=False)}, f"-C {self.state_dir}/arvan-gost.yaml"
