"""
URL Downloader module for immich-drop
Downloads videos/images from TikTok, Instagram, Facebook, Reddit using yt-dlp
Also supports direct image URL downloads via httpx
"""
import os
import re
import tempfile
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple, List
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime
import subprocess
import json

import httpx

from .utils import detect_file_type

logger = logging.getLogger("immich_drop.url_downloader")


@dataclass
class DownloadResult:
    success: bool
    filepath: Optional[str] = None
    filename: Optional[str] = None
    content_type: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None


# Supported platforms and their URL patterns
SUPPORTED_PATTERNS = {
    'tiktok': [
        r'(?:https?://)?(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+',
        r'(?:https?://)?(?:vm|vt)\.tiktok\.com/[\w]+',
        r'(?:https?://)?(?:www\.)?tiktok\.com/t/[\w]+',
    ],
    'instagram': [
        r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|reels)/[\w-]+',
        r'(?:https?://)?(?:www\.)?instagram\.com/stories/[\w.-]+/\d+',
    ],
    'reddit': [
        r'(?:https?://)?(?:www\.|old\.)?reddit\.com/r/[\w]+/comments/[\w]+',
        r'(?:https?://)?(?:www\.)?reddit\.com/r/[\w]+/s/[\w]+',  # Share links
        r'(?:https?://)?(?:www\.)?redd\.it/[\w]+',
        r'(?:https?://)?v\.redd\.it/[\w]+',
        r'(?:https?://)?i\.redd\.it/[\w.]+',
        r'(?:https?://)?preview\.redd\.it/[\w.?&=%-]+',
        r'(?:https?://)?(?:i\.)?reddit\.com/[\w/]+',
    ],
    'youtube': [
        r'(?:https?://)?(?:www\.)?youtube\.com/(?:watch\?v=|shorts/)[\w-]+',
        r'(?:https?://)?youtu\.be/[\w-]+',
    ],
    'twitter': [
        r'(?:https?://)?(?:www\.)?(?:twitter|x)\.com/[\w]+/status/\d+',
    ],
    'facebook': [
        r'(?:https?://)?(?:www\.)?facebook\.com/reel/\d+',
        r'(?:https?://)?(?:www\.)?facebook\.com/[\w.]+/videos/\d+',
        r'(?:https?://)?(?:www\.)?facebook\.com/watch/?\?v=\d+',
        r'(?:https?://)?(?:www\.)?facebook\.com/share/v/[\w]+',
        r'(?:https?://)?(?:www\.)?facebook\.com/share/r/[\w]+',
        r'(?:https?://)?fb\.watch/[\w]+',
    ],
}


DIRECT_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.heic', '.bmp', '.tiff'}

DIRECT_IMAGE_DOMAINS = {'i.redd.it', 'i.imgur.com', 'pbs.twimg.com', 'preview.redd.it'}

MAX_DIRECT_IMAGE_SIZE = 100 * 1024 * 1024  # 100MB


def identify_platform(url: str) -> Optional[str]:
    """Identify which platform a URL belongs to"""
    for platform, patterns in SUPPORTED_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return platform
    return None


def is_direct_image_url(url: str) -> bool:
    """
    Check if a URL points directly to an image file.
    Matches by file extension in the URL path or by known image-hosting domains.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Check if domain is a known direct-image host
    hostname = (parsed.hostname or "").lower()
    if hostname in DIRECT_IMAGE_DOMAINS:
        return True

    # Check if URL path ends with an image extension
    path = parsed.path.lower()
    for ext in DIRECT_IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return True

    return False


def is_supported_url(url: str) -> bool:
    """Check if URL is from a supported platform or a direct image URL"""
    return identify_platform(url) is not None or is_direct_image_url(url)


async def download_direct_image(
    url: str,
    output_dir: Optional[str] = None,
) -> DownloadResult:
    """
    Download an image directly via httpx (no yt-dlp needed).

    Args:
        url: Direct URL to an image file
        output_dir: Directory to save the file (uses temp dir if not specified)

    Returns:
        DownloadResult with file info or error
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="immich_drop_")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            # HEAD request to check content type and size
            head_resp = await client.head(url, headers=headers)
            if head_resp.status_code >= 400:
                return DownloadResult(
                    success=False,
                    error=f"HEAD request failed with status {head_resp.status_code}",
                )

            content_length = head_resp.headers.get("content-length")
            if content_length and int(content_length) > MAX_DIRECT_IMAGE_SIZE:
                return DownloadResult(
                    success=False,
                    error=f"File too large ({int(content_length)} bytes, max {MAX_DIRECT_IMAGE_SIZE})",
                )

            # Download the image
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            data = resp.content
            if len(data) > MAX_DIRECT_IMAGE_SIZE:
                return DownloadResult(
                    success=False,
                    error=f"Downloaded file too large ({len(data)} bytes)",
                )

            # Determine file type from magic bytes first, then fall back to URL/headers
            detected_ext, detected_mime = detect_file_type(data)

            if detected_ext and detected_mime:
                ext = detected_ext
                content_type = detected_mime
            else:
                # Fall back to URL path extension
                parsed_path = urlparse(url).path
                ext = os.path.splitext(parsed_path)[1].lower()
                if not ext or ext not in DIRECT_IMAGE_EXTENSIONS:
                    # Fall back to Content-Type header
                    ct = resp.headers.get("content-type", "")
                    mime_to_ext = {
                        "image/jpeg": ".jpg",
                        "image/png": ".png",
                        "image/gif": ".gif",
                        "image/webp": ".webp",
                        "image/avif": ".avif",
                        "image/heic": ".heic",
                        "image/bmp": ".bmp",
                        "image/tiff": ".tiff",
                    }
                    ext = mime_to_ext.get(ct.split(";")[0].strip(), ".jpg")

                content_type_map = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.webp': 'image/webp',
                    '.avif': 'image/avif',
                    '.heic': 'image/heic',
                    '.bmp': 'image/bmp',
                    '.tiff': 'image/tiff',
                }
                content_type = content_type_map.get(ext, 'application/octet-stream')

            # Generate filename from URL hash
            url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]
            filename = f"direct_{url_hash}{ext}"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "wb") as f:
                f.write(data)

            logger.info(
                "Direct image downloaded: %s (size=%d bytes, type=%s)",
                filename, len(data), content_type,
            )

            return DownloadResult(
                success=True,
                filepath=filepath,
                filename=filename,
                content_type=content_type,
                metadata={"source": "direct_image", "url": url},
            )

    except httpx.HTTPStatusError as e:
        return DownloadResult(
            success=False,
            error=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}",
        )
    except Exception as e:
        logger.error("Direct image download failed for %s: %s", url, e)
        return DownloadResult(
            success=False,
            error=f"Download error: {str(e)}",
        )


async def download_from_url(
    url: str,
    output_dir: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> DownloadResult:
    """
    Download media from a supported URL using yt-dlp

    Args:
        url: The URL to download from
        output_dir: Directory to save the file (uses temp dir if not specified)
        cookies_file: Optional path to cookies.txt for authenticated downloads

    Returns:
        DownloadResult with file info or error
    """
    # Check for direct image URLs first (skip yt-dlp entirely)
    if is_direct_image_url(url):
        logger.info("Detected direct image URL: %s", url)
        return await download_direct_image(url, output_dir)

    platform = identify_platform(url)
    if not platform:
        return DownloadResult(
            success=False,
            error=f"Unsupported URL. Supported platforms: {', '.join(SUPPORTED_PATTERNS.keys())}"
        )

    # Create output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="immich_drop_")

    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")

    # Build yt-dlp command
    cmd = [
        "yt-dlp",
        "--no-playlist",  # Don't download playlists
        "--no-warnings",
        "--quiet",
        "--print-json",  # Output JSON metadata
        "-o", output_template,
        "--no-mtime",  # Don't use server mtime
    ]

    # Apply cookies for any platform if provided
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])

    # Platform-specific options
    if platform == 'tiktok':
        # Download without watermark when possible
        cmd.extend([
            "--format", "best",
        ])
    elif platform == 'instagram':
        cmd.extend([
            "--format", "best",
        ])
    elif platform == 'reddit':
        cmd.extend([
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--impersonate", "chrome",
        ])
    elif platform == 'youtube':
        cmd.extend([
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        ])
    elif platform == 'twitter':
        cmd.extend([
            "--format", "best",
        ])
    elif platform == 'facebook':
        cmd.extend([
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--impersonate", "chrome",
        ])

    cmd.append(url)

    logger.info("yt-dlp command: %s", " ".join(cmd))

    try:
        # Run yt-dlp
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if stderr:
            stderr_text = stderr.decode().strip()
            if stderr_text:
                logger.warning("yt-dlp stderr: %s", stderr_text)

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.error("yt-dlp failed (exit %d): %s", process.returncode, error_msg)
            # Clean up temp dir if we created it
            if output_dir and output_dir.startswith(tempfile.gettempdir()):
                import shutil
                shutil.rmtree(output_dir, ignore_errors=True)
            return DownloadResult(
                success=False,
                error=f"Download failed: {error_msg}"
            )

        # Parse JSON output for metadata
        metadata = {}
        if stdout:
            try:
                # yt-dlp outputs one JSON object per line
                for line in stdout.decode().strip().split('\n'):
                    if line:
                        metadata = json.loads(line)
                        break
            except json.JSONDecodeError:
                logger.warning("Failed to parse yt-dlp JSON output")

        if metadata:
            logger.info(
                "yt-dlp metadata: format=%s ext=%s resolution=%s filesize=%s",
                metadata.get("format"),
                metadata.get("ext"),
                metadata.get("resolution"),
                metadata.get("filesize") or metadata.get("filesize_approx"),
            )

        # Find the downloaded file
        downloaded_files = list(Path(output_dir).glob("*"))
        if not downloaded_files:
            logger.error("yt-dlp returned 0 but no file found in %s", output_dir)
            return DownloadResult(
                success=False,
                error="No file was downloaded"
            )

        filepath = str(downloaded_files[0])
        filename = downloaded_files[0].name
        file_size = downloaded_files[0].stat().st_size
        logger.info(
            "Downloaded file: %s (size=%d bytes, ext=%s)",
            filename, file_size, downloaded_files[0].suffix,
        )
        if file_size < 10000:
            logger.warning(
                "Downloaded file is very small (%d bytes) -- likely a thumbnail or error page",
                file_size,
            )

        # Determine content type
        ext = downloaded_files[0].suffix.lower()
        content_type_map = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.mkv': 'video/x-matroska',
            '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
        }
        content_type = content_type_map.get(ext, 'application/octet-stream')

        # Generate a better filename using metadata if available
        if metadata:
            uploader = metadata.get('uploader', metadata.get('channel', 'unknown'))
            title = metadata.get('title', metadata.get('description', ''))[:50]
            video_id = metadata.get('id', downloaded_files[0].stem)

            # Clean filename
            safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:30]
            safe_uploader = re.sub(r'[^\w\s-]', '', uploader).strip()[:20]

            if safe_title:
                new_filename = f"{platform}_{safe_uploader}_{safe_title}_{video_id}{ext}"
            else:
                new_filename = f"{platform}_{safe_uploader}_{video_id}{ext}"

            # Rename file
            new_filepath = os.path.join(output_dir, new_filename)
            os.rename(filepath, new_filepath)
            filepath = new_filepath
            filename = new_filename

        return DownloadResult(
            success=True,
            filepath=filepath,
            filename=filename,
            content_type=content_type,
            metadata=metadata,
        )

    except FileNotFoundError:
        return DownloadResult(
            success=False,
            error="yt-dlp is not installed. Install with: pip install yt-dlp"
        )
    except Exception as e:
        return DownloadResult(
            success=False,
            error=f"Download error: {str(e)}"
        )


async def download_multiple_urls(
    urls: List[str],
    output_dir: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> List[DownloadResult]:
    """Download multiple URLs concurrently"""
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="immich_drop_batch_")

    tasks = []
    for i, url in enumerate(urls):
        # Create subdirectory for each download to avoid conflicts
        sub_dir = os.path.join(output_dir, f"item_{i}")
        os.makedirs(sub_dir, exist_ok=True)
        tasks.append(download_from_url(url, sub_dir, cookies_file))

    return await asyncio.gather(*tasks)


def cleanup_download(result: DownloadResult):
    """Clean up downloaded file and its directory"""
    if result.filepath and os.path.exists(result.filepath):
        parent_dir = os.path.dirname(result.filepath)
        os.remove(result.filepath)
        # Remove parent directory if empty and in temp
        if parent_dir.startswith(tempfile.gettempdir()):
            try:
                os.rmdir(parent_dir)
            except OSError:
                pass  # Directory not empty or other error
