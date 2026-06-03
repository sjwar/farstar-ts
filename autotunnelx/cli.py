from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import build_default_config, load_config, save_config
from .constants import DEFAULT_CONFIG_PATH, DEFAULT_LOG_DIR, DEFAULT_STATE_DIR, ENGINE_LOG
from .engine import AutoTunnelEngine
from .logging_json import setup_logging
from .state import StateStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autotunnelctl", description="AutoTunnel-X control utility")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create initial configuration")
    init.add_argument("--role", required=True, choices=["inbound", "outbound"])
    init.add_argument("--peer", required=True)
    init.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    init.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    init.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    init.add_argument("--web-port", type=int, default=8088)
    init.add_argument("--admin-user", default="admin")
    init.add_argument("--admin-password", required=True)

    for name in ["engine", "deploy", "benchmark", "status", "web", "sync"]:
        cmd = sub.add_parser(name, help=f"{name} AutoTunnel-X")
        cmd.add_argument("--config", default=DEFAULT_CONFIG_PATH)

    sub.choices["sync"].add_argument("--peer-url", default="")
    sub.choices["sync"].add_argument("--token", default="")

    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "engine":
        config = load_config(args.config)
        AutoTunnelEngine(config).run_forever()
        return 0
    if args.command == "deploy":
        config = load_config(args.config)
        AutoTunnelEngine(config).deploy()
        return 0
    if args.command == "benchmark":
        config = load_config(args.config)
        engine = AutoTunnelEngine(config)
        rows = engine.benchmark_once()
        active = engine.route_best(rows)
        print(json.dumps({"rows": rows, "active": active}, indent=2))
        return 0
    if args.command == "status":
        config = load_config(args.config)
        store = _store(config)
        print(json.dumps(store.list_status(), indent=2))
        return 0
    if args.command == "web":
        return cmd_web(args)
    if args.command == "sync":
        return cmd_sync(args)
    return 1


def cmd_init(args: argparse.Namespace) -> int:
    config = build_default_config(
        role=args.role,
        peer=args.peer,
        state_dir=args.state_dir,
        log_dir=args.log_dir,
        web_port=args.web_port,
        admin_user=args.admin_user,
        admin_password=args.admin_password,
    )
    Path(args.state_dir).mkdir(parents=True, exist_ok=True)
    Path(args.log_dir).mkdir(parents=True, exist_ok=True)
    Path(args.state_dir, "protocols").mkdir(parents=True, exist_ok=True)
    save_config(args.config, config)
    StateStore(str(Path(args.state_dir) / "state.db"))
    logger = setup_logging(str(Path(args.log_dir) / ENGINE_LOG), name="autotunnelx.init")
    logger.info("config_initialized", extra={"_config": args.config, "_role": args.role, "_peer": args.peer})
    print(f"Wrote {args.config}")
    print(f"Bootstrap token: {config['peer']['bootstrap_token']}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    import uvicorn

    from .web.app import create_app

    app = create_app(config, config_path=args.config)
    uvicorn.run(app, host=str(config.get("web", {}).get("host", "0.0.0.0")), port=int(config.get("web", {}).get("port", 8088)))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    peer_url = args.peer_url or config.get("peer", {}).get("api_url", "")
    token = args.token or config.get("peer", {}).get("bootstrap_token", "")
    if not peer_url or not token:
        print("peer URL and token are required", file=sys.stderr)
        return 2
    from .sync import sync_with_peer

    result = sync_with_peer(config, args.config, peer_url, token)
    print(json.dumps(result, indent=2))
    return 0


def _store(config: dict[str, Any]) -> StateStore:
    return StateStore(str(Path(config.get("paths", {}).get("state_dir", DEFAULT_STATE_DIR)) / "state.db"))


if __name__ == "__main__":
    raise SystemExit(main())
