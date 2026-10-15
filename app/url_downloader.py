"""
URL Downloader module for immich-drop
Downloads videos/images from supported platforms using gallery-dl and yt-dlp.
Also supports direct image URL downloads via httpx.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import asyncio
import hashlib
import ipaddress
import logging
import signal
import socket
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING
from urllib.parse import urlparse, parse_qs, unquote
from dataclasses import dataclass
import json

import httpx

from .db import get_app_settings
from .utils import detect_file_type

if TYPE_CHECKING:
    from .config import Settings

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
    'flickr': [
        r'(?:https?://)?(?:www\.)?flickr\.com/photos/[\w@]+/\d+',
    ],
    'tumblr': [
        r'(?:https?://)?[\w-]+\.tumblr\.com/post/\d+',
    ],
    'imgur': [
        r'(?:https?://)?(?:www\.)?imgur\.com/(?:a|gallery)/[\w]+',
        r'(?:https?://)?(?:www\.)?imgur\.com/[\w]+',
    ],
    'artstation': [
        r'(?:https?://)?(?:www\.)?artstation\.com/artwork/[\w]+',
    ],
    'deviantart': [
        r'(?:https?://)?(?:www\.)?deviantart\.com/[\w-]+/art/[\w-]+',
    ],
    'pixiv': [
        r'(?:https?://)?(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+',
    ],
    'danbooru': [
        r'(?:https?://)?danbooru\.donmai\.us/posts/\d+',
    ],
    'bluesky': [
        r'(?:https?://)?bsky\.app/profile/[\w.:]+/post/[\w]+',
    ],
    'pinterest': [
        r'(?:https?://)?(?:www\.)?pinterest\.com/pin/[\d]+',
        r'(?:https?://)?pin\.it/[\w]+',
    ],
}

# Platforms where gallery-dl excels (image-focused extraction)
GALLERY_DL_PLATFORMS = {
    "reddit", "instagram", "twitter", "flickr", "tumblr",
    "imgur", "artstation", "deviantart", "pixiv", "danbooru",
    "bluesky", "pinterest",
}

# Platforms where yt-dlp is the better tool (video-focused extraction)
YTDLP_PLATFORMS = {"youtube", "tiktok", "facebook"}


DIRECT_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif', '.heic', '.bmp', '.tiff'}

DIRECT_IMAGE_DOMAINS = {'i.redd.it', 'i.imgur.com', 'pbs.twimg.com', 'preview.redd.it'}

MAX_DIRECT_IMAGE_SIZE = 100 * 1024 * 1024  # 100MB

# Hostnames that route into the Reddit-specific extraction branch (share-link
# resolution and /media wrapper unwrapping). Exact-match dispatch only -- this
# is NOT an access gate, just feature dispatch. URLs that don't match still
# flow through to yt-dlp / gallery-dl / direct extraction like any other URL.
REDDIT_HOSTS = {
    "reddit.com", "www.reddit.com",
    "old.reddit.com", "np.reddit.com",
    "i.redd.it", "v.redd.it", "redd.it",
}


REDDIT_EMBED_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
REDDIT_MEDIA_HOSTS = {"i.redd.it", "preview.redd.it", "packaged-media.redd.it", "v.redd.it"}
REDDIT_EMBED_MAX_VIDEO = 500 * 1024 * 1024  # 500MB
REDDIT_EMBED_MAX_IMAGE = 100 * 1024 * 1024  # 100MB


def _is_reddit_host(hostname: Optional[str]) -> bool:
    return bool(hostname) and hostname.lower() in REDDIT_HOSTS


# Extensions allowed when composing the on-disk filename for a direct-image
# download. Anything outside this set is clamped to .jpg before joining the
# path. Derived from DIRECT_IMAGE_EXTENSIONS plus video extensions yt-dlp may
# legitimately produce.
SAFE_DIRECT_EXTS = DIRECT_IMAGE_EXTENSIONS | {'.mp4', '.mov', '.webm', '.mkv'}


def _is_private_ip(addr: str) -> bool:
    """Check if an IP address is private, loopback, link-local, or otherwise reserved."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # Unparseable -> treat as unsafe
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _validate_url_target(url: str) -> Optional[str]:
    """
    Validate that a URL does not target private/internal networks.
    Resolves the hostname to an IP and checks against blocked ranges.

    Returns an error message if the URL is unsafe, or None if it is safe.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"Blocked URL scheme: {scheme}"

    try:
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"Cannot resolve hostname: {hostname}"

    for family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            return f"Blocked request to private/reserved address: {hostname} -> {ip_str}"

    return None


def _ensure_public_url(url: str) -> str:
    """Raise ValueError if url targets a private/reserved network. Returns
    the url unchanged on success. Use this immediately before any outbound
    HTTP fetch so the raise pattern is recognized as a barrier guard.
    """
    err = _validate_url_target(url)
    if err is not None:
        raise ValueError(err)
    return url


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

    # SSRF protection: validate the URL target is not a private/internal address
    try:
        url = _ensure_public_url(url)
    except ValueError as ssrf_err:
        logger.warning("Direct image download blocked (SSRF): %s -- %s", url, ssrf_err)
        return DownloadResult(success=False, error=f"URL blocked: {ssrf_err}")

    headers = {"User-Agent": BROWSER_USER_AGENT}

    async def _validate_redirect(response):
        """Event hook: validate each redirect target against SSRF blocklist."""
        if response.is_redirect:
            location = response.headers.get("location", "")
            if location:
                redirect_err = _validate_url_target(location)
                if redirect_err:
                    logger.warning(
                        "Redirect blocked (SSRF): %s -> %s -- %s",
                        response.url, location, redirect_err,
                    )
                    raise httpx.TooManyRedirects(
                        f"Redirect blocked: {redirect_err}",
                        request=response.request,
                    )

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=60.0,
            event_hooks={"response": [_validate_redirect]},
        ) as client:
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
                    ct = resp.headers.get("content-type", "").split(";")[0].strip()
                    # Reverse lookup: MIME -> extension (prefer shorter ext for dupes like .jpg/.jpeg)
                    mime_to_ext = {}
                    for k, v in CONTENT_TYPE_MAP.items():
                        if v not in mime_to_ext or len(k) < len(mime_to_ext[v]):
                            mime_to_ext[v] = k
                    ext = mime_to_ext.get(ct, ".jpg")

                content_type = CONTENT_TYPE_MAP.get(ext, 'application/octet-stream')

            # Clamp ext to the safe allowlist before composing a filename.
            # This forecloses any path-traversal dataflow from URL/Content-Type.
            if ext.lower() not in SAFE_DIRECT_EXTS:
                ext = ".jpg"

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

# Default gallery-dl subprocess timeout (seconds); overridden by settings
_DEFAULT_GALLERY_DL_TIMEOUT = 300

# Content type map shared across download methods
CONTENT_TYPE_MAP = {
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
    '.avif': 'image/avif',
    '.heic': 'image/heic',
    '.bmp': 'image/bmp',
    '.tiff': 'image/tiff',
}


REDDIT_SETTING_KEYS = ("reddit_client_id", "reddit_refresh_token", "reddit_user_agent")


def resolve_reddit_credentials(settings: Settings) -> Optional[dict]:
    """Reddit OAuth options for gallery-dl: admin menu values first, then env."""
    stored = get_app_settings(settings.state_db, list(REDDIT_SETTING_KEYS))
    if stored.get("reddit_client_id"):
        client_id = stored["reddit_client_id"]
        token = stored.get("reddit_refresh_token", "")
        agent = stored.get("reddit_user_agent", "")
        source = "menu"
    elif settings.gallery_dl_reddit_client_id:
        client_id = settings.gallery_dl_reddit_client_id
        token = settings.gallery_dl_reddit_refresh_token
        agent = settings.gallery_dl_reddit_user_agent
        source = "env"
    else:
        return None
    creds = {"client-id": client_id}
    if token:
        creds["refresh-token"] = token
    if agent:
        creds["user-agent-oauth"] = agent
    creds["source"] = source
    return creds


async def extract_via_gallery_dl(
    url: str,
    output_dir: str,
    cookies_file: Optional[str] = None,
    platform: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> Optional[List[DownloadResult]]:
    """
    Extract and download media using gallery-dl as a subprocess.

    Returns list of DownloadResult on success, or None to signal that the
    caller should fall through to yt-dlp.
    """
    cmd = [
        "gallery-dl",
        "--no-mtime",
        "--write-metadata",
        "-d", output_dir,
        "--filename", "{filename}.{extension}",
    ]

    # Randomized delays to avoid rate limiting on all platforms
    if settings:
        if settings.gallery_dl_sleep_request:
            cmd.extend(["--sleep-request", settings.gallery_dl_sleep_request])
        if settings.gallery_dl_sleep:
            cmd.extend(["--sleep", settings.gallery_dl_sleep])

    config_path = None
    if platform == "reddit" and settings:
        creds = resolve_reddit_credentials(settings)
        if creds:
            # Config file keeps the token out of the process list
            config_path = os.path.join(output_dir, "gallery-dl.json")
            fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"extractor": {"reddit": {k: v for k, v in creds.items() if k != "source"}}}, f)
            cmd.extend(["-c", config_path])
            logger.info("Reddit OAuth credentials from %s", creds["source"])

    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])

    cmd.append(url)

    logger.info("gallery-dl command: %s", " ".join(cmd))

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        timeout = settings.gallery_dl_timeout if settings else _DEFAULT_GALLERY_DL_TIMEOUT
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # Kill the entire process group to clean up any child processes
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                process.kill()
            await process.communicate()
            logger.warning("gallery-dl timed out after %ds for %s", timeout, url)
            return None

        if stderr:
            stderr_text = stderr.decode().strip()
            if stderr_text:
                logger.debug("gallery-dl stderr: %s", stderr_text)

        if process.returncode != 0:
            logger.info(
                "gallery-dl failed (exit %d) for %s, falling back to yt-dlp",
                process.returncode, url,
            )
            return None

        # Collect downloaded files (skip .json sidecar metadata files)
        downloaded = [
            p for p in Path(output_dir).rglob("*")
            if p.is_file() and p.suffix != ".json"
        ]

        if not downloaded:
            logger.info("gallery-dl produced no files for %s", url)
            return None

        results = []
        for filepath in downloaded:
            # Read companion .json metadata sidecar if present
            metadata = {"source": "gallery_dl", "post_url": url}
            sidecar = filepath.with_suffix(filepath.suffix + ".json")
            if sidecar.exists():
                try:
                    with open(sidecar, "r") as f:
                        sidecar_data = json.load(f)
                    metadata.update({
                        k: sidecar_data[k]
                        for k in ("category", "subcategory", "filename", "extension",
                                  "date", "description", "title", "author", "username")
                        if k in sidecar_data
                    })
                except (json.JSONDecodeError, OSError) as e:
                    logger.debug("Could not read gallery-dl sidecar %s: %s", sidecar, e)

            # Determine content type from magic bytes first, then extension
            with open(filepath, "rb") as f:
                header_bytes = f.read(12)
            detected_ext, detected_mime = detect_file_type(header_bytes)
            if detected_mime:
                content_type = detected_mime
            else:
                content_type = CONTENT_TYPE_MAP.get(
                    filepath.suffix.lower(), "application/octet-stream"
                )

            results.append(DownloadResult(
                success=True,
                filepath=str(filepath),
                filename=filepath.name,
                content_type=content_type,
                metadata=metadata,
            ))

        logger.info(
            "gallery-dl extracted %d file(s) from %s", len(results), url,
        )
        return results

    except FileNotFoundError:
        logger.warning("gallery-dl is not installed, falling back to yt-dlp")
        return None
    except Exception as e:
        logger.error("gallery-dl error for %s: %s", url, e)
        return None
    finally:
        if config_path:
            try:
                os.remove(config_path)
            except OSError:
                pass


async def download_from_url(
    url: str,
    output_dir: Optional[str] = None,
    cookies_file: Optional[str] = None,
) -> DownloadResult:
    """
    Download media from a URL using yt-dlp (fallback path when gallery-dl
    does not handle the URL or fails). Called by download_from_url_multi().
    """
    platform = identify_platform(url)

    # Create output directory
    owned_output_dir = output_dir is None
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
        # Run yt-dlp (longer timeout than gallery-dl since video downloads are slower)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300,
            )
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                process.kill()
            await process.communicate()
            logger.error("yt-dlp timed out after 300s for %s", url)
            return DownloadResult(success=False, error="Download timed out")

        if stderr:
            stderr_text = stderr.decode().strip()
            if stderr_text:
                logger.warning("yt-dlp stderr: %s", stderr_text)

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.error("yt-dlp failed (exit %d): %s", process.returncode, error_msg)
            # Only clean up the temp dir if we created it ourselves; callers
            # that passed their own output_dir may still need it (e.g. for the
            # reddit media?url= fallback in download_from_url_multi).
            if owned_output_dir and output_dir.startswith(tempfile.gettempdir()):
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
        content_type = CONTENT_TYPE_MAP.get(ext, 'application/octet-stream')

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


def _reddit_media_host_ok(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in REDDIT_MEDIA_HOSTS


def parse_reddit_embed(html_text: str) -> list[dict]:
    """Extract media items from a Reddit embed page (pure, no I/O)."""
    import html as html_lib

    # Video post: packaged MP4 permutations (with audio), pick the tallest
    m = re.search(r'packaged-media-json="([^"]*)"', html_text)
    if m:
        try:
            data = json.loads(html_lib.unescape(m.group(1)))
            perms = (data.get("playbackMp4s") or {}).get("permutations") or []
            best_url, best_h = None, -1
            for perm in perms:
                src = (perm or {}).get("source") or {}
                u = src.get("url")
                h = (src.get("dimensions") or {}).get("height") or 0
                if u and _reddit_media_host_ok(u) and h > best_h:
                    best_url, best_h = u, h
            if best_url:
                segs = [x for x in urlparse(best_url).path.split("/") if x]
                if segs and re.fullmatch(r"[A-Za-z0-9_-]+", segs[0]):
                    return [{"url": best_url, "kind": "video", "filename": f"{segs[0]}.mp4"}]
        except (ValueError, AttributeError, TypeError):
            pass

    # Video post without MP4s: HLS/DASH playlist handled by yt-dlp
    for pm in re.finditer(r'<shreddit-player(?:-2)?\b[^>]*?\ssrc="([^"]+)"', html_text):
        u = html_lib.unescape(pm.group(1))
        pu = urlparse(u)
        if (pu.hostname or "").lower() == "v.redd.it" and pu.path.endswith((".m3u8", ".mpd")):
            segs = [x for x in pu.path.split("/") if x]
            if segs and re.fullmatch(r"[A-Za-z0-9_-]+", segs[0]):
                return [{"url": u, "kind": "video", "filename": f"{segs[0]}.mp4", "hls": True}]

    items: list[dict] = []
    seen: set = set()

    def _add(u: str):
        if u in seen or not _reddit_media_host_ok(u):
            return
        seen.add(u)
        items.append({"url": u, "kind": "image", "filename": os.path.basename(urlparse(u).path)})

    if "<gallery-carousel" in html_text:
        pages = []
        for li in re.finditer(r'<li\b[^>]*\bslot="page-(\d+)"[^>]*>(.*?)</li>', html_text, re.S):
            sm = re.search(r'\bsrc="([^"]+)"', li.group(2))
            if sm:
                pages.append((int(li.group(1)), html_lib.unescape(sm.group(1))))
        for _, u in sorted(pages, key=lambda x: x[0]):
            pu = urlparse(u)
            host = (pu.hostname or "").lower()
            if host == "preview.redd.it":
                fm = re.search(r"-v0-([A-Za-z0-9_-]+)\.(jpe?g|png|gif|webp)$", pu.path, re.I)
                if not fm:
                    continue
                u = f"https://i.redd.it/{fm.group(1)}.{fm.group(2).lower()}"
            elif host != "i.redd.it":
                continue
            _add(u)
        return items

    text = html_lib.unescape(html_text)
    for um in re.finditer(r"https://i\.redd\.it/[A-Za-z0-9_-]+\.(?:jpe?g|png|gif|webp)", text, re.I):
        _add(um.group(0))
    return items


async def extract_via_reddit_embed(url: str, output_dir: str) -> Optional[List[DownloadResult]]:
    """Fetch Reddit media via embed.reddit.com and the media CDNs. Never raises."""
    try:
        m = re.search(r"reddit\.com/(r|user|u)/([A-Za-z0-9_.-]+)/comments/([a-z0-9]+)", url)
        if not m:
            return None
        kind = "user" if m.group(1) == "u" else m.group(1)
        embed_url = f"https://embed.reddit.com/{kind}/{m.group(2)}/comments/{m.group(3)}/?embed=true"
        page_headers = {
            "User-Agent": REDDIT_EMBED_UA,
            "Accept": "text/html,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=page_headers) as client:
                resp = await client.get(embed_url)
        except Exception as e:
            logger.info("Reddit embed fetch failed for %s: %s", url, e)
            return None
        if resp.status_code != 200 or "blocked by network security" in resp.text:
            logger.info("Reddit embed page unavailable for %s (HTTP %d)", url, resp.status_code)
            return None

        items = parse_reddit_embed(resp.text)
        if not items:
            logger.info("Reddit embed page has no media for %s", url)
            return None

        os.makedirs(output_dir, exist_ok=True)
        results: List[DownloadResult] = []
        for item in items:
            try:
                if item.get("hls"):
                    res = await download_from_url(item["url"], output_dir)
                    if res.success:
                        results.append(res)
                    else:
                        logger.info("Reddit embed: HLS download failed: %s", res.error)
                    continue
                res = await _download_reddit_embed_file(item, url, output_dir)
                if res:
                    results.append(res)
            except Exception as e:
                logger.info("Reddit embed: item failed (%s): %s", item.get("filename"), e)
        return results or None
    except Exception as e:
        logger.info("Reddit embed extraction error for %s: %s", url, e)
        return None


async def _download_reddit_embed_file(item: dict, post_url: str, output_dir: str) -> Optional[DownloadResult]:
    limit = REDDIT_EMBED_MAX_VIDEO if item["kind"] == "video" else REDDIT_EMBED_MAX_IMAGE
    filename = os.path.basename(item["filename"])
    filepath = os.path.join(output_dir, filename)

    async def _check_redirect(response):
        if response.is_redirect:
            err = _validate_url_target(response.headers.get("location", ""))
            if err:
                raise httpx.TooManyRedirects(f"Redirect blocked: {err}", request=response.request)

    size = 0
    head = b""
    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=True, headers={"User-Agent": REDDIT_EMBED_UA},
            event_hooks={"response": [_check_redirect]},
        ) as client:
            async with client.stream("GET", item["url"]) as resp:
                if resp.status_code != 200:
                    logger.info("Reddit embed: HTTP %d for %s", resp.status_code, item["url"])
                    return None
                with open(filepath, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        if not head:
                            head = chunk[:64]
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f"file exceeds {limit} bytes")
                        f.write(chunk)
    except Exception as e:
        logger.info("Reddit embed: download failed for %s: %s", item["url"], e)
        if os.path.exists(filepath):
            os.remove(filepath)
        return None

    ext = os.path.splitext(filename)[1].lower()
    detected_ext, detected_mime = detect_file_type(head)
    content_type = detected_mime or CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
    logger.info("Reddit embed: downloaded %s (%d bytes)", filename, size)
    return DownloadResult(
        success=True,
        filepath=filepath,
        filename=filename,
        content_type=content_type,
        metadata={"source": "reddit_embed", "post_url": post_url},
    )


async def download_multiple_urls(
    urls: List[str],
    output_dir: Optional[str] = None,
    cookies_file: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> List[DownloadResult]:
    """Download multiple URLs with concurrency limited by semaphore."""
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="immich_drop_batch_")

    concurrency = max(1, settings.download_concurrency if settings else 1)
    sem = asyncio.Semaphore(concurrency)

    async def _download_with_sem(url: str, sub_dir: str) -> List[DownloadResult]:
        async with sem:
            return await download_from_url_multi(url, sub_dir, cookies_file, settings=settings)

    tasks = []
    for i, url in enumerate(urls):
        sub_dir = os.path.join(output_dir, f"item_{i}")
        os.makedirs(sub_dir, exist_ok=True)
        tasks.append(_download_with_sem(url, sub_dir))

    nested_results = await asyncio.gather(*tasks)
    # Flatten: download_from_url_multi returns List[DownloadResult] per URL
    return [r for sublist in nested_results for r in sublist]


async def download_from_url_multi(
    url: str,
    output_dir: Optional[str] = None,
    cookies_file: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> List[DownloadResult]:
    """
    Download media from a URL, returning multiple results for galleries/carousels.

    Pipeline order:
    1. Direct image URLs -> download_direct_image() (fast path, SSRF-protected)
    2. gallery-dl platforms -> extract_via_gallery_dl() (image-focused extraction)
    3. yt-dlp fallback -> download_from_url() (video-focused extraction)
       Blocked for Instagram by default to avoid double-scraper detection.
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="immich_drop_")

    # Resolve Reddit share links and media redirects to actual URLs
    try:
        parsed = urlparse(url)
        if _is_reddit_host(parsed.hostname):
            # Share links (/r/.../s/...) redirect to the actual post or media URL
            if "/s/" in parsed.path:
                # SSRF gate: resolve the host inline and reject any non-public
                # target. Inline (rather than via _ensure_public_url) so the
                # ipaddress.ip_address barrier-guard pattern is visible to
                # static analyzers at the HEAD call site.
                safe_url = None
                try:
                    if (parsed.scheme or "").lower() in ("http", "https") and parsed.hostname:
                        addrs = socket.getaddrinfo(
                            parsed.hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM,
                        )
                        if all(
                            not ipaddress.ip_address(sa[0]).is_private
                            and not ipaddress.ip_address(sa[0]).is_loopback
                            and not ipaddress.ip_address(sa[0]).is_link_local
                            and not ipaddress.ip_address(sa[0]).is_reserved
                            for _, _, _, _, sa in addrs
                        ):
                            safe_url = url
                except (socket.gaierror, ValueError):
                    safe_url = None
                if safe_url is None:
                    logger.warning("Reddit share-link HEAD blocked (SSRF): %s", url)

                if safe_url is not None:
                    async def _ssrf_check_redirect(response):
                        if response.is_redirect:
                            location = response.headers.get("location", "")
                            if location:
                                err = _validate_url_target(location)
                                if err:
                                    raise httpx.HTTPStatusError(
                                        f"Redirect blocked (SSRF): {err}",
                                        request=response.request, response=response,
                                    )

                    async with httpx.AsyncClient(
                        follow_redirects=True,
                        timeout=15.0,
                        event_hooks={"response": [_ssrf_check_redirect]},
                    ) as client:
                        head_resp = await client.head(safe_url, headers={"User-Agent": BROWSER_USER_AGENT})
                        resolved = str(head_resp.url)
                        if not resolved or resolved == safe_url or "/s/" in urlparse(resolved).path:
                            return [DownloadResult(
                                success=False,
                                error=f"Reddit share link did not resolve to a post: {safe_url}",
                            )]
                        logger.info("Resolved Reddit share link: %s -> %s", safe_url, resolved)
                        url = resolved
                        parsed = urlparse(url)

            # Media wrapper (reddit.com/media?url=<encoded-image-url>)
            if _is_reddit_host(parsed.hostname) and parsed.path.rstrip("/") == "/media":
                params = parse_qs(parsed.query)
                if "url" in params:
                    embedded_url = unquote(params["url"][0])
                    logger.info("Extracted embedded URL from Reddit media redirect: %s", embedded_url)
                    url = embedded_url
    except Exception as e:
        logger.debug("Reddit URL resolution failed for %s: %s", url, e)

    # 1. Direct image URLs bypass everything
    if is_direct_image_url(url):
        logger.info("Detected direct image URL: %s", url)
        result = await download_direct_image(url, output_dir)
        return [result]

    platform = identify_platform(url)

    # Reddit blocks JSON endpoints; the embed page still serves post markup
    if platform == "reddit" and "/comments/" in url:
        results = await extract_via_reddit_embed(url, output_dir)
        if results:
            return results
        logger.info("Reddit embed extraction found nothing for %s, falling back", url)

    # 2. gallery-dl for image-heavy platforms (and any unrecognized-but-supported)
    if platform in GALLERY_DL_PLATFORMS or (platform and platform not in YTDLP_PLATFORMS):
        results = await extract_via_gallery_dl(
            url, output_dir, cookies_file, platform=platform, settings=settings,
        )
        if results:
            return results

        # Block yt-dlp fallback for Instagram to avoid double-scraper detection
        if platform == "instagram" and not (settings and settings.instagram_ytdlp_fallback):
            logger.warning(
                "gallery-dl failed for Instagram URL %s; yt-dlp fallback disabled", url,
            )
            return [DownloadResult(
                success=False,
                error="Instagram download failed. gallery-dl could not extract media. "
                      "Check that your Instagram cookies are fresh and valid.",
            )]

        logger.info(
            "gallery-dl returned no results for %s, falling back to yt-dlp", url,
        )

    # 3. yt-dlp fallback for video platforms and gallery-dl failures
    result = await download_from_url(url, output_dir, cookies_file)

    # If yt-dlp failed on a reddit.com/media?url= redirect, extract the embedded image URL
    if not result.success and result.error and "reddit.com/media?url=" in result.error:
        match = re.search(r'reddit\.com/media\?url=(https?%3A%2F%2F[^\s"\']+)', result.error)
        if match:
            embedded_url = unquote(match.group(1))
            logger.info("Extracting embedded image URL from yt-dlp Reddit media error: %s", embedded_url)
            os.makedirs(output_dir, exist_ok=True)
            result = await download_direct_image(embedded_url, output_dir)

    # Surface rate-limit failures with a clearer message
    if not result.success and result.error and "HTTP Error 429" in result.error:
        result = DownloadResult(
            success=False,
            error=f"Rate limited by source ({platform or 'site'}); try again later",
        )

    # Final fallback: if we haven't already, try gallery-dl for unknown URLs
    if not result.success and platform is None:
        logger.info("yt-dlp failed for unknown URL %s; trying gallery-dl as last resort", url)
        gdl_results = await extract_via_gallery_dl(
            url, output_dir, cookies_file, platform=None, settings=settings,
        )
        if gdl_results:
            return gdl_results
        logger.warning(
            "Both yt-dlp and gallery-dl failed for %s: %s", url, result.error,
        )

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
