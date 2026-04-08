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
import logging
import mimetypes
import asyncio

logger = logging.getLogger("immich_drop.api_routes")

from .url_downloader import (
    download_from_url,
    download_from_url_multi,
    download_multiple_urls,
    cleanup_download,
    is_supported_url,
    identify_platform,
    is_direct_image_url,
    SUPPORTED_PATTERNS,
)
from .cookie_manager import get_cookie_file_for_platform
from .utils import detect_file_type
from .job_manager import create_job, get_job, update_job, cleanup_expired


router = APIRouter(prefix="/api", tags=["api"])


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
    total_uploaded: int = 0
    additional_results: List[UploadResult] = []


class BatchUploadResponse(BaseModel):
    total: int
    successful: int
    duplicates: int
    failed: int
    results: List[UploadResult]


class SupportedPlatformsResponse(BaseModel):
    platforms: List[str]
    examples: dict


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    done: str = "0"  # "0" = in progress, "1" = completed, "2" = failed (string for iOS Shortcuts compatibility)
    created_at: float
    result: Optional[dict] = None
    error: Optional[str] = None


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
                "facebook": "https://www.facebook.com/reel/123456789",
            }
        )

    @router.post("/upload/url", response_model=JobResponse)
    async def upload_from_url(
        url_request: UrlUploadRequest,
        request: Request,
    ):
        """
        Start async download from a supported URL.
        Returns a job ID immediately. Poll /api/upload/url/status/{job_id} for results.
        """
        url = url_request.url.strip()

        # Validate URL
        platform = identify_platform(url)
        direct_image = is_direct_image_url(url)
        if not platform and not direct_image:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported URL. Supported platforms: {', '.join(SUPPORTED_PATTERNS.keys())}. Direct image URLs are also accepted."
            )

        logger.info("URL upload request: platform=%s direct_image=%s url=%s", platform, direct_image, url)

        job = create_job(url, url_request.album_name)
        httpx_client = request.app.state.httpx_client

        asyncio.create_task(_process_url_job(job.id, url, url_request.album_name, platform, httpx_client))

        return JobResponse(job_id=job.id, status=job.status)

    async def _process_url_job(
        job_id: str,
        url: str,
        album_name: Optional[str],
        platform: Optional[str],
        httpx_client,
    ):
        """Background task: download media from URL and upload to Immich."""
        try:
            update_job(job_id, status="downloading")

            cookies_file = get_cookie_file_for_platform(platform, config.state_db) if platform else None
            download_results = await download_from_url_multi(url, cookies_file=cookies_file, settings=config)

            successful_downloads = [r for r in download_results if r.success]
            if not successful_downloads:
                first_error = download_results[0].error if download_results else "No media found"
                logger.error("Download failed for %s: %s", url, first_error)
                update_job(job_id, status="failed", error=first_error)
                return

            update_job(job_id, status="uploading")

            source_label = platform or "direct_image"
            primary_upload_result = None
            all_upload_results = []
            total_uploaded = 0

            try:
                for download_result in successful_downloads:
                    with open(download_result.filepath, "rb") as f:
                        file_content = f.read()

                    logger.info(
                        "Uploading to Immich: filename=%s content_type=%s size=%d bytes",
                        download_result.filename,
                        download_result.content_type,
                        len(file_content),
                    )

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
                        device_id=f"immich-drop-{source_label}",
                        file_created_at=file_created_at,
                    )
                    upload_result.platform = source_label

                    target_album = album_name or getattr(config, 'album_name', None)
                    if target_album and upload_result.asset_id and upload_result.status == "success":
                        await add_asset_to_album(upload_result.asset_id, target_album, config, httpx_client)

                    if upload_result.status == "success":
                        total_uploaded += 1

                    all_upload_results.append(upload_result)

                    if primary_upload_result is None:
                        primary_upload_result = upload_result

                if total_uploaded > 1:
                    logger.info(
                        "Gallery upload complete: %d/%d items uploaded for %s",
                        total_uploaded, len(successful_downloads), url,
                    )

                response = UrlUploadResponse(
                    success=primary_upload_result.status == "success",
                    result=primary_upload_result,
                    error=primary_upload_result.error,
                    total_uploaded=total_uploaded,
                    additional_results=all_upload_results[1:],
                )
                update_job(job_id, status="completed", result=response.model_dump())

            finally:
                for download_result in download_results:
                    cleanup_download(download_result)

        except Exception as e:
            logger.exception("Job %s failed: %s", job_id, e)
            update_job(job_id, status="failed", error=str(e))

    @router.get("/upload/url/status/{job_id}", response_model=JobStatusResponse)
    async def get_upload_status(job_id: str):
        """Poll for the status of an async URL upload job."""
        cleanup_expired()
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found or expired")
        resp = {
            "job_id": job.id,
            "status": job.status,
            "created_at": job.created_at,
        }
        if job.status == "completed" and job.result is not None:
            resp["completed"] = "yes"
            resp["result"] = job.result
        if job.status == "failed":
            resp["failed"] = "yes"
            resp["error"] = job.error or "Unknown error"
        return JSONResponse(resp)

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
            platforms.append(identify_platform(url))  # None for direct image URLs

        # Look up cookies - if all URLs are from the same platform, use cookies
        cookies_file = None
        unique_platforms = set(p for p in platforms if p is not None)
        if len(unique_platforms) == 1:
            cookies_file = get_cookie_file_for_platform(list(unique_platforms)[0], config.state_db)

        results = []
        download_results = await download_multiple_urls(urls, cookies_file=cookies_file, settings=config)

        for download_result in download_results:
            # Derive platform from the result's metadata or original URL
            post_url = (download_result.metadata or {}).get("post_url", "")
            platform = identify_platform(post_url) if post_url else None
            source_label = platform or (download_result.metadata or {}).get("source", "direct_image")

            if not download_result.success:
                results.append(UploadResult(
                    filename=download_result.filename or post_url or "unknown",
                    status="error",
                    error=download_result.error,
                    platform=source_label,
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
                    device_id=f"immich-drop-{source_label}",
                    file_created_at=file_created_at,
                )
                upload_result.platform = source_label

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
