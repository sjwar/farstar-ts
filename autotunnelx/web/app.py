from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import load_config, save_config
from ..constants import WEB_LOG
from ..logging_json import setup_logging
from ..security import create_jwt, verify_jwt, verify_password
from ..state import StateStore
from ..sync import local_public_material

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def create_app(config: dict[str, Any], *, config_path: str) -> FastAPI:
    paths = config.get("paths", {})
    logger = setup_logging(str(Path(paths.get("log_dir", "/var/log/autotunnel")) / WEB_LOG), name="autotunnelx.web")
    store = StateStore(str(Path(paths.get("state_dir", "/var/lib/autotunnel-x")) / "state.db"))
    app = FastAPI(title="AutoTunnel-X", version="1.0.0")
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    app.state.config = config
    app.state.config_path = config_path
    app.state.store = store
    app.state.log = logger

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        response = await call_next(request)
        logger.info(
            "web_access",
            extra={
                "_method": request.method,
                "_path": request.url.path,
                "_status": response.status_code,
                "_client": request.client.host if request.client else "",
            },
        )
        return response

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse("login.html", {"request": request, "error": ""})

    @app.post("/login")
    async def login(request: Request, username: str = Form(...), password: str = Form(...)):
        web = app.state.config.get("web", {})
        if username != web.get("admin_user") or not verify_password(password, web.get("admin_password_hash", "")):
            logger.warning("login_failed", extra={"_username": username, "_client": request.client.host if request.client else ""})
            return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"}, status_code=401)
        jwt_secret = web.get("jwt_secret")
        if not jwt_secret:
            raise HTTPException(status_code=500, detail="JWT secret is not configured")
        token = create_jwt({"sub": username, "role": "admin"}, jwt_secret)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            "atx_token",
            token,
            httponly=True,
            secure=bool(web.get("cookie_secure", False)),
            samesite="lax",
            max_age=12 * 3600,
        )
        logger.info("login_success", extra={"_username": username})
        return response

    @app.get("/logout")
    async def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("atx_token")
        return response

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, user: dict[str, Any] = Depends(require_user)):
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "config": app.state.config,
                "manual_override": store.get_kv("manual_override", ""),
            },
        )

    @app.get("/api/status")
    async def api_status(_: dict[str, Any] = Depends(require_user)):
        return {"status": store.list_status(), "manual_override": store.get_kv("manual_override", "")}

    @app.get("/api/history")
    async def api_history(name: str | None = None, limit: int = 240, _: dict[str, Any] = Depends(require_user)):
        return {"history": store.history(name=name, limit=min(max(limit, 1), 2000))}

    @app.post("/api/manual-override")
    async def api_manual_override(name: str = Form(""), _: dict[str, Any] = Depends(require_user)):
        allowed = {row["name"] for row in store.list_status()}
        if name and name not in allowed:
            raise HTTPException(status_code=400, detail="Unknown tunnel")
        store.set_kv("manual_override", name)
        store.event("manual_override", name or None, {"name": name or None})
        logger.info("manual_override", extra={"_tunnel": name or ""})
        return RedirectResponse("/", status_code=303)

    @app.post("/api/config")
    async def api_config(
        peer_host: str = Form(...),
        peer_api_url: str = Form(...),
        peer_bootstrap_token: str = Form(""),
        routing_mode: str = Form(...),
        packet_loss_threshold_pct: float = Form(...),
        latency_threshold_ms: float = Form(...),
        ssh_user: str = Form("root"),
        ssh_key_path: str = Form("/root/.ssh/id_ed25519"),
        cloudflared_token: str = Form(""),
        cloudflared_hostname: str = Form(""),
        cdn_host: str = Form(""),
        dns_tunnel_domain: str = Form(""),
        _: dict[str, Any] = Depends(require_user),
    ):
        if routing_mode not in {"failover", "loadbalance"}:
            raise HTTPException(status_code=400, detail="Invalid routing mode")
        fresh = load_config(app.state.config_path)
        fresh.setdefault("peer", {})["host"] = peer_host.strip()
        fresh.setdefault("peer", {})["api_url"] = peer_api_url.strip()
        if peer_bootstrap_token.strip():
            fresh["peer"]["bootstrap_token"] = peer_bootstrap_token.strip()
        fresh.setdefault("routing", {})["mode"] = routing_mode
        fresh["routing"]["packet_loss_threshold_pct"] = float(packet_loss_threshold_pct)
        fresh["routing"]["latency_threshold_ms"] = float(latency_threshold_ms)
        creds = fresh.setdefault("credentials", {})
        creds["ssh_user"] = ssh_user.strip() or "root"
        creds["ssh_key_path"] = ssh_key_path.strip() or "/root/.ssh/id_ed25519"
        creds["cloudflared_token"] = cloudflared_token.strip()
        creds["cloudflared_hostname"] = cloudflared_hostname.strip()
        creds["cdn_host"] = cdn_host.strip()
        creds["dns_tunnel_domain"] = dns_tunnel_domain.strip()
        save_config(app.state.config_path, fresh)
        app.state.config = fresh
        logger.info("config_updated", extra={"_peer": peer_host, "_routing_mode": routing_mode})
        return RedirectResponse("/", status_code=303)

    @app.post("/api/bootstrap/sync")
    async def bootstrap_sync(request: Request):
        token = request.headers.get("X-AutoTunnel-Bootstrap", "")
        expected = app.state.config.get("peer", {}).get("bootstrap_token", "")
        if not expected or token != expected:
            logger.warning("bootstrap_denied", extra={"_client": request.client.host if request.client else ""})
            raise HTTPException(status_code=403, detail="Invalid bootstrap token")
        payload = await request.json()
        fresh = load_config(app.state.config_path)
        peer = fresh.setdefault("peer", {})
        if payload.get("wireguard_public_key"):
            peer["wireguard_public_key"] = payload["wireguard_public_key"]
            for spec in fresh.get("protocols", []):
                if spec.get("type") == "wireguard":
                    spec["peer_public_key"] = payload["wireguard_public_key"]
        if payload.get("xray_reality_public_key"):
            peer["xray_reality_public_key"] = payload["xray_reality_public_key"]
        save_config(app.state.config_path, fresh)
        app.state.config = fresh
        logger.info("bootstrap_sync", extra={"_peer_node": payload.get("node_id", "")})
        return local_public_material(fresh)

    @app.websocket("/ws/logs")
    async def ws_logs(websocket: WebSocket):
        token = websocket.cookies.get("atx_token", "")
        user = verify_jwt(token, app.state.config.get("web", {}).get("jwt_secret", ""))
        if not user:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        log_file = Path(app.state.config.get("paths", {}).get("log_dir", "/var/log/autotunnel")) / "engine.log"
        try:
            await follow_log(websocket, log_file)
        except WebSocketDisconnect:
            return

    return app


async def require_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get("atx_token", "")
    secret = request.app.state.config.get("web", {}).get("jwt_secret", "")
    user = verify_jwt(token, secret)
    if not user:
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="Not authenticated")
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


async def follow_log(websocket: WebSocket, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(0, 2)
        while True:
            line = fh.readline()
            if line:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = {"message": line.strip(), "level": "INFO"}
                await websocket.send_json(payload)
            else:
                await asyncio.sleep(0.5)
