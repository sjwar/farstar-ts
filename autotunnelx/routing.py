from __future__ import annotations

import logging
import shlex
import time
from typing import Any

from . import shell


class RoutingManager:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config
        self.log = logger
        self._last_switch = 0.0

    def apply(self, winners: list[dict[str, Any]], *, forced: str | None = None) -> list[str]:
        routing = self.config.get("routing", {})
        if not routing.get("enabled", True):
            return []
        cooldown = float(routing.get("failover_cooldown_seconds", 45))
        if time.time() - self._last_switch < cooldown and not forced:
            return []

        if forced:
            winners = [w for w in winners if w.get("name") == forced]
        if not winners:
            return []

        mode = routing.get("mode", "failover")
        chosen = winners[: int(routing.get("load_balance_top_n", 3))] if mode == "loadbalance" else winners[:1]
        l3 = [item for item in chosen if item.get("mode") == "l3" and item.get("interface")]
        proxies = [item for item in chosen if item.get("mode") == "proxy" and item.get("local_port")]

        applied: list[str] = []
        if l3:
            if len(l3) == 1:
                self._route_single_l3(l3[0])
                applied.append(l3[0]["name"])
            else:
                self._route_loadbalance_l3(l3)
                applied.extend(item["name"] for item in l3)
        elif proxies:
            if len(proxies) == 1:
                self._proxy_single(proxies[0])
                applied.append(proxies[0]["name"])
            else:
                self._proxy_nth(proxies)
                applied.extend(item["name"] for item in proxies)

        if applied:
            self._last_switch = time.time()
            self.log.info("routing_applied", extra={"_active": applied, "_mode": mode, "_forced": forced})
        return applied

    def _route_single_l3(self, winner: dict[str, Any]) -> None:
        iface = shlex.quote(str(winner["interface"]))
        peer_ip = winner.get("peer_tunnel_ip")
        via = f" via {shlex.quote(str(peer_ip))}" if peer_ip and ":" not in str(peer_ip) else ""
        shell.shell(f"ip route replace default{via} dev {iface} metric 20", timeout=15)

    def _route_loadbalance_l3(self, winners: list[dict[str, Any]]) -> None:
        chunks = []
        for item in winners:
            iface = shlex.quote(str(item["interface"]))
            peer_ip = item.get("peer_tunnel_ip")
            weight = max(1, int(100 - float(item.get("packet_loss_pct") or 0)))
            via = f" via {shlex.quote(str(peer_ip))}" if peer_ip and ":" not in str(peer_ip) else ""
            chunks.append(f"nexthop{via} dev {iface} weight {weight}")
        shell.shell("ip route replace default scope global " + " ".join(chunks), timeout=15)

    def _proxy_single(self, winner: dict[str, Any]) -> None:
        routing = self.config.get("routing", {})
        forward_port = int(routing.get("proxy_forward_port", 443))
        target_port = int(winner["local_port"])
        self._ensure_proxy_chain(forward_port)
        shell.shell("iptables -t nat -F AUTOTUNNELX_PROXY", timeout=10)
        shell.shell(f"iptables -t nat -A AUTOTUNNELX_PROXY -p tcp --dport {forward_port} -j REDIRECT --to-ports {target_port}", timeout=10)

    def _proxy_nth(self, winners: list[dict[str, Any]]) -> None:
        routing = self.config.get("routing", {})
        forward_port = int(routing.get("proxy_forward_port", 443))
        self._ensure_proxy_chain(forward_port)
        shell.shell("iptables -t nat -F AUTOTUNNELX_PROXY", timeout=10)
        every = len(winners)
        for idx, item in enumerate(winners):
            target_port = int(item["local_port"])
            if idx < every - 1:
                shell.shell(
                    f"iptables -t nat -A AUTOTUNNELX_PROXY -p tcp --dport {forward_port} "
                    f"-m statistic --mode nth --every {every} --packet {idx} -j REDIRECT --to-ports {target_port}",
                    timeout=10,
                )
            else:
                shell.shell(f"iptables -t nat -A AUTOTUNNELX_PROXY -p tcp --dport {forward_port} -j REDIRECT --to-ports {target_port}", timeout=10)

    def _ensure_proxy_chain(self, forward_port: int) -> None:
        shell.shell("iptables -t nat -N AUTOTUNNELX_PROXY 2>/dev/null || true", timeout=10)
        shell.shell(
            f"iptables -t nat -C PREROUTING -p tcp --dport {forward_port} -j AUTOTUNNELX_PROXY 2>/dev/null || "
            f"iptables -t nat -A PREROUTING -p tcp --dport {forward_port} -j AUTOTUNNELX_PROXY",
            timeout=10,
        )
