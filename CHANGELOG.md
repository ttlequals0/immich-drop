# Changelog

All notable changes to this project will be documented in this file.

## [1.2.8] - 2026-02-15

### Added
- Facebook Reels and video support (URL downloads via yt-dlp)
  - Supported URL formats: /reel/, /videos/, /watch, /share/v/, /share/r/, fb.watch short links
  - Cookie support for authenticated Facebook downloads
  - Video-first format selection to prevent thumbnail-only downloads

### Changed
- Unpinned yt-dlp version (always pulls latest on build, was previously pinned to >=2024.1.0)

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
