from __future__ import annotations

import logging
import signal
import time
from pathlib import Path
from typing import Any

from .constants import ENGINE_LOG
from .firewall import FirewallManager
from .logging_json import setup_logging
from .metrics import benchmark
from .protocols import adapters_for_config
from .routing import RoutingManager
from .state import StateStore


class AutoTunnelEngine:
    def __init__(self, config: dict[str, Any], *, logger: logging.Logger | None = None):
        self.config = config
        paths = config.get("paths", {})
        log_file = str(Path(paths.get("log_dir", "/var/log/autotunnel")) / ENGINE_LOG)
        self.log = logger or setup_logging(log_file, name="autotunnelx.engine")
        self.state = StateStore(str(Path(paths.get("state_dir", "/var/lib/autotunnel-x")) / "state.db"))
        self.firewall = FirewallManager(config, self.log)
        self.routing = RoutingManager(config, self.log)
        self.running = True

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGHUP, self._reload_logs)

    def _stop(self, *_: object) -> None:
        self.running = False
        self.log.info("engine_stop_requested")

    def _reload_logs(self, *_: object) -> None:
        self.log.info("engine_hup")

    def deploy(self) -> None:
        self.firewall.ensure_baseline()
        self.firewall.open_protocol_ports()
        for adapter in adapters_for_config(self.config, self.log):
            spec = adapter.spec
            try:
                result = adapter.deploy()
                if result.get("status") == "deployed" and spec.get("enabled", True):
                    adapter.start()
                status = {
                    "status": result.get("status", "deployed"),
                    "last_error": ",".join(result.get("missing", [])) if result.get("missing") else None,
                    "score": -1 if result.get("missing") else 0,
                }
                self.state.upsert_tunnel(spec, status)
                self.state.event("tunnel_deploy", spec.get("name"), result)
                self.log.info("tunnel_deploy", extra={"_tunnel": spec.get("name"), "_result": result})
            except Exception as exc:
                self.state.upsert_tunnel(spec, {"status": "deploy_failed", "last_error": str(exc), "score": -1})
                self.state.event("tunnel_deploy_failed", spec.get("name"), {"error": str(exc)})
                self.log.exception("tunnel_deploy_failed", extra={"_tunnel": spec.get("name")})

    def benchmark_once(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for spec in self.config.get("protocols", []):
            try:
                result = benchmark(spec, self.config).asdict()
                active = self._is_active_name(str(spec.get("name")))
                result["active"] = active
                self.state.upsert_tunnel(spec, result)
                row = {**spec, **result}
                rows.append(row)
                self.log.info("benchmark_result", extra={"_tunnel": spec.get("name"), "_metrics": result})
            except Exception as exc:
                result = {"status": "benchmark_failed", "last_error": str(exc), "score": -1}
                self.state.upsert_tunnel(spec, result)
                rows.append({**spec, **result})
                self.log.exception("benchmark_failed", extra={"_tunnel": spec.get("name")})
        return rows

    def route_best(self, rows: list[dict[str, Any]]) -> list[str]:
        manual = self.state.get_kv("manual_override", "")
        healthy = [
            row
            for row in rows
            if row.get("enabled", True)
            and row.get("status") == "healthy"
            and float(row.get("score") or 0) > 0
        ]
        degraded = [
            row
            for row in rows
            if row.get("enabled", True)
            and row.get("status") == "degraded"
            and float(row.get("score") or 0) > 0
        ]
        candidates = healthy + degraded if manual else healthy or degraded
        candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        active = self.routing.apply(candidates, forced=manual or None)
        if active:
            self.state.set_active(active)
            self.state.event("routing_switch", ",".join(active), {"manual_override": manual or None})
        return active

    def run_forever(self) -> None:
        self.install_signal_handlers()
        self.log.info("engine_started", extra={"_role": self.config.get("role"), "_node_id": self.config.get("node_id")})
        self.deploy()
        interval = int(self.config.get("benchmark", {}).get("interval_seconds", 60))
        while self.running:
            started = time.time()
            rows = self.benchmark_once()
            active = self.route_best(rows)
            if active:
                self.log.info("active_tunnels", extra={"_active": active})
            elapsed = time.time() - started
            sleep_for = max(1, interval - int(elapsed))
            for _ in range(sleep_for):
                if not self.running:
                    break
                time.sleep(1)
        self.log.info("engine_stopped")

    def _is_active_name(self, name: str) -> bool:
        active = self.state.get_kv("active_names", [])
        return name in active
