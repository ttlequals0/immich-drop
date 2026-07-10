"""
Single client for all Immich server API calls (v3 API).

Immich v3 validates upload fields with Zod: unknown fields are rejected and
fileCreatedAt/fileModifiedAt must be ISO-8601 with an explicit timezone
offset. AssetMediaCreateDto allows only: assetData, duration, fileCreatedAt,
fileModifiedAt, filename, isFavorite, livePhotoVideoId, metadata,
sidecarData, visibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import httpx

logger = logging.getLogger("immich_drop.immich_client")

_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB


def to_immich_iso(dt: Optional[datetime]) -> str:
    """Format a datetime as ISO-8601 with a timezone offset (required by v3)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="milliseconds")


def parse_error(resp: httpx.Response) -> str:
    """Extract a readable message from an Immich error response.

    v3 returns Zod-shaped bodies where message may be a string, list, or
    nested error objects.
    """
    try:
        data = resp.json()
    except Exception:
        return (resp.text or f"HTTP {resp.status_code}").strip()[:300]
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, list):
        msg = "; ".join(str(m) for m in msg)
    elif isinstance(msg, dict):
        msg = json.dumps(msg)
    if not msg and isinstance(data, dict):
        errs = data.get("errors")
        if isinstance(errs, list):
            parts = []
            for e in errs:
                if isinstance(e, dict):
                    path = e.get("path")
                    m = e.get("message") or e.get("code") or json.dumps(e)
                    parts.append(f"{path}: {m}" if path else str(m))
                else:
                    parts.append(str(e))
            msg = "; ".join(parts)
    return str(msg or resp.text or f"HTTP {resp.status_code}").strip()[:300]


@dataclass
class UploadOutcome:
    ok: bool
    status_code: int
    asset_id: Optional[str] = None
    status: str = ""  # "created" or "duplicate" on success
    error: Optional[str] = None


def _multipart_parts(fields: Dict[str, str], filename: str, content_type: str, boundary: str) -> tuple[bytes, bytes]:
    """Build the multipart head (fields + file part header) and tail."""
    safe = filename.replace("\\", "_").replace('"', "'")
    head = "".join(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        for k, v in fields.items()
    )
    head += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"assetData\"; "
        f"filename=\"{safe}\"\r\nContent-Type: {content_type}\r\n\r\n"
    )
    tail = f"\r\n--{boundary}--\r\n"
    return head.encode("utf-8"), tail.encode("utf-8")


async def upload_asset(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    *,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    checksum: str,
    created_at: Optional[datetime] = None,
    modified_at: Optional[datetime] = None,
    progress: Optional[Callable[[int], None]] = None,
    timeout: float = 300.0,
) -> UploadOutcome:
    """POST /assets with a streaming multipart body and optional progress callback.

    progress is called with 0-100 whenever the sent percentage changes.
    """
    fields = {
        "fileCreatedAt": to_immich_iso(created_at),
        "fileModifiedAt": to_immich_iso(modified_at or created_at),
        "isFavorite": "false",
        "filename": filename,
    }
    boundary = uuid.uuid4().hex
    head, tail = _multipart_parts(fields, filename, content_type or "application/octet-stream", boundary)
    total = len(head) + len(file_bytes) + len(tail)

    async def body():
        sent = 0
        last_pct = -1
        for blob in (head, file_bytes, tail):
            for i in range(0, len(blob), _UPLOAD_CHUNK):
                chunk = blob[i:i + _UPLOAD_CHUNK]
                sent += len(chunk)
                if progress:
                    pct = int(sent * 100 / total)
                    if pct != last_pct:
                        last_pct = pct
                        progress(pct)
                yield chunk
                # Let progress messages flush between chunks
                await asyncio.sleep(0)

    req_headers = {
        **headers,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(total),
        "x-immich-checksum": checksum,
    }
    try:
        r = await client.post(f"{base_url}/assets", headers=req_headers, content=body(), timeout=timeout)
    except Exception as e:
        return UploadOutcome(ok=False, status_code=0, error=str(e))
    if r.status_code in (200, 201):
        data = r.json()
        return UploadOutcome(
            ok=True,
            status_code=r.status_code,
            asset_id=data.get("id"),
            status=data.get("status", "created"),
        )
    return UploadOutcome(ok=False, status_code=r.status_code, error=parse_error(r))


async def bulk_upload_check(client: httpx.AsyncClient, base_url: str, headers: Dict[str, str], checks: List[dict]) -> Dict[str, dict]:
    """POST /assets/bulk-upload-check; returns map id->result (empty on failure)."""
    try:
        r = await client.post(
            f"{base_url}/assets/bulk-upload-check",
            headers=headers,
            json={"assets": checks},
            timeout=10.0,
        )
        if r.status_code == 200:
            results = r.json().get("results", [])
            return {x["id"]: x for x in results}
    except Exception:
        pass
    return {}


async def find_or_create_album(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    album_name: str,
    description: Optional[str] = None,
) -> Optional[str]:
    """Find an album by name or create it. Returns the album id or None."""
    try:
        r = await client.get(f"{base_url}/albums", headers=headers, timeout=10.0)
        if r.status_code == 200:
            for album in r.json():
                if album.get("albumName") == album_name:
                    return album.get("id")
        elif r.status_code >= 500:
            # Do not create albums while Immich is erroring; avoids duplicates
            logger.warning("Immich returned %s when listing albums, skipping album assignment", r.status_code)
            return None
        payload = {"albumName": album_name}
        if description:
            payload["description"] = description
        r = await client.post(
            f"{base_url}/albums",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=10.0,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        logger.warning("Failed to create album: %s - %s", r.status_code, parse_error(r))
    except Exception as e:
        logger.exception("Error managing album: %s", e)
    return None


async def add_to_album(client: httpx.AsyncClient, base_url: str, headers: Dict[str, str], album_id: str, asset_id: str) -> bool:
    """PUT /albums/{id}/assets. Duplicate membership counts as success."""
    if not album_id or not asset_id:
        return False
    try:
        r = await client.put(
            f"{base_url}/albums/{album_id}/assets",
            headers={**headers, "Content-Type": "application/json"},
            json={"ids": [asset_id]},
            timeout=10.0,
        )
        if r.status_code == 200:
            for result in r.json():
                if result.get("success") or result.get("error") == "duplicate":
                    return True
        return False
    except Exception as e:
        logger.exception("Error adding asset to album: %s", e)
        return False


async def ping(client: httpx.AsyncClient, base_url: str, headers: Dict[str, str]) -> bool:
    """Best-effort reachability check (v3 endpoints)."""
    for path in ("/server/ping", "/server/version", "/users/me"):
        try:
            r = await client.get(f"{base_url}{path}", headers=headers, timeout=4.0)
            if 200 <= r.status_code < 400:
                return True
        except Exception:
            continue
    return False
