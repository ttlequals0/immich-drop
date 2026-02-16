# iOS Shortcuts for immich-drop

Upload photos, videos, and social media links directly to your Immich server from your iPhone or iPad.

## Download the Shortcut

**[Download "Save to Immich" Shortcut](https://www.icloud.com/shortcuts/fcd52bd36a3c4a569bae1d6dfe743756)**

This shortcut handles:
- Photos (JPEG, HEIC, PNG, etc.)
- Videos (MOV, MP4)
- Social media URLs (TikTok, Instagram, Facebook, Reddit, YouTube, Twitter/X)

## Setup

1. Tap the download link above on your iOS device
2. Tap "Add Shortcut"
3. **Important:** Edit the shortcut and update the `ServerName` variable to your immich-drop server URL:
   - Example: `https://drop.yourdomain.com`
   - Example: `http://192.168.1.100:8080`

## Usage

### For Photos and Videos

1. Select photos/videos in the Photos app (or any app)
2. Tap the Share button
3. Select "Save to Immich"
4. Files upload automatically

### For Social Media URLs

1. Open TikTok, Instagram, Facebook, Reddit, YouTube, or Twitter
2. Find a video/post you want to save
3. Tap Share -> "Save to Immich"
4. The video downloads and uploads automatically

## How It Works

The shortcut:
1. Detects if input is a URL or media file
2. For URLs: Sends to `/api/upload/url` endpoint for server-side download
3. For videos: Uses "Encode Media" with Passthrough to preserve raw video data
4. For images: Encodes directly to base64
5. Uploads via `/api/upload/base64` endpoint with auto-detected file type

The server automatically detects file types from magic bytes, so filename extensions are optional.

---

## Troubleshooting

### "Request failed" or timeout errors
- Check your server URL is correct in the `ServerName` variable
- Ensure your server is accessible from your phone (not just local network if on cellular)
- Large videos may take time to process - be patient

### "The network connection was lost"
- This usually means the request body wasn't sent correctly
- Make sure you're using the official shortcut from the link above

### "Unsupported URL" error
- Make sure you're sharing the video/post URL, not just text
- Supported platforms: TikTok, Instagram, Facebook, Reddit, YouTube, Twitter/X

### Videos not downloading from Instagram
- Instagram stories/posts may require authentication
- Configure platform cookies in the immich-drop admin menu
- Try public posts first

### "413 Request Entity Too Large"
- If using a reverse proxy (nginx, Traefik), increase body size limit
- For nginx: `client_max_body_size 500M;`

### Facebook Reels show "Unsupported URL" error
- Make sure your immich-drop server is v1.2.8 or later
- Supported URL formats: /reel/, /videos/, /watch, /share/v/, /share/r/, fb.watch short links
- If using a private video, configure Facebook cookies in the admin menu

### Images appear corrupted
- Make sure you're using the latest shortcut version
- The shortcut uses "Encode Media" for videos and direct base64 for images
- Server v1.2.6+ auto-detects file types from content

---

## API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/upload/base64` | POST | Upload base64-encoded file (JSON: data, filename) - Recommended for iOS |
| `/api/upload/url` | POST | Download and upload from URL (JSON: url) |
| `/api/upload/urls` | POST | Batch URL downloads (JSON: urls[], max 10) |
| `/api/supported-platforms` | GET | List supported URL platforms |

### Base64 Upload Format

```json
{
  "data": "base64-encoded-file-content",
  "filename": "optional-filename.jpg",
  "album_name": "optional-album-name"
}
```

The server auto-detects file type from magic bytes. Supported formats:
- Images: JPEG, PNG, GIF, WebP, HEIC, AVIF, BMP, TIFF
- Videos: MP4, MOV

---

## Manual Shortcut Creation

If you prefer to create the shortcut manually or want to customize it, the key components are:

1. **URL Detection**: Check if input contains "http" to route to URL upload
2. **Video Detection**: Use "Get Details of Images" -> "File Extension" to detect .mov/.mp4
3. **Video Processing**: Use "Encode Media" with Size: Passthrough before base64 encoding
4. **Image Processing**: Base64 encode directly with Line Breaks: None
5. **JSON Body**: Build manually with Text action, send as Request Body: File
6. **Result Handling**: Store upload result in a variable before End If to handle both paths
