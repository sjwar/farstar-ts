from __future__ import annotations

import logging
import shlex
from typing import Any

from . import shell


class FirewallManager:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config
        self.log = logger

    def ensure_baseline(self) -> None:
        shell.shell("sysctl -w net.ipv4.ip_forward=1 net.ipv6.conf.all.forwarding=1 >/dev/null", timeout=10)
        shell.shell("iptables -N AUTOTUNNELX 2>/dev/null || true", timeout=10)
        shell.shell("iptables -C INPUT -j AUTOTUNNELX 2>/dev/null || iptables -I INPUT -j AUTOTUNNELX", timeout=10)

    def open_protocol_ports(self) -> None:
        shell.shell("iptables -F AUTOTUNNELX", timeout=10)
        for spec in self.config.get("protocols", []):
            if not spec.get("enabled", True):
                continue
            port = spec.get("listen_port")
            if not port:
                continue
            proto = _port_proto(spec)
            self.open_port(int(port), proto, spec.get("name", "unknown"))

    def open_port(self, port: int, proto: str, label: str) -> None:
        proto = proto.lower()
        if proto not in {"tcp", "udp"}:
            self.open_port(port, "tcp", label)
            self.open_port(port, "udp", label)
            return
        cmd = f"iptables -C AUTOTUNNELX -p {proto} --dport {port} -j ACCEPT 2>/dev/null || iptables -A AUTOTUNNELX -p {proto} --dport {port} -j ACCEPT"
        result = shell.shell(cmd, timeout=10)
        if result.ok:
            self.log.info("firewall_port_opened", extra={"_tunnel": label, "_port": port, "_proto": proto})
        else:
            self.log.warning("firewall_port_failed", extra={"_tunnel": label, "_port": port, "_proto": proto, "_stderr": result.stderr})

        ufw_check = shell.shell("command -v ufw >/dev/null 2>&1 && ufw status | grep -qi 'Status: active'", timeout=5)
        if ufw_check.ok:
            shell.shell(f"ufw allow {shlex.quote(str(port) + '/' + proto)} comment 'AutoTunnel-X {shlex.quote(label)}' >/dev/null || true", timeout=20)


def _port_proto(spec: dict[str, Any]) -> str:
    tunnel_type = str(spec.get("type", ""))
    if tunnel_type in {"wireguard", "openvpn_udp", "hysteria2", "tuic_v5", "juicity", "gost_udp", "iodine_dns"}:
        return "udp"
    if tunnel_type == "openvpn" and str(spec.get("proto", "")).startswith("udp"):
        return "udp"
    if tunnel_type in {"gost_tcp", "gost_ws_tls", "frp", "rathole", "chisel", "wstunnel", "shadowtls", "ssh_autossh"}:
        return "tcp"
    return "tcp"
