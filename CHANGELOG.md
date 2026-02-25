# Changelog

All notable changes to this project will be documented in this file.

## [1.3.3] - 2026-02-25

### Fixed
- Instagram image posts still failing when og:image meta tags are absent (JS-rendered pages)
  - Added oEmbed fallback (`/api/v1/oembed/`) that works without authentication
  - Returns 640x800 CDN thumbnail URL -- sufficient for image post extraction
  - New fallback chain: API -> oEmbed -> og:image scraping
  - oEmbed is tried before og:image since it is more reliable for unauthenticated requests

### Added
- `_instagram_oembed_fallback()` -- Instagram oEmbed API client for thumbnail extraction
- `_instagram_fallback_chain()` -- unified fallback wrapper (oEmbed then og:image)

## [1.3.2] - 2026-02-25

### Fixed
- Instagram image posts still failing with "No video formats found" despite v1.3.1 extraction
  - Cookies were never threaded through to `extract_instagram_media_urls()` -- the `?__a=1&__d=dis` API endpoint returns 404 without auth
  - Added `cookies_file` parameter to `download_platform_media()` and `extract_instagram_media_urls()`
  - `download_from_url_multi()` now passes `cookies_file` to platform-specific extractors
  - Cookies also passed to `_instagram_og_image_fallback()` for login-walled pages
- Instagram CDN image downloads failing when CDN rejects HEAD requests
  - HEAD pre-check is now non-fatal: logs a debug message and proceeds with GET
- Hardened og:image fallback regex to handle both `property/content` and `content/property` attribute orderings

### Added
- `parse_netscape_cookies()` helper to read Netscape cookie files into HTTP Cookie header strings

## [1.3.1] - 2026-02-25

### Fixed
- Reddit image posts failing with HTTP 429 (Too Many Requests)
  - Bypasses yt-dlp entirely for image posts: fetches Reddit JSON directly via httpx
  - Extracts image URLs from gallery posts (multi-image) and single image posts
  - Constructs direct `i.redd.it` URLs from media_metadata for original quality
  - Removed `--impersonate chrome` from Reddit yt-dlp args (did not fix 429)
  - Video posts still fall through to yt-dlp as before
- Instagram image posts failing with "No video formats found"
  - Uses Instagram REST API (`?__a=1&__d=dis`) to extract media URLs directly
  - Handles carousel posts (mixed images + videos), single images, and single videos
  - Selects highest resolution from available candidates
  - Falls back to og:image meta tag scraping if API endpoint fails
  - Reels and video-only posts still fall through to yt-dlp

### Added
- Gallery/carousel support: single URL uploads now handle multi-image posts
  - Reddit galleries download all images from the post
  - Instagram carousels download all images and videos from the post
  - All items uploaded to Immich; primary response returns first item
- `extract_reddit_image_urls()` -- Reddit post JSON parser for image extraction
- `extract_instagram_media_urls()` -- Instagram API client for media extraction
- `download_platform_media()` -- unified platform-specific media downloader
- `download_from_url_multi()` -- multi-result wrapper for gallery support

## [1.3.0] - 2026-02-25

### Added
- Direct image URL download support (bypasses yt-dlp for image files)
  - Downloads images via httpx with browser User-Agent, redirect following, and 100MB size limit
  - File type detection via magic bytes (reuses shared detect_file_type utility)
  - Known image-hosting domains: i.redd.it, i.imgur.com, pbs.twimg.com, preview.redd.it
  - Any URL ending in .jpg, .jpeg, .png, .gif, .webp, .avif, .heic, .bmp, .tiff
  - Works in both single and batch upload endpoints
- Reddit URL patterns for i.redd.it and preview.redd.it image domains

### Fixed
- Reddit downloads failing with HTTP 429 (Too Many Requests)
  - Added browser impersonation (`--impersonate chrome`) for Reddit, matching existing Facebook fix

### Changed
- Extracted detect_file_type into shared app/utils.py module (used by both api_routes and url_downloader)
- Updated frontend description text to mention direct image URL support
- is_supported_url now returns True for direct image URLs (not just platform-matched URLs)

## [1.2.9] - 2026-02-15

### Fixed
- Facebook downloads: Force mp4 output format to prevent corrupt files in Immich
  - Changed format selection to prefer mp4 containers with `--merge-output-format mp4`
  - Previous `bestvideo+bestaudio/best` could produce .webm/.mkv that Immich cannot play
- iOS Shortcut: Updated URL detection from "contains http" text check to "Get URLs from Input"
  - Facebook's share sheet passes URLs in a format the old text check could not detect
  - Shortcut was falling through to base64 path and uploading a thumbnail instead of the video
  - New approach uses "Get URLs from Input" + "Get First Item from List" for reliable extraction

### Added
- Debug logging for yt-dlp downloads (command, stderr, metadata, file size, format)
- Warning log when downloaded file is very small (likely a thumbnail instead of video)
- Upload logging with filename, content type, and file size before sending to Immich
- Facebook added to iOS Shortcuts and README supported platform lists

## [1.2.8] - 2026-02-15

### Added
- Facebook Reels and video support (URL downloads via yt-dlp)
  - Supported URL formats: /reel/, /videos/, /watch, /share/v/, /share/r/, fb.watch short links
  - Cookie support for authenticated Facebook downloads
  - Video-first format selection to prevent thumbnail-only downloads
  - Browser impersonation for Facebook downloads (bypasses bot detection)

### Changed
- Unpinned yt-dlp version (always pulls latest on build, was previously pinned to >=2024.1.0)
- Added curl_cffi dependency for yt-dlp browser impersonation support

## [1.2.7] - 2026-01-30

### Fixed
- Album creation race condition: Multiple concurrent uploads no longer create duplicate albums
  - Added async lock to prevent simultaneous album creation
  - Added proper error handling when Immich returns 5xx errors (skips album assignment instead of creating duplicates)
- Reddit share link URLs now supported (format: `reddit.com/r/<subreddit>/s/<id>`)

## [1.2.6] - 2026-01-02

### Added
- Auto-detect file type from magic bytes in base64 upload endpoint
  - Supports JPEG, PNG, GIF, WebP, HEIC, AVIF, MP4, MOV, BMP, TIFF
  - Filename extension no longer required for iOS Shortcuts uploads
  - Automatically appends correct extension if missing
- Official iOS Shortcut for uploading photos, videos, and URLs
  - Download link in docs/ios-shortcuts.md
  - Handles photos, videos (MOV/MP4), and social media URLs
  - Uses Encode Media passthrough for proper video handling

## [1.2.5] - 2026-01-01

### Fixed
- WebSocket disconnect error handling (RuntimeError when client disconnects)

## [1.2.4] - 2025-12-31

### Added
- Version logging on application startup

### Fixed
- URL upload: Use inline styles for vertical stacking (fixes Tailwind CDN dynamic content issue)

## [1.2.3] - 2025-12-31

### Fixed
- URL upload: Use inline styles for vertical stacking (fixes Tailwind CDN dynamic content issue)

## [1.2.2] - 2025-12-31

### Changed
- Version footer now dynamically fetches from `/api/config` instead of hardcoded value
- Mobile UI: Restored "Choose files" button inside dropzone (removed sticky bottom bar)
- URL upload input and button now always stack vertically for consistency
- Login page: "Back to uploader" link styled as outlined button
- Admin menu: "Create album" button styled as outlined (secondary action)

### Fixed
- Mobile UI: "Choose files" button visible on all screen sizes
- All pages now show consistent version footer with dynamic version

## [1.2.1] - 2025-12-31

### Added
- Version footer with GitHub link on all pages

### Fixed
- Mobile UI: URL upload button now stacks vertically on small screens
- Mobile UI: Removed duplicate "Choose files" button (sticky bar only on mobile)

## [1.2.0] - 2025-12-31

### Added
- Platform cookie management for authenticated social media downloads
  - New "Platform Cookies" section in admin menu
  - Supports Instagram, TikTok, Twitter/X, Reddit, and YouTube
  - Paste raw cookie strings from browser DevTools
  - Automatically converts to Netscape format for yt-dlp
- New API endpoints:
  - `GET /api/cookies` - List configured platform cookies
  - `POST /api/cookies` - Create or update platform cookie
  - `DELETE /api/cookies/{platform}` - Delete platform cookie
- Cookie files stored in `/data/cookies/` with restrictive permissions

### Changed
- yt-dlp now applies cookies to all supported platforms (previously Instagram only)
- Batch URL downloads use cookies when all URLs are from the same platform

## [1.1.3] - 2025-12-28

### Added
- New `/api/upload/base64` endpoint for iOS Shortcuts file uploads
  - Accepts JSON body with base64-encoded file data
  - More reliable than multipart form uploads from iOS Shortcuts
  - Supports data URL format (e.g., `data:image/jpeg;base64,...`)

### Changed
- Updated iOS Shortcuts documentation with base64 upload method
- Improved iOS Shortcuts instructions with correct action syntax

## [1.1.2] - 2025-12-28

### Fixed
- Fixed url-uploader.js not loading due to restrictive file permissions (600 -> 644)
- Extended Dockerfile chmod to include frontend directory

## [1.1.1] - 2025-12-28

### Fixed
- Fixed container startup permission error for api_routes.py
- Added explicit chmod in Dockerfile to ensure Python files are readable

### Changed
- Optimized httpx usage with shared AsyncClient via FastAPI lifespan for connection pooling
- Updated api_routes.py to use shared httpx client from app state

## [1.1.0] - 2025-12-28

### Added
- URL download support for TikTok, Instagram, Reddit, YouTube, and Twitter/X
- iOS Shortcut-compatible endpoints for file uploads
- New API endpoints:
  - `POST /api/upload/url` - Download and upload from single URL
  - `POST /api/upload/urls` - Batch URL downloads (max 10)
  - `POST /api/upload/file` - Single file upload (iOS shortcut)
  - `POST /api/upload/batch` - Multiple file upload (iOS shortcut)
  - `GET /api/supported-platforms` - List supported platforms
- URL uploader UI component on main upload page
- yt-dlp integration for social media downloads
- ffmpeg support in Docker image for video processing

### Changed
- Migrated HTTP client from sync `requests` to async `httpx` for better performance

## [1.0.0] - Initial Release

### Added
- File upload to Immich with duplicate detection
- Chunked upload support for large files
- Invite link system with password protection and expiry
- WebSocket progress tracking
- Album management
- QR code generation for invite links
