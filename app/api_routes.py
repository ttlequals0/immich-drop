"""
API Routes for immich-drop extensions
- URL download and upload to Immich
- Batch upload for iOS Shortcuts
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import hashlib
import httpx
import os
import base64
import mimetypes

from .url_downloader import (
    download_from_url,
    download_multiple_urls,
    cleanup_download,
    is_supported_url,
    identify_platform,
    SUPPORTED_PATTERNS,
)
from .cookie_manager import get_cookie_file_for_platform


router = APIRouter(prefix="/api", tags=["api"])


# ============================================================================
# File Type Detection (Magic Bytes)
# ============================================================================

def detect_file_type(data: bytes) -> tuple[str, str]:
    """
    Detect file type from magic bytes.
    Returns (extension, mime_type) or (None, None) if unknown.
    """
    if len(data) < 12:
        return None, None

    # JPEG: FF D8 FF
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg', 'image/jpeg'

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png', 'image/png'

    # GIF: GIF87a or GIF89a
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif', 'image/gif'

    # WebP: RIFF....WEBP
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp', 'image/webp'

    # HEIC/HEIF/AVIF: ftyp box with brand
    if data[4:8] == b'ftyp':
        brand = data[8:12]
        if brand in (b'heic', b'heix', b'hevc', b'hevx', b'mif1'):
            return '.heic', 'image/heic'
        if brand == b'avif':
            return '.avif', 'image/avif'
        # MP4/MOV video formats
        if brand in (b'isom', b'iso2', b'mp41', b'mp42', b'M4V ', b'M4A '):
            return '.mp4', 'video/mp4'
        if brand == b'qt  ':
            return '.mov', 'video/quicktime'

    # BMP: BM
    if data[:2] == b'BM':
        return '.bmp', 'image/bmp'

    # TIFF: II or MM
    if data[:4] in (b'II*\x00', b'MM\x00*'):
        return '.tiff', 'image/tiff'

    return None, None


# ============================================================================
# Request/Response Models
# ============================================================================

class UrlUploadRequest(BaseModel):
    url: str
    album_name: Optional[str] = None


class UrlBatchUploadRequest(BaseModel):
    urls: List[str]
    album_name: Optional[str] = None


class Base64UploadRequest(BaseModel):
    """Request model for base64-encoded file upload (iOS Shortcuts compatible)"""
    data: str  # base64-encoded file content
    filename: Optional[str] = None
    album_name: Optional[str] = None


class UploadResult(BaseModel):
    filename: str
    status: str  # "success", "error", "duplicate"
    asset_id: Optional[str] = None
    duplicate: bool = False
    error: Optional[str] = None
    platform: Optional[str] = None


class UrlUploadResponse(BaseModel):
    success: bool
    result: Optional[UploadResult] = None
    error: Optional[str] = None


class BatchUploadResponse(BaseModel):
    total: int
    successful: int
    duplicates: int
    failed: int
    results: List[UploadResult]


class SupportedPlatformsResponse(BaseModel):
    platforms: List[str]
    examples: dict


# ============================================================================
# Helper Functions
# ============================================================================

async def upload_to_immich(
    file_content: bytes,
    filename: str,
    content_type: str,
    config,  # Config object from main app
    httpx_client: httpx.AsyncClient,  # Shared httpx client
    device_id: str = "immich-drop-url",
    file_created_at: Optional[str] = None,
) -> UploadResult:
    """Upload a file to Immich server"""
    sha1 = hashlib.sha1(file_content).hexdigest()
    now = file_created_at or (datetime.utcnow().isoformat() + "Z")
    device_asset_id = f"{device_id}-{sha1}"

    try:
        resp = await httpx_client.post(
            f"{config.normalized_base_url}/assets",
            files={"assetData": (filename, file_content, content_type)},
            data={
                "deviceAssetId": device_asset_id,
                "deviceId": device_id,
                "fileCreatedAt": now,
                "fileModifiedAt": now,
                "isFavorite": "false",
            },
            headers={
                "x-api-key": config.immich_api_key,
                "x-immich-checksum": sha1,
            },
            timeout=300.0,
        )

        if resp.status_code in (200, 201):
            result = resp.json()
            return UploadResult(
                filename=filename,
                status="success",
                asset_id=result.get("id"),
                duplicate=result.get("duplicate", False),
            )
        else:
            return UploadResult(
                filename=filename,
                status="error",
                error=f"Immich returned {resp.status_code}: {resp.text[:200]}",
            )
    except Exception as e:
        return UploadResult(
            filename=filename,
            status="error",
            error=str(e),
        )


async def add_asset_to_album(
    asset_id: str,
    album_name: str,
    config,
    httpx_client: httpx.AsyncClient,  # Shared httpx client
) -> bool:
    """Add an asset to an album (creates album if needed)"""
    headers = {"x-api-key": config.immich_api_key}

    # Find or create album
    albums_resp = await httpx_client.get(
        f"{config.normalized_base_url}/albums",
        headers=headers,
        timeout=30.0,
    )

    album_id = None
    if albums_resp.status_code == 200:
        albums = albums_resp.json()
        for album in albums:
            if album.get("albumName") == album_name:
                album_id = album.get("id")
                break

    # Create album if not found
    if not album_id:
        create_resp = await httpx_client.post(
            f"{config.normalized_base_url}/albums",
            headers=headers,
            json={"albumName": album_name},
            timeout=30.0,
        )
        if create_resp.status_code in (200, 201):
            album_id = create_resp.json().get("id")

    if not album_id:
        return False

    # Add asset to album
    add_resp = await httpx_client.put(
        f"{config.normalized_base_url}/albums/{album_id}/assets",
        headers=headers,
        json={"ids": [asset_id]},
        timeout=30.0,
    )

    return add_resp.status_code in (200, 201)


# ============================================================================
# API Endpoints
# ============================================================================

def create_api_routes(config):
    """Factory function to create routes with config injection"""

    @router.get("/supported-platforms", response_model=SupportedPlatformsResponse)
    async def get_supported_platforms():
        """Get list of supported platforms for URL downloads"""
        return SupportedPlatformsResponse(
            platforms=list(SUPPORTED_PATTERNS.keys()),
            examples={
                "tiktok": "https://www.tiktok.com/@user/video/123456",
                "instagram": "https://www.instagram.com/reel/ABC123/",
                "reddit": "https://www.reddit.com/r/subreddit/comments/abc123/title",
                "youtube": "https://www.youtube.com/shorts/ABC123",
                "twitter": "https://twitter.com/user/status/123456789",
            }
        )

    @router.post("/upload/url", response_model=UrlUploadResponse)
    async def upload_from_url(
        url_request: UrlUploadRequest,
        background_tasks: BackgroundTasks,
        request: Request,
    ):
        """
        Download media from a supported URL and upload to Immich

        Supported platforms: TikTok, Instagram, Reddit, YouTube, Twitter/X
        """
        url = url_request.url.strip()
        httpx_client = request.app.state.httpx_client

        # Validate URL
        platform = identify_platform(url)
        if not platform:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported URL. Supported platforms: {', '.join(SUPPORTED_PATTERNS.keys())}"
            )

        # Look up cookies for this platform (if configured)
        cookies_file = get_cookie_file_for_platform(platform, config.state_db)

        # Download the file
        download_result = await download_from_url(url, cookies_file=cookies_file)

        if not download_result.success:
            return UrlUploadResponse(
                success=False,
                error=download_result.error,
            )

        try:
            # Read file content
            with open(download_result.filepath, "rb") as f:
                file_content = f.read()

            # Extract timestamp from metadata if available
            file_created_at = None
            if download_result.metadata:
                timestamp = download_result.metadata.get("timestamp")
                if timestamp:
                    file_created_at = datetime.fromtimestamp(timestamp).isoformat() + "Z"

            # Upload to Immich
            upload_result = await upload_to_immich(
                file_content=file_content,
                filename=download_result.filename,
                content_type=download_result.content_type,
                config=config,
                httpx_client=httpx_client,
                device_id=f"immich-drop-{platform}",
                file_created_at=file_created_at,
            )
            upload_result.platform = platform

            # Add to album if specified or configured
            album_name = url_request.album_name or getattr(config, 'album_name', None)
            if album_name and upload_result.asset_id and upload_result.status == "success":
                await add_asset_to_album(upload_result.asset_id, album_name, config, httpx_client)

            return UrlUploadResponse(
                success=upload_result.status == "success",
                result=upload_result,
                error=upload_result.error,
            )

        finally:
            # Clean up downloaded file
            background_tasks.add_task(cleanup_download, download_result)

    @router.post("/upload/urls", response_model=BatchUploadResponse)
    async def upload_from_urls(
        batch_request: UrlBatchUploadRequest,
        background_tasks: BackgroundTasks,
        request: Request,
    ):
        """
        Download and upload multiple URLs to Immich

        Max 10 URLs per request
        """
        urls = [u.strip() for u in batch_request.urls if u.strip()]
        httpx_client = request.app.state.httpx_client

        if not urls:
            raise HTTPException(status_code=400, detail="No URLs provided")

        if len(urls) > 10:
            raise HTTPException(status_code=400, detail="Maximum 10 URLs per request")

        # Validate all URLs first and collect platforms
        platforms = []
        for url in urls:
            if not is_supported_url(url):
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported URL: {url}"
                )
            platforms.append(identify_platform(url))

        # Look up cookies - if all URLs are from the same platform, use cookies
        cookies_file = None
        unique_platforms = set(platforms)
        if len(unique_platforms) == 1:
            cookies_file = get_cookie_file_for_platform(platforms[0], config.state_db)

        results = []
        download_results = await download_multiple_urls(urls, cookies_file=cookies_file)

        for url, download_result in zip(urls, download_results):
            platform = identify_platform(url)

            if not download_result.success:
                results.append(UploadResult(
                    filename=url,
                    status="error",
                    error=download_result.error,
                    platform=platform,
                ))
                continue

            try:
                with open(download_result.filepath, "rb") as f:
                    file_content = f.read()

                file_created_at = None
                if download_result.metadata:
                    timestamp = download_result.metadata.get("timestamp")
                    if timestamp:
                        file_created_at = datetime.fromtimestamp(timestamp).isoformat() + "Z"

                upload_result = await upload_to_immich(
                    file_content=file_content,
                    filename=download_result.filename,
                    content_type=download_result.content_type,
                    config=config,
                    httpx_client=httpx_client,
                    device_id=f"immich-drop-{platform}",
                    file_created_at=file_created_at,
                )
                upload_result.platform = platform

                # Add to album
                album_name = batch_request.album_name or getattr(config, 'album_name', None)
                if album_name and upload_result.asset_id and upload_result.status == "success":
                    await add_asset_to_album(upload_result.asset_id, album_name, config, httpx_client)

                results.append(upload_result)

            finally:
                background_tasks.add_task(cleanup_download, download_result)

        successful = sum(1 for r in results if r.status == "success" and not r.duplicate)
        duplicates = sum(1 for r in results if r.duplicate)
        failed = sum(1 for r in results if r.status == "error")

        return BatchUploadResponse(
            total=len(results),
            successful=successful,
            duplicates=duplicates,
            failed=failed,
            results=results,
        )

    @router.post("/upload/batch", response_model=BatchUploadResponse)
    async def upload_batch_files(
        request: Request,
        files: List[UploadFile] = File(...),
        album_name: Optional[str] = Form(None),
    ):
        """
        Batch upload files - designed for iOS Shortcuts

        POST multipart/form-data with one or more files
        """
        httpx_client = request.app.state.httpx_client

        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        if len(files) > 50:
            raise HTTPException(status_code=400, detail="Maximum 50 files per request")

        results = []

        for file in files:
            contents = await file.read()
            filename = file.filename or f"upload_{datetime.utcnow().timestamp()}"
            content_type = file.content_type or "application/octet-stream"

            upload_result = await upload_to_immich(
                file_content=contents,
                filename=filename,
                content_type=content_type,
                config=config,
                httpx_client=httpx_client,
                device_id="ios-shortcut",
            )

            # Add to album
            target_album = album_name or getattr(config, 'album_name', None)
            if target_album and upload_result.asset_id and upload_result.status == "success":
                await add_asset_to_album(upload_result.asset_id, target_album, config, httpx_client)

            results.append(upload_result)

        successful = sum(1 for r in results if r.status == "success" and not r.duplicate)
        duplicates = sum(1 for r in results if r.duplicate)
        failed = sum(1 for r in results if r.status == "error")

        return BatchUploadResponse(
            total=len(results),
            successful=successful,
            duplicates=duplicates,
            failed=failed,
            results=results,
        )

    @router.post("/upload/file", response_model=UploadResult)
    async def upload_single_file(
        request: Request,
        file: UploadFile = File(...),
        album_name: Optional[str] = Form(None),
    ):
        """
        Upload a single file - simpler endpoint for iOS Shortcuts
        """
        httpx_client = request.app.state.httpx_client
        contents = await file.read()
        filename = file.filename or f"upload_{datetime.utcnow().timestamp()}"
        content_type = file.content_type or "application/octet-stream"

        upload_result = await upload_to_immich(
            file_content=contents,
            filename=filename,
            content_type=content_type,
            config=config,
            httpx_client=httpx_client,
            device_id="ios-shortcut",
        )

        target_album = album_name or getattr(config, 'album_name', None)
        if target_album and upload_result.asset_id and upload_result.status == "success":
            await add_asset_to_album(upload_result.asset_id, target_album, config, httpx_client)

        return upload_result

    @router.post("/upload/base64", response_model=UploadResult)
    async def upload_base64_file(
        request: Request,
        upload_request: Base64UploadRequest,
    ):
        """
        Upload a base64-encoded file - most reliable for iOS Shortcuts

        JSON body:
        {
            "data": "base64-encoded-file-content",
            "filename": "photo.jpg" (optional),
            "album_name": "Album Name" (optional)
        }
        """
        httpx_client = request.app.state.httpx_client

        # Decode base64 data
        try:
            # Handle data URL format (e.g., "data:image/jpeg;base64,/9j/4AAQ...")
            data_str = upload_request.data
            if data_str.startswith("data:"):
                # Extract the base64 part after the comma
                header, data_str = data_str.split(",", 1)

            file_content = base64.b64decode(data_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 data: {str(e)}")

        # Detect file type from magic bytes
        detected_ext, detected_mime = detect_file_type(file_content)

        # Determine filename - use provided name or generate one
        base_filename = upload_request.filename or f"upload_{datetime.utcnow().timestamp()}"

        # If filename lacks extension or has wrong extension, use detected type
        _, existing_ext = os.path.splitext(base_filename)
        if detected_ext and (not existing_ext or existing_ext.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.avif', '.mp4', '.mov', '.bmp', '.tiff']):
            filename = base_filename + detected_ext
        else:
            filename = base_filename if existing_ext else base_filename + (detected_ext or '.jpg')

        # Use detected MIME type or fall back to guessing from filename
        if detected_mime:
            content_type = detected_mime
        else:
            content_type, _ = mimetypes.guess_type(filename)
            content_type = content_type or "application/octet-stream"

        upload_result = await upload_to_immich(
            file_content=file_content,
            filename=filename,
            content_type=content_type,
            config=config,
            httpx_client=httpx_client,
            device_id="ios-shortcut-base64",
        )

        target_album = upload_request.album_name or getattr(config, 'album_name', None)
        if target_album and upload_result.asset_id and upload_result.status == "success":
            await add_asset_to_album(upload_result.asset_id, target_album, config, httpx_client)

        return upload_result

    return router
