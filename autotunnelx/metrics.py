from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass
from typing import Any

from . import shell


@dataclass(slots=True)
class BenchmarkResult:
    status: str
    latency_ms: float | None = None
    jitter_ms: float | None = None
    packet_loss_pct: float | None = None
    throughput_mbps: float | None = None
    score: float | None = None
    last_error: str | None = None

    def asdict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "latency_ms": self.latency_ms,
            "jitter_ms": self.jitter_ms,
            "packet_loss_pct": self.packet_loss_pct,
            "throughput_mbps": self.throughput_mbps,
            "score": self.score,
            "last_error": self.last_error,
        }


def benchmark(spec: dict[str, Any], config: dict[str, Any]) -> BenchmarkResult:
    if not spec.get("enabled", True):
        return BenchmarkResult(status="disabled", score=-1)
    missing = _missing_credentials(spec, config)
    if missing:
        return BenchmarkResult(status="waiting_for_credentials", score=-1, last_error="missing: " + ",".join(missing))

    if spec.get("mode") == "proxy":
        return proxy_benchmark(spec, config)

    target = _target_for(spec, config)
    if not target:
        return BenchmarkResult(status="no_target", score=-1, last_error="no benchmark target")

    ping = ping_target(target, config)
    throughput = throughput_test(spec, config)
    score = score_result(ping.get("latency_ms"), ping.get("jitter_ms"), ping.get("packet_loss_pct"), throughput)
    unhealthy = _is_unhealthy(ping.get("latency_ms"), ping.get("packet_loss_pct"), throughput, config)
    return BenchmarkResult(
        status="degraded" if unhealthy else "healthy",
        latency_ms=ping.get("latency_ms"),
        jitter_ms=ping.get("jitter_ms"),
        packet_loss_pct=ping.get("packet_loss_pct"),
        throughput_mbps=throughput,
        score=score,
        last_error=ping.get("error"),
    )


def proxy_benchmark(spec: dict[str, Any], config: dict[str, Any]) -> BenchmarkResult:
    targets = config.get("benchmark", {}).get("curl_targets", [])
    if not targets:
        return BenchmarkResult(status="no_target", score=-1, last_error="no curl targets configured")
    timeout = int(config.get("benchmark", {}).get("curl_timeout_seconds", 5))
    count = int(config.get("benchmark", {}).get("ping_count", 5))
    local_port = int(spec.get("local_port", 0))
    if not local_port:
        return BenchmarkResult(status="no_proxy_port", score=-1, last_error="local_port is not configured")

    samples_ms: list[float] = []
    speeds: list[float] = []
    failures = 0
    proxy = f"socks5h://127.0.0.1:{local_port}"
    for idx in range(max(1, count)):
        url = targets[idx % len(targets)]
        result = shell.run(
            [
                "curl",
                "-L",
                "-k",
                "-o",
                "/dev/null",
                "-sS",
                "--proxy",
                proxy,
                "--max-time",
                str(timeout),
                "-w",
                "%{time_total} %{size_download}",
                url,
            ],
            timeout=timeout + 2,
        )
        if not result.ok:
            failures += 1
            continue
        parts = result.stdout.split()
        if len(parts) != 2:
            failures += 1
            continue
        try:
            elapsed = max(float(parts[0]), 0.001)
            size = int(float(parts[1]))
        except ValueError:
            failures += 1
            continue
        samples_ms.append(elapsed * 1000.0)
        if size > 0:
            speeds.append((size * 8.0 / elapsed) / 1_000_000.0)

    total = max(1, count)
    loss = round((failures / total) * 100.0, 3)
    latency = round(statistics.mean(samples_ms), 3) if samples_ms else None
    jitter = round(statistics.pstdev(samples_ms), 3) if len(samples_ms) > 1 else 0.0 if samples_ms else None
    throughput = round(statistics.median(speeds), 3) if speeds else None
    score = score_result(latency, jitter, loss, throughput)
    unhealthy = _is_unhealthy(latency, loss, throughput, config)
    return BenchmarkResult(
        status="degraded" if unhealthy else "healthy",
        latency_ms=latency,
        jitter_ms=jitter,
        packet_loss_pct=loss,
        throughput_mbps=throughput,
        score=score,
        last_error=None if failures < total else "all proxy probes failed",
    )


def ping_target(target: str, config: dict[str, Any]) -> dict[str, Any]:
    bench = config.get("benchmark", {})
    count = int(bench.get("ping_count", 5))
    timeout = int(bench.get("ping_timeout_seconds", 4))
    cmd = ["ping", "-c", str(count), "-W", str(timeout), target]
    result = shell.run(cmd, timeout=max(10, count * timeout + 2))
    out = "\n".join([result.stdout, result.stderr])
    loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", out)
    rtt_match = re.search(r"(?:rtt|round-trip).*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    latency = None
    jitter = None
    if rtt_match:
        samples = [float(rtt_match.group(i)) for i in range(1, 5)]
        latency = samples[1]
        jitter = samples[3]
    return {
        "latency_ms": latency,
        "jitter_ms": jitter,
        "packet_loss_pct": loss,
        "error": None if result.ok else (result.stderr or result.stdout or "ping failed")[:500],
    }


def throughput_test(spec: dict[str, Any], config: dict[str, Any]) -> float | None:
    target = _target_for(spec, config)
    if not target:
        return None
    duration = int(config.get("benchmark", {}).get("iperf_seconds", 4))
    iperf_cmd = ["iperf3", "-c", target, "-J", "-t", str(duration)]
    if spec.get("mode") == "l3" and spec.get("interface"):
        iperf_cmd.extend(["--bind-dev", str(spec["interface"])])
    result = shell.run(iperf_cmd, timeout=duration + 8)
    if result.ok and result.stdout:
        try:
            import json

            data = json.loads(result.stdout)
            bps = data.get("end", {}).get("sum_received", {}).get("bits_per_second")
            if bps:
                return round(float(bps) / 1_000_000, 3)
        except Exception:
            pass

    # Fallback to small HTTPS probes when iperf3 is unavailable on the peer.
    targets = config.get("benchmark", {}).get("curl_targets", [])
    speeds: list[float] = []
    for url in targets[:3]:
        start = time.perf_counter()
        cmd = ["curl", "-L", "-k", "-o", "/dev/null", "-sS", "-w", "%{size_download}", "--max-time", str(config.get("benchmark", {}).get("curl_timeout_seconds", 5))]
        if spec.get("mode") == "l3" and spec.get("interface"):
            cmd.extend(["--interface", str(spec["interface"])])
        cmd.append(url)
        curl = shell.run(
            cmd,
            timeout=int(config.get("benchmark", {}).get("curl_timeout_seconds", 5)) + 2,
        )
        elapsed = max(time.perf_counter() - start, 0.001)
        if curl.ok and curl.stdout.isdigit():
            speeds.append((int(curl.stdout) * 8 / elapsed) / 1_000_000)
    if speeds:
        return round(statistics.median(speeds), 3)
    return None


def score_result(latency: float | None, jitter: float | None, loss: float | None, throughput: float | None) -> float:
    latency_penalty = min(latency or 1000.0, 2000.0) / 20.0
    jitter_penalty = min(jitter or 250.0, 500.0) / 10.0
    loss_penalty = min(loss if loss is not None else 100.0, 100.0) * 6.0
    throughput_bonus = min(throughput or 0.0, 1000.0) / 8.0
    return round(max(0.0, 100.0 + throughput_bonus - latency_penalty - jitter_penalty - loss_penalty), 3)


def _is_unhealthy(latency: float | None, loss: float | None, throughput: float | None, config: dict[str, Any]) -> bool:
    routing = config.get("routing", {})
    if loss is None or loss > float(routing.get("packet_loss_threshold_pct", 5.0)):
        return True
    if latency is None or latency > float(routing.get("latency_threshold_ms", 650.0)):
        return True
    if throughput is not None and throughput < float(routing.get("min_throughput_mbps", 1.0)):
        return True
    return False


def _target_for(spec: dict[str, Any], config: dict[str, Any]) -> str | None:
    if spec.get("mode") == "l3" and spec.get("peer_tunnel_ip"):
        return str(spec["peer_tunnel_ip"])
    peer = config.get("peer", {}).get("host")
    return str(peer) if peer else None


def _missing_credentials(spec: dict[str, Any], config: dict[str, Any]) -> list[str]:
    creds = config.get("credentials", {})
    missing: list[str] = []
    for key in spec.get("credential_keys", []):
        if not creds.get(key):
            missing.append(str(key))
    return missing
