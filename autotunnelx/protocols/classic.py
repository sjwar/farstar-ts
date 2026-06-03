from __future__ import annotations

from .base import ProtocolAdapter


class ClassicTunnelAdapter(ProtocolAdapter):
    mode_map = {"gre": "gre", "ipip": "ipip", "sit": "sit"}

    def render(self) -> None:
        iface = self.spec.get("interface", f"atx-{self.type}")
        mode = self.mode_map[self.type]
        local_addr = self.spec.get("local_tunnel_ip")
        peer = self.peer_host
        family = "-6" if ":" in str(local_addr) else ""
        ttl = "255" if mode in {"gre", "sit"} else "64"
        start = (
            "sysctl -w net.ipv4.ip_forward=1 net.ipv6.conf.all.forwarding=1 >/dev/null; "
            f"ip link del {self.q(iface)} 2>/dev/null || true; "
            f"ip tunnel add {self.q(iface)} mode {mode} remote {self.q(peer)} ttl {ttl}; "
            f"ip {family} addr replace {self.q(local_addr)} dev {self.q(iface)}; "
            f"ip link set {self.q(iface)} up mtu 1400"
        )
        stop = f"ip link set {self.q(iface)} down 2>/dev/null || true; ip tunnel del {self.q(iface)} 2>/dev/null || true"
        self.write_unit(
            self.systemd_unit(
                description=f"AutoTunnel-X classic {self.type} tunnel {self.name}",
                exec_start=f"/bin/bash -lc {self.q(start)}",
                exec_stop=f"/bin/bash -lc {self.q(stop)}",
                service_type="oneshot",
                remain=True,
            )
        )
