# iOS Shortcut for immich-drop

Share a link from any app on your iPhone, download the media, and upload it to Immich.

## Download the Shortcut

**[Download "Dead-Drop" Shortcut](Dead-Drop.shortcut)**

Supports TikTok, Instagram, Facebook, Reddit, YouTube, Twitter/X, Flickr, Imgur, Tumblr, Pinterest, Bluesky, and direct image URLs.

## Setup

1. Download the `.shortcut` file on your iOS device and tap to import
2. Edit the shortcut in the Shortcuts app
3. Find the two `https://YOUR-SERVER-HERE.example.com` URLs and replace with your server:
   - The POST URL: `https://your-server.com/api/upload/url`
   - The status poll URL: `https://your-server.com/api/upload/url/status/`
4. Or rebuild with your server URL using `docs/build-shortcut.py` (see below)

## Usage

1. Open TikTok, Instagram, Facebook, Reddit, YouTube, Twitter, or other supported platforms
2. Find a video/post you want to save
3. Tap Share -> "Dead-Drop"
4. The shortcut submits the URL, polls for completion, and shows a notification when done

## How It Works

The shortcut uses async polling to avoid iOS timeout issues:

1. Extracts the URL from Share Sheet input
2. POSTs to `/api/upload/url` which returns a job ID immediately
3. Polls `/api/upload/url/status/{job_id}` every 3 seconds
4. When the `result` field appears in the response -> shows "Upload complete"
5. When the `error` field appears -> shows "Upload failed"
6. Exits the shortcut after showing the alert

This handles slow downloads (Instagram with anti-detection sleep delays can take 60+ seconds) without hitting iOS Shortcuts' HTTP timeout.

## Building the Shortcut

The shortcut is built programmatically from `docs/build-shortcut.py`:

```bash
# Edit SERVER variable in build-shortcut.py first
python docs/build-shortcut.py
# Output: ~/Downloads/Dead-Drop.shortcut
```

The script generates an unsigned plist and signs it with `shortcuts sign`. The signed `.shortcut` file can be imported on any iOS device.

### Why not build it by hand?

`shortcuts sign` silently strips parameters from the plist. String comparisons, number comparisons, explicit HTTP bodies -- all gone after signing. The only way to get a working shortcut with conditional logic is to know which parameter formats survive and which don't. The script handles that. See `ios-shortcuts-plist-reference.md` for the full list of quirks.

---

## API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/upload/url` | POST | Submit URL for async download (returns job_id) |
| `/api/upload/url/status/{job_id}` | GET | Poll job status |
| `/api/upload/base64` | POST | Upload base64-encoded file (JSON: data, filename) |
| `/api/upload/urls` | POST | Batch URL downloads (JSON: urls[], max 10) |
| `/api/supported-platforms` | GET | List supported URL platforms |

### URL Upload (async)

```
POST /api/upload/url
Content-Type: application/json

{"url": "https://www.tiktok.com/@user/video/123"}
```

Response (immediate):
```json
{"job_id": "abc123", "status": "pending"}
```

Poll:
```
GET /api/upload/url/status/abc123
```

While downloading:
```json
{"job_id": "abc123", "status": "downloading", "created_at": 1234567890.0}
```

On completion:
```json
{"job_id": "abc123", "status": "completed", "created_at": 1234567890.0, "result": {"success": true, "result": {"filename": "video.mp4", "status": "success", "asset_id": "uuid"}}}
```

On failure:
```json
{"job_id": "abc123", "status": "failed", "created_at": 1234567890.0, "error": "Error message"}
```

---

## Troubleshooting

### Shortcut shows "Upload failed"
- Check server logs for the actual error
- Reddit posts may fail with 429 (rate limited) -- wait a few minutes and retry
- Instagram requires fresh cookies configured in the admin menu

### Shortcut keeps polling without completing
- Check that your server is running v1.6.0+
- The status endpoint must return `result` or `error` fields only when the job is done
- Jobs expire after 10 minutes

### "Unsupported URL" error
- Make sure you're sharing the video/post URL, not just text
- See the [full list of supported platforms](../README.md#url-downloads) in the README

### Instagram downloads slow
- Anti-detection sleep delays (10-25 seconds between requests) are intentional
- The async polling handles this -- the shortcut waits up to 90 seconds

### Reddit image posts failing
- Some Reddit image posts redirect through `reddit.com/media?url=` which gallery-dl and yt-dlp can't handle directly
- Server v1.6.1+ extracts the embedded image URL automatically
- If you see 429 errors, Reddit is rate-limiting you -- wait a few minutes
