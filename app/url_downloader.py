"""
URL Downloader module for immich-drop
Downloads videos/images from TikTok, Instagram, Reddit using yt-dlp
"""
import os
import re
import tempfile
import asyncio
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime
import subprocess
import json


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
        r'(?:https?://)?(?:www\.)?redd\.it/[\w]+',
        r'(?:https?://)?v\.redd\.it/[\w]+',
        r'(?:https?://)?(?:i\.)?reddit\.com/[\w/]+',
    ],
    'youtube': [
        r'(?:https?://)?(?:www\.)?youtube\.com/(?:watch\?v=|shorts/)[\w-]+',
        r'(?:https?://)?youtu\.be/[\w-]+',
    ],
    'twitter': [
        r'(?:https?://)?(?:www\.)?(?:twitter|x)\.com/[\w]+/status/\d+',
    ],
}


def identify_platform(url: str) -> Optional[str]:
    """Identify which platform a URL belongs to"""
    for platform, patterns in SUPPORTED_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return platform
    return None


def is_supported_url(url: str) -> bool:
    """Check if URL is from a supported platform"""
    return identify_platform(url) is not None


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
        # Instagram often requires cookies for stories
        if cookies_file and os.path.exists(cookies_file):
            cmd.extend(["--cookies", cookies_file])
    elif platform == 'reddit':
        cmd.extend([
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        ])
    elif platform == 'youtube':
        cmd.extend([
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        ])
    elif platform == 'twitter':
        cmd.extend([
            "--format", "best",
        ])

    cmd.append(url)

    try:
        # Run yt-dlp
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
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
                pass

        # Find the downloaded file
        downloaded_files = list(Path(output_dir).glob("*"))
        if not downloaded_files:
            return DownloadResult(
                success=False,
                error="No file was downloaded"
            )

        filepath = str(downloaded_files[0])
        filename = downloaded_files[0].name

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
