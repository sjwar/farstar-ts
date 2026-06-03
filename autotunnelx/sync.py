from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import save_config


def local_public_material(config: dict[str, Any]) -> dict[str, Any]:
    state_dir = Path(config.get("paths", {}).get("protocol_state_dir", "/var/lib/autotunnel-x/protocols"))
    material: dict[str, Any] = {
        "node_id": config.get("node_id"),
        "role": config.get("role"),
        "wireguard_public_key": _read_optional(state_dir / "wireguard" / "publickey"),
        "xray_reality_public_key": _read_optional(state_dir / "xray_vless_reality" / "reality_publickey"),
    }
    return {k: v for k, v in material.items() if v}


def sync_with_peer(config: dict[str, Any], config_path: str, peer_url: str, token: str) -> dict[str, Any]:
    payload = json.dumps(local_public_material(config)).encode("utf-8")
    request = urllib.request.Request(
        peer_url.rstrip("/") + "/api/bootstrap/sync",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-AutoTunnel-Bootstrap": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"peer sync failed: HTTP {exc.code} {exc.read().decode('utf-8', 'ignore')}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"peer sync failed: {exc}") from exc

    peer = config.setdefault("peer", {})
    if data.get("wireguard_public_key"):
        peer["wireguard_public_key"] = data["wireguard_public_key"]
        for spec in config.get("protocols", []):
            if spec.get("type") == "wireguard":
                spec["peer_public_key"] = data["wireguard_public_key"]
    if data.get("xray_reality_public_key"):
        peer["xray_reality_public_key"] = data["xray_reality_public_key"]
    save_config(config_path, config)
    return {"status": "ok", "received": data}


def _read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
