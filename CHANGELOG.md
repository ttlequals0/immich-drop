# Changelog

All notable changes to this project will be documented in this file.

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
