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

import html

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
            # HEAD request to pre-check size (non-fatal: some CDNs reject HEAD)
            try:
                head_resp = await client.head(url, headers=headers)
                if head_resp.status_code < 400:
                    content_length = head_resp.headers.get("content-length")
                    if content_length and int(content_length) > MAX_DIRECT_IMAGE_SIZE:
                        return DownloadResult(
                            success=False,
                            error=f"File too large ({int(content_length)} bytes, max {MAX_DIRECT_IMAGE_SIZE})",
                        )
                else:
                    logger.debug(
                        "HEAD request returned %d for %s, proceeding with GET",
                        head_resp.status_code, url,
                    )
            except httpx.HTTPError as e:
                logger.debug("HEAD request failed for %s: %s, proceeding with GET", url, e)

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


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def parse_netscape_cookies(cookies_file: str) -> Optional[str]:
    """
    Parse a Netscape-format cookie file and return a Cookie header string.

    Reads the file, skips comment and blank lines, parses tab-separated fields
    (domain, flag, path, secure, expiry, name, value) and returns a string
    like "name1=value1; name2=value2" suitable for an HTTP Cookie header.

    Returns None if the file doesn't exist, is empty, or contains no valid cookies.
    """
    if not cookies_file or not os.path.exists(cookies_file):
        return None

    pairs = []
    try:
        with open(cookies_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[5]
                    value = parts[6]
                    if name:
                        pairs.append(f"{name}={value}")
    except Exception as e:
        logger.warning("Failed to parse cookie file %s: %s", cookies_file, e)
        return None

    if not pairs:
        return None

    return "; ".join(pairs)


async def extract_reddit_image_urls(url: str) -> List[str]:
    """
    Extract image URLs from a Reddit post by fetching its JSON data.

    Handles:
    - Gallery posts (is_gallery=True): extracts all images from gallery_data/media_metadata
    - Single image posts (post_hint="image"): extracts the main image URL

    Returns list of image URLs, or empty list if the post is a video or extraction fails.
    """
    # Normalize URL: strip trailing slash, append .json
    clean_url = url.rstrip("/")
    # Remove query params for the JSON fetch
    json_url = clean_url.split("?")[0] + ".json"

    headers = {"User-Agent": BROWSER_USER_AGENT}

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(json_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "Reddit JSON fetch failed: status=%d url=%s", resp.status_code, json_url
                )
                return []

            data = resp.json()

        # Reddit .json returns a list of listing objects
        if not isinstance(data, list) or len(data) < 1:
            logger.warning("Reddit JSON unexpected structure for %s", url)
            return []

        post_data = data[0].get("data", {}).get("children", [{}])[0].get("data", {})

        if not post_data:
            logger.warning("Reddit JSON: no post data found for %s", url)
            return []

        # Skip video posts -- let yt-dlp handle those
        if post_data.get("is_video"):
            logger.info("Reddit post is a video, deferring to yt-dlp: %s", url)
            return []

        image_urls = []

        # Gallery posts
        if post_data.get("is_gallery"):
            gallery_items = post_data.get("gallery_data", {}).get("items", [])
            media_metadata = post_data.get("media_metadata", {})

            for item in gallery_items:
                media_id = item.get("media_id")
                if not media_id or media_id not in media_metadata:
                    continue

                meta = media_metadata[media_id]
                # Skip non-image media (e.g., gif -> mp4)
                mime_type = meta.get("m", "")
                if not mime_type.startswith("image/"):
                    continue

                # Prefer constructing direct i.redd.it URL (original, uncompressed)
                ext = mime_type.split("/")[-1]
                if ext == "jpeg":
                    ext = "jpg"
                direct_url = f"https://i.redd.it/{media_id}.{ext}"
                image_urls.append(direct_url)

            if image_urls:
                logger.info(
                    "Reddit gallery: extracted %d image URLs from %s",
                    len(image_urls), url,
                )
                return image_urls

            # Fallback: try preview URLs from media_metadata .s.u
            for item in gallery_items:
                media_id = item.get("media_id")
                if media_id and media_id in media_metadata:
                    meta = media_metadata[media_id]
                    preview_url = meta.get("s", {}).get("u")
                    if preview_url:
                        image_urls.append(html.unescape(preview_url))

            if image_urls:
                logger.info(
                    "Reddit gallery (preview fallback): extracted %d URLs from %s",
                    len(image_urls), url,
                )
            return image_urls

        # Single image posts
        post_hint = post_data.get("post_hint", "")
        if post_hint == "image" or post_data.get("domain", "") in ("i.redd.it", "i.imgur.com"):
            # Primary: url_overridden_by_dest (usually i.redd.it direct link)
            override_url = post_data.get("url_overridden_by_dest")
            if override_url:
                image_urls.append(html.unescape(override_url))
            else:
                # Fallback: preview images
                previews = post_data.get("preview", {}).get("images", [])
                if previews:
                    source_url = previews[0].get("source", {}).get("url")
                    if source_url:
                        image_urls.append(html.unescape(source_url))

            if image_urls:
                logger.info("Reddit single image: extracted URL from %s", url)
            return image_urls

        logger.info("Reddit post has no extractable images (hint=%s), deferring to yt-dlp", post_hint)
        return []

    except Exception as e:
        logger.error("Reddit image extraction failed for %s: %s", url, e)
        return []


async def extract_instagram_media_urls(
    url: str,
    cookies_file: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    Extract media URLs from an Instagram post using the REST API endpoint.

    Handles:
    - Carousel posts: extracts all images and videos
    - Single posts: extracts the image or video

    Args:
        url: Instagram post URL
        cookies_file: Optional path to Netscape-format cookie file for authenticated requests

    Returns list of (url, media_type) tuples where media_type is "image" or "video".
    Returns empty list on failure (caller should fall through to yt-dlp).
    """
    # Extract shortcode from URL
    match = re.search(r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)', url)
    if not match:
        logger.warning("Instagram: could not extract shortcode from %s", url)
        return []

    shortcode = match.group(1)
    api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"

    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
    }

    # Add cookies from the Netscape cookie file if available
    cookie_header = parse_netscape_cookies(cookies_file)
    if cookie_header:
        headers["Cookie"] = cookie_header
        logger.debug("Instagram API request: using cookies from %s", cookies_file)
    else:
        logger.debug("Instagram API request: no cookies available (API may return 404)")

    def _best_image_url(candidates: list) -> Optional[str]:
        """Pick highest resolution image from candidates list."""
        if not candidates:
            return None
        best = max(candidates, key=lambda c: c.get("width", 0) * c.get("height", 0))
        return best.get("url")

    def _best_video_url(versions: list) -> Optional[str]:
        """Pick highest resolution video from versions list."""
        if not versions:
            return None
        best = max(versions, key=lambda v: v.get("width", 0) * v.get("height", 0))
        return best.get("url")

    def _extract_media_from_item(item: dict) -> Optional[Tuple[str, str]]:
        """Extract best media URL from a single Instagram media item."""
        # Check for video first
        video_versions = item.get("video_versions")
        if video_versions:
            video_url = _best_video_url(video_versions)
            if video_url:
                return (video_url, "video")

        # Fall back to image
        candidates = item.get("image_versions2", {}).get("candidates", [])
        image_url = _best_image_url(candidates)
        if image_url:
            return (image_url, "image")

        return None

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(api_url, headers=headers)

            if resp.status_code != 200:
                logger.warning(
                    "Instagram API failed: status=%d, trying fallback chain",
                    resp.status_code,
                )
                return await _instagram_fallback_chain(url, client, cookies_file)

            data = resp.json()

        items = data.get("items", [])
        if not items:
            logger.warning("Instagram API returned no items for %s", url)
            return await _instagram_fallback_chain(url, cookies_file=cookies_file)

        post = items[0]
        media_urls = []

        # Carousel posts
        carousel_media = post.get("carousel_media")
        if carousel_media:
            for media_item in carousel_media:
                result = _extract_media_from_item(media_item)
                if result:
                    media_urls.append(result)
            logger.info(
                "Instagram carousel: extracted %d media items from %s",
                len(media_urls), url,
            )
            return media_urls

        # Single post
        result = _extract_media_from_item(post)
        if result:
            media_urls.append(result)
            logger.info("Instagram single post: extracted %s from %s", result[1], url)
            return media_urls

        logger.warning("Instagram: no media found in API response for %s", url)
        return await _instagram_fallback_chain(url, cookies_file=cookies_file)

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Instagram API parse error for %s: %s, trying fallback chain", url, e)
        return await _instagram_fallback_chain(url, cookies_file=cookies_file)
    except Exception as e:
        logger.error("Instagram media extraction failed for %s: %s", url, e)
        return []


async def _instagram_oembed_fallback(url: str) -> List[Tuple[str, str]]:
    """
    Fallback: use Instagram's oEmbed endpoint to get a thumbnail URL.
    Works without authentication. Returns a 640x800 CDN image link.
    """
    oembed_url = f"https://www.instagram.com/api/v1/oembed/?url={url}"
    headers = {"User-Agent": BROWSER_USER_AGENT}

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(oembed_url, headers=headers)

            if resp.status_code != 200:
                logger.warning(
                    "Instagram oEmbed failed: status=%d for %s", resp.status_code, url,
                )
                return []

            data = resp.json()
            thumbnail_url = data.get("thumbnail_url")
            if thumbnail_url:
                logger.info("Instagram oEmbed fallback: extracted thumbnail from %s", url)
                return [(thumbnail_url, "image")]

            logger.warning("Instagram oEmbed: no thumbnail_url in response for %s", url)
            return []

    except Exception as e:
        logger.error("Instagram oEmbed fallback failed for %s: %s", url, e)
        return []


async def _instagram_fallback_chain(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
    cookies_file: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    Try Instagram fallback methods in order:
    1. oEmbed endpoint (no auth needed, most reliable for images)
    2. og:image HTML scraping (last resort)
    """
    result = await _instagram_oembed_fallback(url)
    if result:
        return result
    return await _instagram_og_image_fallback(url, client, cookies_file)


async def _instagram_og_image_fallback(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
    cookies_file: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    Fallback: scrape og:image meta tag from Instagram page HTML.
    Returns at most one image (the cover/preview image).
    """
    headers = {"User-Agent": BROWSER_USER_AGENT}

    # Add cookies if available (may help with login-walled pages)
    cookie_header = parse_netscape_cookies(cookies_file)
    if cookie_header:
        headers["Cookie"] = cookie_header

    try:
        if client is None:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as new_client:
                resp = await new_client.get(url, headers=headers)
                page_html = resp.text
        else:
            resp = await client.get(url, headers=headers)
            page_html = resp.text

        # Extract og:image content -- handle both attribute orderings:
        #   <meta property="og:image" content="...">
        #   <meta content="..." property="og:image">
        match = re.search(
            r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
            page_html,
        )
        if not match:
            match = re.search(
                r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                page_html,
            )
        if match:
            og_url = html.unescape(match.group(1))
            logger.info("Instagram og:image fallback: extracted URL from %s", url)
            return [(og_url, "image")]

        logger.warning("Instagram og:image fallback: no og:image found for %s", url)
        return []

    except Exception as e:
        logger.error("Instagram og:image fallback failed for %s: %s", url, e)
        return []


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


async def download_platform_media(
    url: str,
    platform: str,
    output_dir: str,
    cookies_file: Optional[str] = None,
) -> Optional[List[DownloadResult]]:
    """
    Try platform-specific media extraction (bypasses yt-dlp).

    Returns list of DownloadResult on success, or None if extraction fails
    (signaling the caller to fall through to yt-dlp).
    """
    if platform == "reddit":
        image_urls = await extract_reddit_image_urls(url)
        if not image_urls:
            return None

        results = []
        for img_url in image_urls:
            result = await download_direct_image(img_url, output_dir)
            if result.success:
                result.metadata = result.metadata or {}
                result.metadata["source"] = "reddit_extract"
                result.metadata["post_url"] = url
                results.append(result)
            else:
                logger.warning("Reddit image download failed for %s: %s", img_url, result.error)

        return results if results else None

    elif platform == "instagram":
        media_items = await extract_instagram_media_urls(url, cookies_file)
        if not media_items:
            return None

        results = []
        for media_url, media_type in media_items:
            result = await download_direct_image(media_url, output_dir)
            if result.success:
                result.metadata = result.metadata or {}
                result.metadata["source"] = "instagram_extract"
                result.metadata["post_url"] = url
                result.metadata["media_type"] = media_type
                results.append(result)
            else:
                logger.warning(
                    "Instagram %s download failed for %s: %s",
                    media_type, media_url, result.error,
                )

        return results if results else None

    return None


async def download_from_url_multi(
    url: str,
    output_dir: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> List[DownloadResult]:
    """
    Download media from a URL, returning multiple results for galleries/carousels.

    For Reddit/Instagram: tries platform-specific extraction first (supports
    multiple images), falls back to yt-dlp.
    For all other platforms: delegates to download_from_url().
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="immich_drop_")

    platform = identify_platform(url)

    if platform in ("reddit", "instagram"):
        media_results = await download_platform_media(url, platform, output_dir, cookies_file)
        if media_results:
            return media_results
        logger.info(
            "Platform extraction returned no results for %s, falling back to yt-dlp",
            url,
        )

    # Fall through to yt-dlp (or direct image handler)
    result = await download_from_url(url, output_dir, cookies_file)
    return [result]


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
