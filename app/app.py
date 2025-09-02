"""
Immich Drop Uploader – Backend (FastAPI, simplified)
----------------------------------------------------
- Serves static frontend (no settings UI)
- Uploads to Immich using values from .env ONLY
- Duplicate checks (local SHA-1 DB + optional Immich bulk-check)
- WebSocket progress per session
- Ephemeral "Connected" banner via /api/ping
"""

from __future__ import annotations

import asyncio
import io
import json
import hashlib
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
import logging
from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState
from starlette.middleware.sessions import SessionMiddleware
from PIL import Image, ExifTags
try:
    import qrcode
except Exception:
    qrcode = None

from app.config import Settings, load_settings

# ---- App & static ----
app = FastAPI(title="Immich Drop Uploader (Python)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global settings (read-only at runtime)
SETTINGS: Settings = load_settings()

# Basic logging setup using settings
logging.basicConfig(level=SETTINGS.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("immich_drop")

# Cookie-based session for short-lived auth token storage (no persistence)
app.add_middleware(SessionMiddleware, secret_key=SETTINGS.session_secret, same_site="lax")

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Album cache
ALBUM_ID: Optional[str] = None

def reset_album_cache() -> None:
    """Invalidate the cached Immich album id so next use re-resolves it."""
    global ALBUM_ID
    ALBUM_ID = None

# ---------- DB (local dedupe cache) ----------

def db_init() -> None:
    """Create the local SQLite table used for duplicate checks (idempotent)."""
    conn = sqlite3.connect(SETTINGS.state_db)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checksum TEXT UNIQUE,
            filename TEXT,
            size INTEGER,
            device_asset_id TEXT,
            immich_asset_id TEXT,
            created_at TEXT,
            inserted_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()

def db_lookup_checksum(checksum: str) -> Optional[dict]:
    """Return a record for the given checksum if seen before (None if not)."""
    conn = sqlite3.connect(SETTINGS.state_db)
    cur = conn.cursor()
    cur.execute("SELECT checksum, immich_asset_id FROM uploads WHERE checksum = ?", (checksum,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"checksum": row[0], "immich_asset_id": row[1]}
    return None

def db_lookup_device_asset(device_asset_id: str) -> bool:
    """True if a deviceAssetId has been uploaded by this service previously."""
    conn = sqlite3.connect(SETTINGS.state_db)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM uploads WHERE device_asset_id = ?", (device_asset_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row)

def db_insert_upload(checksum: str, filename: str, size: int, device_asset_id: str, immich_asset_id: Optional[str], created_at: str) -> None:
    """Insert a newly-uploaded asset into the local cache (ignore on duplicates)."""
    conn = sqlite3.connect(SETTINGS.state_db)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO uploads (checksum, filename, size, device_asset_id, immich_asset_id, created_at) VALUES (?,?,?,?,?,?)",
        (checksum, filename, size, device_asset_id, immich_asset_id, created_at)
    )
    conn.commit()
    conn.close()

db_init()

# ---------- WebSocket hub ----------

class SessionHub:
    """Holds WebSocket connections per session and broadcasts progress updates."""
    def __init__(self) -> None:
        self.sessions: Dict[str, List[WebSocket]] = {}

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        """Register a newly accepted WebSocket under the given session id."""
        self.sessions.setdefault(session_id, []).append(ws)

    def _cleanup_closed(self, session_id: str) -> None:
        """Drop closed sockets and cleanup empty session buckets."""
        if session_id not in self.sessions:
            return
        self.sessions[session_id] = [w for w in self.sessions[session_id] if w.client_state == WebSocketState.CONNECTED]
        if not self.sessions[session_id]:
            del self.sessions[session_id]

    async def send(self, session_id: str, payload: dict) -> None:
        """Broadcast a JSON payload to all sockets for one session."""
        conns = self.sessions.get(session_id, [])
        for ws in list(conns):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                try:
                    await ws.close()
                except Exception:
                    pass
        self._cleanup_closed(session_id)

    async def disconnect(self, session_id: str, ws: WebSocket) -> None:
        """Remove a socket from the hub and close it (best-effort)."""
        if session_id in self.sessions and ws in self.sessions[session_id]:
            self.sessions[session_id].remove(ws)
            self._cleanup_closed(session_id)
        # Only try to close if the connection is still open
        if ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except Exception:
                pass

hub = SessionHub()

# ---------- Helpers ----------

def sha1_hex(file_bytes: bytes) -> str:
    """Return SHA-1 hex digest of file_bytes."""
    h = hashlib.sha1()
    h.update(file_bytes)
    return h.hexdigest()

def read_exif_datetimes(file_bytes: bytes):
    """
    Extract EXIF DateTimeOriginal / ModifyDate values when possible.
    Returns (created, modified) as datetime or (None, None) on failure.
    """
    created = modified = None
    try:
        with Image.open(io.BytesIO(file_bytes)) as im:
            exif = getattr(im, "_getexif", lambda: None)() or {}
            if exif:
                tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
                dt_original = tags.get("DateTimeOriginal") or tags.get("CreateDate")
                dt_modified = tags.get("ModifyDate") or dt_original
                def parse_dt(s: str):
                    try:
                        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
                    except Exception:
                        return None
                if isinstance(dt_original, str):
                    created = parse_dt(dt_original)
                if isinstance(dt_modified, str):
                    modified = parse_dt(dt_modified)
    except Exception:
        pass
    return created, modified

def immich_headers(request: Optional[Request] = None) -> dict:
    """Headers for Immich API calls using either session access token or API key."""
    headers = {"Accept": "application/json"}
    token = None
    try:
        if request is not None:
            token = request.session.get("accessToken")
    except Exception:
        token = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif SETTINGS.immich_api_key:
        headers["x-api-key"] = SETTINGS.immich_api_key
    return headers

def get_or_create_album(request: Optional[Request] = None, album_name_override: Optional[str] = None) -> Optional[str]:
    """Get existing album by name or create a new one. Returns album ID or None."""
    global ALBUM_ID
    album_name = album_name_override if album_name_override is not None else SETTINGS.album_name
    # Skip if no album name configured
    if not album_name:
        return None
    # Return cached album ID if already fetched and using default settings name
    if album_name_override is None and ALBUM_ID:
        return ALBUM_ID
    try:
        # First, try to find existing album
        url = f"{SETTINGS.normalized_base_url}/albums"
        r = requests.get(url, headers=immich_headers(request), timeout=10)
        
        if r.status_code == 200:
            albums = r.json()
            for album in albums:
                if album.get("albumName") == album_name:
                    found_id = album.get("id")
                    if album_name_override is None:
                        ALBUM_ID = found_id
                        logger.info(f"Found existing album '%s' with ID: %s", album_name, ALBUM_ID)
                        return ALBUM_ID
                    else:
                        return found_id
        
        # Album doesn't exist, create it
        create_url = f"{SETTINGS.normalized_base_url}/albums"
        payload = {
            "albumName": album_name,
            "description": "Auto-created album for Immich Drop uploads"
        }
        r = requests.post(create_url, headers={**immich_headers(request), "Content-Type": "application/json"}, 
                          json=payload, timeout=10)
        
        if r.status_code in (200, 201):
            data = r.json()
            new_id = data.get("id")
            if album_name_override is None:
                ALBUM_ID = new_id
                logger.info("Created new album '%s' with ID: %s", album_name, ALBUM_ID)
                return ALBUM_ID
            else:
                logger.info("Created new album '%s' with ID: %s", album_name, new_id)
                return new_id
        else:
            logger.warning("Failed to create album: %s - %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("Error managing album: %s", e)
    
    return None

def add_asset_to_album(asset_id: str, request: Optional[Request] = None, album_id_override: Optional[str] = None, album_name_override: Optional[str] = None) -> bool:
    """Add an asset to the configured album. Returns True on success."""
    album_id = album_id_override
    if not album_id:
        album_id = get_or_create_album(request=request, album_name_override=album_name_override)
    if not album_id or not asset_id:
        return False
    
    try:
        url = f"{SETTINGS.normalized_base_url}/albums/{album_id}/assets"
        payload = {"ids": [asset_id]}
        r = requests.put(url, headers={**immich_headers(request), "Content-Type": "application/json"}, 
                         json=payload, timeout=10)
        
        if r.status_code == 200:
            results = r.json()
            # Check if any result indicates success
            for result in results:
                if result.get("success"):
                    return True
                elif result.get("error") == "duplicate":
                    # Asset already in album, consider it success
                    return True
        return False
    except Exception as e:
        logger.exception("Error adding asset to album: %s", e)
        return False

def immich_ping() -> bool:
    """Best-effort reachability check against a few Immich endpoints."""
    if not SETTINGS.immich_api_key:
        return False
    base = SETTINGS.normalized_base_url
    for path in ("/server-info", "/server/version", "/users/me"):
        try:
            r = requests.get(f"{base}{path}", headers=immich_headers(), timeout=4)
            if 200 <= r.status_code < 400:
                return True
        except Exception:
            continue
    return False

def immich_bulk_check(checks: List[dict]) -> Dict[str, dict]:
    """Try Immich bulk upload check; return map id->result (or empty on failure)."""
    try:
        url = f"{SETTINGS.normalized_base_url}/assets/bulk-upload-check"
        r = requests.post(url, headers=immich_headers(), json={"assets": checks}, timeout=10)
        if r.status_code == 200:
            results = r.json().get("results", [])
            return {x["id"]: x for x in results}
    except Exception:
        pass
    return {}

async def send_progress(session_id: str, item_id: str, status: str, progress: int = 0, message: str = "", response_id: Optional[str] = None) -> None:
    """Push a progress update over WebSocket for one queue item."""
    await hub.send(session_id, {
        "item_id": item_id,
        "status": status,
        "progress": progress,
        "message": message,
        "responseId": response_id,
    })

# ---------- Routes ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the SPA (frontend/index.html) or redirect to login if disabled."""
    if not SETTINGS.public_upload_page_enabled:
        return RedirectResponse(url="/login")
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/login", response_class=HTMLResponse)
async def login_page(_: Request) -> HTMLResponse:
    """Serve the login page."""
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

@app.get("/menu", response_class=HTMLResponse)
async def menu_page(request: Request) -> HTMLResponse:
    """Serve the menu page for creating invite links. Requires login."""
    if not request.session.get("accessToken"):
        return RedirectResponse(url="/login")
    return FileResponse(os.path.join(FRONTEND_DIR, "menu.html"))

@app.get("/favicon.ico")
async def favicon() -> Response:
    """Serve favicon from /static/favicon.png if present (avoids 404 noise)."""
    path = os.path.join(FRONTEND_DIR, "favicon.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return Response(content=f.read(), media_type="image/png")
    return Response(status_code=204)

@app.post("/api/ping")
async def api_ping() -> dict:
    """Connectivity test endpoint used by the UI to display a temporary banner."""
    return {
        "ok": immich_ping(), 
        "base_url": SETTINGS.normalized_base_url,
        "album_name": SETTINGS.album_name if SETTINGS.album_name else None
    }

@app.get("/api/config")
async def api_config() -> dict:
    """Expose minimal public configuration flags for the frontend."""
    return {
        "public_upload_page_enabled": SETTINGS.public_upload_page_enabled,
    }

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """WebSocket endpoint for pushing per-item upload progress."""
    await ws.accept()
    try:
        init = await ws.receive_text()
        data = json.loads(init)
        session_id = data.get("session_id") or "default"
    except Exception:
        session_id = "default"
    # If this is the first socket for a (possibly new) session, reset album cache
    # so a freshly opened page can rotate the drop album by renaming the old one.
    if session_id not in hub.sessions:
        reset_album_cache()
    await hub.connect(session_id, ws)

    # keepalive to avoid proxy idle timeouts
    try:
        while True:
            msg_task = asyncio.create_task(ws.receive_text())
            keep_task = asyncio.create_task(asyncio.sleep(30))
            done, pending = await asyncio.wait({msg_task, keep_task}, return_when=asyncio.FIRST_COMPLETED)
            if msg_task in done:
                _ = msg_task.result()
            else:
                await ws.send_text('{"type":"ping"}')
            for t in pending:
                t.cancel()
    except WebSocketDisconnect:
        await hub.disconnect(session_id, ws)

@app.post("/api/upload")
async def api_upload(
    request: Request,
    file: UploadFile,
    item_id: str = Form(...),
    session_id: str = Form(...),
    last_modified: Optional[int] = Form(None),
    invite_token: Optional[str] = Form(None),
):
    """Receive a file, check duplicates, forward to Immich; stream progress via WS."""
    raw = await file.read()
    size = len(raw)
    checksum = sha1_hex(raw)

    exif_created, exif_modified = read_exif_datetimes(raw)
    created_at = exif_created or (datetime.fromtimestamp(last_modified / 1000) if last_modified else datetime.utcnow())
    modified_at = exif_modified or created_at
    created_iso = created_at.isoformat()
    modified_iso = modified_at.isoformat()

    device_asset_id = f"{file.filename}-{last_modified or 0}-{size}"

    if db_lookup_checksum(checksum):
        await send_progress(session_id, item_id, "duplicate", 100, "Duplicate (by checksum - local cache)")
        return JSONResponse({"status": "duplicate", "id": None}, status_code=200)
    if db_lookup_device_asset(device_asset_id):
        await send_progress(session_id, item_id, "duplicate", 100, "Already uploaded from this device (local cache)")
        return JSONResponse({"status": "duplicate", "id": None}, status_code=200)

    await send_progress(session_id, item_id, "checking", 2, "Checking duplicates…")
    bulk = immich_bulk_check([{"id": item_id, "checksum": checksum}])
    if bulk.get(item_id, {}).get("action") == "reject" and bulk[item_id].get("reason") == "duplicate":
        asset_id = bulk[item_id].get("assetId")
        db_insert_upload(checksum, file.filename, size, device_asset_id, asset_id, created_iso)
        await send_progress(session_id, item_id, "duplicate", 100, "Duplicate (server)", asset_id)
        return JSONResponse({"status": "duplicate", "id": asset_id}, status_code=200)

    def gen_encoder() -> MultipartEncoder:
        return MultipartEncoder(fields={
            "assetData": (file.filename, io.BytesIO(raw), file.content_type or "application/octet-stream"),
            "deviceAssetId": device_asset_id,
            "deviceId": f"python-{session_id}",
            "fileCreatedAt": created_iso,
            "fileModifiedAt": modified_iso,
            "isFavorite": "false",
            "filename": file.filename,
        })

    encoder = gen_encoder()

    # Invite token validation (if provided)
    target_album_id: Optional[str] = None
    target_album_name: Optional[str] = None
    if invite_token:
        try:
            conn = sqlite3.connect(SETTINGS.state_db)
            cur = conn.cursor()
            cur.execute("SELECT token, album_id, album_name, max_uses, used_count, expires_at, COALESCE(claimed,0), claimed_by_session FROM invites WHERE token = ?", (invite_token,))
            row = cur.fetchone()
            conn.close()
        except Exception as e:
            logger.exception("Invite lookup error: %s", e)
            row = None
        if not row:
            await send_progress(session_id, item_id, "error", 100, "Invalid invite token")
            return JSONResponse({"error": "invalid_invite"}, status_code=403)
        _, album_id, album_name, max_uses, used_count, expires_at, claimed, claimed_by_session = row
        # Expiry check
        if expires_at:
            try:
                if datetime.utcnow() > datetime.fromisoformat(expires_at):
                    await send_progress(session_id, item_id, "error", 100, "Invite expired")
                    return JSONResponse({"error": "invite_expired"}, status_code=403)
            except Exception:
                pass
        # One-time claim or multi-use enforcement
        try:
            max_uses_int = int(max_uses) if max_uses is not None else -1
        except Exception:
            max_uses_int = -1
        if max_uses_int == 1:
            if claimed and claimed_by_session and claimed_by_session != session_id:
                await send_progress(session_id, item_id, "error", 100, "Invite already used")
                return JSONResponse({"error": "invite_claimed"}, status_code=403)
            # Atomically claim the one-time invite to prevent concurrent use
            try:
                connc = sqlite3.connect(SETTINGS.state_db)
                curc = connc.cursor()
                curc.execute(
                    "UPDATE invites SET claimed = 1, claimed_at = CURRENT_TIMESTAMP, claimed_by_session = ? WHERE token = ? AND (claimed IS NULL OR claimed = 0)",
                    (session_id, invite_token)
                )
                connc.commit()
                changed = connc.total_changes
                connc.close()
                if changed == 0 and (claimed_by_session or claimed):
                    await send_progress(session_id, item_id, "error", 100, "Invite already used")
                    return JSONResponse({"error": "invite_claimed"}, status_code=403)
            except Exception as e:
                logger.exception("Invite claim failed: %s", e)
                return JSONResponse({"error": "invite_claim_failed"}, status_code=500)
        else:
            # Usage check for multi-use (max_uses < 0 => indefinite)
            if (used_count or 0) >= (max_uses_int if max_uses_int >= 0 else 10**9):
                await send_progress(session_id, item_id, "error", 100, "Invite already used up")
                return JSONResponse({"error": "invite_exhausted"}, status_code=403)
        target_album_id = album_id
        target_album_name = album_name

    async def do_upload():
        await send_progress(session_id, item_id, "uploading", 0, "Uploading…")
        sent = {"pct": 0}
        def cb(monitor: MultipartEncoderMonitor) -> None:
            if monitor.len:
                pct = int(monitor.bytes_read * 100 / monitor.len)
                if pct != sent["pct"]:
                    sent["pct"] = pct
                    asyncio.create_task(send_progress(session_id, item_id, "uploading", pct))
        monitor = MultipartEncoderMonitor(encoder, cb)
        headers = {"Accept": "application/json", "Content-Type": monitor.content_type, "x-immich-checksum": checksum, **immich_headers(request)}
        try:
            r = requests.post(f"{SETTINGS.normalized_base_url}/assets", headers=headers, data=monitor, timeout=120)
            if r.status_code in (200, 201):
                data = r.json()
                asset_id = data.get("id")
                db_insert_upload(checksum, file.filename, size, device_asset_id, asset_id, created_iso)
                status = data.get("status", "created")
                
                # Add to album if configured (invite overrides .env)
                if asset_id:
                    added = False
                    if invite_token:
                        added = add_asset_to_album(asset_id, request=request, album_id_override=target_album_id, album_name_override=target_album_name)
                        if added:
                            status += f" (added to album '{target_album_name or target_album_id}')"
                    elif SETTINGS.album_name:
                        if add_asset_to_album(asset_id, request=request):
                            status += f" (added to album '{SETTINGS.album_name}')"

                await send_progress(session_id, item_id, "duplicate" if status == "duplicate" else "done", 100, status, asset_id)

                # Increment invite usage on success
                if invite_token:
                    try:
                        conn2 = sqlite3.connect(SETTINGS.state_db)
                        cur2 = conn2.cursor()
                        # Keep one-time used_count at 1; multi-use increments per asset
                        cur2.execute("SELECT max_uses FROM invites WHERE token = ?", (invite_token,))
                        row_mu = cur2.fetchone()
                        mx = None
                        try:
                            mx = int(row_mu[0]) if row_mu and row_mu[0] is not None else None
                        except Exception:
                            mx = None
                        if mx == 1:
                            cur2.execute("UPDATE invites SET used_count = 1 WHERE token = ?", (invite_token,))
                        else:
                            cur2.execute("UPDATE invites SET used_count = used_count + 1 WHERE token = ?", (invite_token,))
                        conn2.commit()
                        conn2.close()
                    except Exception as e:
                        logger.exception("Failed to increment invite usage: %s", e)
                return JSONResponse({"id": asset_id, "status": status}, status_code=200)
            else:
                try:
                    msg = r.json().get("message", r.text)
                except Exception:
                    msg = r.text
                await send_progress(session_id, item_id, "error", 100, msg)
                return JSONResponse({"error": msg}, status_code=400)
        except Exception as e:
            await send_progress(session_id, item_id, "error", 100, str(e))
            return JSONResponse({"error": str(e)}, status_code=500)

    return await do_upload()

@app.post("/api/album/reset")
async def api_album_reset() -> dict:
    """Explicit trigger from the UI to clear cached album id."""
    reset_album_cache()
    return {"ok": True}

# ---------- Auth & Albums & Invites APIs ----------

@app.post("/api/login")
async def api_login(request: Request) -> JSONResponse:
    """Authenticate against Immich using email/password; store token in session."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    email = (body or {}).get("email")
    password = (body or {}).get("password")
    if not email or not password:
        return JSONResponse({"error": "missing_credentials"}, status_code=400)
    try:
        r = requests.post(f"{SETTINGS.normalized_base_url}/auth/login", headers={"Content-Type": "application/json", "Accept": "application/json"}, json={"email": email, "password": password}, timeout=15)
    except Exception as e:
        logger.exception("Login request failed: %s", e)
        return JSONResponse({"error": "login_failed"}, status_code=502)
    if r.status_code not in (200, 201):
        logger.warning("Auth rejected: %s - %s", r.status_code, r.text)
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = r.json() if r.content else {}
    token = data.get("accessToken")
    if not token:
        logger.warning("Auth response missing accessToken")
        return JSONResponse({"error": "invalid_response"}, status_code=502)
    # Store only token and basic info in cookie session
    request.session.update({
        "accessToken": token,
        "userEmail": data.get("userEmail"),
        "userId": data.get("userId"),
        "name": data.get("name"),
        "isAdmin": data.get("isAdmin", False),
    })
    logger.info("User %s logged in", data.get("userEmail"))
    return JSONResponse({"ok": True, **{k: data.get(k) for k in ("userEmail","userId","name","isAdmin")}})

@app.post("/api/logout")
async def api_logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}

@app.get("/logout")
async def logout_get(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/api/albums")
async def api_albums(request: Request) -> JSONResponse:
    """Return list of albums if authorized; logs on 401/403."""
    try:
        r = requests.get(f"{SETTINGS.normalized_base_url}/albums", headers=immich_headers(request), timeout=10)
    except Exception as e:
        logger.exception("Albums request failed: %s", e)
        return JSONResponse({"error": "request_failed"}, status_code=502)
    if r.status_code == 200:
        return JSONResponse(r.json())
    if r.status_code in (401, 403):
        logger.warning("Album list not allowed: %s - %s", r.status_code, r.text)
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse({"error": "unexpected_status", "status": r.status_code}, status_code=502)

@app.post("/api/albums")
async def api_albums_create(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    name = (body or {}).get("name")
    if not name:
        return JSONResponse({"error": "missing_name"}, status_code=400)
    try:
        r = requests.post(f"{SETTINGS.normalized_base_url}/albums", headers={**immich_headers(request), "Content-Type": "application/json"}, json={"albumName": name}, timeout=10)
    except Exception as e:
        logger.exception("Create album failed: %s", e)
        return JSONResponse({"error": "request_failed"}, status_code=502)
    if r.status_code in (200, 201):
        return JSONResponse(r.json(), status_code=201)
    if r.status_code in (401, 403):
        logger.warning("Create album forbidden: %s - %s", r.status_code, r.text)
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse({"error": "unexpected_status", "status": r.status_code, "body": r.text}, status_code=502)

# ---------- Invites (one-time/expiring links) ----------

def ensure_invites_table() -> None:
    try:
        conn = sqlite3.connect(SETTINGS.state_db)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                token TEXT PRIMARY KEY,
                album_id TEXT,
                album_name TEXT,
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                expires_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Attempt to add new columns for claiming semantics
        try:
            cur.execute("ALTER TABLE invites ADD COLUMN claimed INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE invites ADD COLUMN claimed_at TEXT")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE invites ADD COLUMN claimed_by_session TEXT")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception as e:
        logger.exception("Failed to ensure invites table: %s", e)

ensure_invites_table()

@app.post("/api/invites")
async def api_invites_create(request: Request) -> JSONResponse:
    """Create an invite link for uploads with optional expiry and max uses."""
    # Require a logged-in session to create invites
    if not request.session.get("accessToken"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    album_id = (body or {}).get("albumId")
    album_name = (body or {}).get("albumName")
    max_uses = (body or {}).get("maxUses", 1)
    expires_days = (body or {}).get("expiresDays")
    # Normalize max_uses
    try:
        max_uses = int(max_uses)
    except Exception:
        max_uses = 1
    if not album_id and not album_name and not SETTINGS.album_name:
        return JSONResponse({"error": "missing_album"}, status_code=400)
    if not album_name and SETTINGS.album_name:
        album_name = SETTINGS.album_name
    # If only album_name provided, resolve or create now to fix to an ID
    resolved_album_id = None
    if not album_id and album_name:
        resolved_album_id = get_or_create_album(request=request, album_name_override=album_name)
    else:
        resolved_album_id = album_id
    # Compute expiry
    expires_at = None
    if expires_days is not None:
        try:
            days = int(expires_days)
            expires_at = (datetime.utcnow()).replace(microsecond=0).isoformat()
            # Use timedelta
            from datetime import timedelta
            expires_at = (datetime.utcnow() + timedelta(days=days)).replace(microsecond=0).isoformat()
        except Exception:
            expires_at = None
    # Generate token
    import uuid
    token = uuid.uuid4().hex
    try:
        conn = sqlite3.connect(SETTINGS.state_db)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO invites (token, album_id, album_name, max_uses, expires_at) VALUES (?,?,?,?,?)",
            (token, resolved_album_id, album_name, max_uses, expires_at)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.exception("Failed to create invite: %s", e)
        return JSONResponse({"error": "db_error"}, status_code=500)
    # Build absolute URL using PUBLIC_BASE_URL if set, else request base
    try:
        base_url = SETTINGS.public_base_url.strip().rstrip('/') if SETTINGS.public_base_url else str(request.base_url).rstrip('/')
    except Exception:
        base_url = str(request.base_url).rstrip('/')
    absolute = f"{base_url}/invite/{token}"
    return JSONResponse({
        "ok": True,
        "token": token,
        "url": f"/invite/{token}",
        "absoluteUrl": absolute,
        "albumId": resolved_album_id,
        "albumName": album_name,
        "maxUses": max_uses,
        "expiresAt": expires_at
    })

@app.get("/invite/{token}", response_class=HTMLResponse)
async def invite_page(token: str, request: Request) -> HTMLResponse:
    # If public invites disabled and no user session, require login
    #if  not request.session.get("accessToken"):
    #    return RedirectResponse(url="/login")
    return FileResponse(os.path.join(FRONTEND_DIR, "invite.html"))

@app.get("/api/invite/{token}")
async def api_invite_info(token: str) -> JSONResponse:
    try:
        conn = sqlite3.connect(SETTINGS.state_db)
        cur = conn.cursor()
        cur.execute("SELECT token, album_id, album_name, max_uses, used_count, expires_at, COALESCE(claimed,0), claimed_at FROM invites WHERE token = ?", (token,))
        row = cur.fetchone()
        conn.close()
    except Exception as e:
        logger.exception("Invite info error: %s", e)
        return JSONResponse({"error": "db_error"}, status_code=500)
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    _, album_id, album_name, max_uses, used_count, expires_at, claimed, claimed_at = row
    # compute remaining
    remaining = None
    try:
        if max_uses is not None and int(max_uses) >= 0:
            remaining = int(max_uses) - int(used_count or 0)
    except Exception:
        remaining = None
    # compute state flags
    try:
        one_time = (int(max_uses) == 1)
    except Exception:
        one_time = False
    expired = False
    if expires_at:
        try:
            expired = datetime.utcnow() > datetime.fromisoformat(expires_at)
        except Exception:
            expired = False
    deactivated = False
    if one_time and claimed:
        deactivated = True
    elif remaining is not None and remaining <= 0:
        deactivated = True
    if expired:
        deactivated = True
    active = not deactivated
    return JSONResponse({
        "token": token,
        "albumId": album_id,
        "albumName": album_name,
        "maxUses": max_uses,
        "used": used_count or 0,
        "remaining": remaining,
        "expiresAt": expires_at,
        "oneTime": one_time,
        "claimed": bool(claimed),
        "claimedAt": claimed_at,
        "expired": expired,
        "active": active,
    })

@app.get("/api/qr", response_model=None)
async def api_qr(request: Request):
    """Generate a QR code PNG for a given text (query param 'text')."""
    text = request.query_params.get("text")
    if not text:
        return JSONResponse({"error": "missing_text"}, status_code=400)
    if qrcode is None:
        logger.warning("qrcode library not installed; cannot generate QR")
        return JSONResponse({"error": "qr_not_available"}, status_code=501)
    import io as _io
    img = qrcode.make(text)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/png")

"""
Note: Do not run this module directly. Use `python main.py` from
project root, which starts `uvicorn app.app:app` with reload.
"""
