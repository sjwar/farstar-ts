from __future__ import annotations

import os
import socket
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .constants import DEFAULT_LOG_DIR, DEFAULT_STATE_DIR, default_protocols
from .security import hash_password, random_token


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("paths", {})
    data["paths"].setdefault("state_dir", DEFAULT_STATE_DIR)
    data["paths"].setdefault("log_dir", DEFAULT_LOG_DIR)
    data.setdefault("protocols", [])
    data.setdefault("routing", {})
    data.setdefault("benchmark", {})
    return data


def save_config(path: str | os.PathLike[str], config: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)
    os.chmod(target, 0o640)


def get_protocol(config: dict[str, Any], name: str) -> dict[str, Any] | None:
    for spec in config.get("protocols", []):
        if spec.get("name") == name:
            return spec
    return None


def build_default_config(
    *,
    role: str,
    peer: str,
    state_dir: str = DEFAULT_STATE_DIR,
    log_dir: str = DEFAULT_LOG_DIR,
    web_port: int = 8088,
    admin_user: str = "admin",
    admin_password: str,
) -> dict[str, Any]:
    if role not in {"inbound", "outbound"}:
        raise ValueError("role must be inbound or outbound")

    protocols = deepcopy(default_protocols())
    if role == "inbound":
        for spec in protocols:
            if spec.get("local_tunnel_ip") and spec.get("peer_tunnel_ip"):
                local = spec["local_tunnel_ip"]
                peer_ip = spec["peer_tunnel_ip"]
                if ":" in str(local):
                    spec["local_tunnel_ip"] = "fd71:71::2/126" if spec["type"] == "sit" else local
                    spec["peer_tunnel_ip"] = "fd71:71::1" if spec["type"] == "sit" else peer_ip
                else:
                    spec["local_tunnel_ip"], spec["peer_tunnel_ip"] = _swap_ipv4_pair(str(local), str(peer_ip))

    node_id = socket.gethostname() + "-" + uuid.uuid4().hex[:8]
    return {
        "version": 1,
        "node_id": node_id,
        "role": role,
        "peer": {
            "host": peer,
            "api_url": f"http://{peer}:{web_port}",
            "bootstrap_token": random_token(24),
        },
        "paths": {
            "state_dir": state_dir,
            "log_dir": log_dir,
            "protocol_state_dir": f"{state_dir}/protocols",
        },
        "web": {
            "host": "0.0.0.0",
            "port": int(web_port),
            "admin_user": admin_user,
            "admin_password_hash": hash_password(admin_password),
            "jwt_secret": random_token(48),
            "cookie_secure": False,
        },
        "routing": {
            "enabled": True,
            "mode": "failover",
            "load_balance_top_n": 3,
            "main_table": 254,
            "managed_mark": 171,
            "packet_loss_threshold_pct": 5.0,
            "latency_threshold_ms": 650.0,
            "jitter_threshold_ms": 120.0,
            "min_throughput_mbps": 1.0,
            "failover_cooldown_seconds": 45,
            "proxy_forward_port": 443,
            "proxy_bind_addr": "127.0.0.1",
        },
        "benchmark": {
            "interval_seconds": 60,
            "ping_count": 5,
            "ping_timeout_seconds": 4,
            "iperf_seconds": 4,
            "curl_timeout_seconds": 5,
            "curl_targets": [
                "https://1.1.1.1/cdn-cgi/trace",
                "https://cloudflare.com/cdn-cgi/trace",
                "https://www.google.com/generate_204",
            ],
        },
        "credentials": {
            "shared_secret": random_token(32),
            "xray_uuid": str(uuid.uuid4()),
            "xray_reality_short_id": "a1b2c3d4e5f6a7b8",
            "trojan_password": random_token(24),
            "hysteria_password": random_token(24),
            "tuic_uuid": str(uuid.uuid4()),
            "tuic_password": random_token(24),
            "juicity_uuid": str(uuid.uuid4()),
            "juicity_password": random_token(24),
            "shadowtls_password": random_token(24),
            "ssh_user": "root",
            "ssh_key_path": "/root/.ssh/id_ed25519",
            "cloudflared_token": "",
            "cloudflared_hostname": "",
            "cdn_host": "",
            "dns_tunnel_domain": "",
        },
        "protocols": protocols,
    }


def _swap_ipv4_pair(local_cidr: str, peer_ip: str) -> tuple[str, str]:
    if "/" not in local_cidr:
        return local_cidr, peer_ip
    prefix = local_cidr.rsplit(".", 1)[0]
    mask = local_cidr.split("/", 1)[1]
    return f"{prefix}.2/{mask}", f"{prefix}.1"
