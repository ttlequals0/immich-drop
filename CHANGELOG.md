# Changelog

All notable changes to this project will be documented in this file.

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
