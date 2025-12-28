# iOS Shortcuts for immich-drop

These shortcuts allow you to share photos, videos, and social media links directly to your Immich server.

## Combined Shortcut: Save to Immich (Recommended)

**Purpose**: Single shortcut that handles both file uploads AND URL downloads from TikTok, Instagram, Reddit, etc.

### Manual Creation

1. Open the **Shortcuts** app
2. Tap **+** to create a new shortcut
3. Name it "Save to Immich"
4. Add these actions in order:

```
1. Receive [Images, Media, Files, URLs, Text] input from [Share Sheet, Quick Actions]
   - Show in Share Sheet: ON

2. If [Shortcut Input] contains "http"

   =============== URL PATH ===============

   3. Get Contents of URL
      URL: https://YOUR_IMMICH_DROP_URL/api/upload/url
      Method: POST
      Headers:
        Content-Type: application/json
      Request Body: JSON
      {
        "url": "[Shortcut Input]"
      }

   4. Get Dictionary from [Contents of URL]

   5. If [success] equals [true]

      6. Show Notification
         Title: Saved to Immich
         Body: [result.filename]

   7. Otherwise

      8. Show Alert
         Title: Upload Failed
         Message: [error]

   9. End If

10. Otherwise

   =============== FILE PATH (loops for multiple files) ===============

   11. Set variable [uploadCount] to 0

   12. Set variable [errorCount] to 0

   13. Repeat with Each item in [Shortcut Input]

      14. Get Contents of URL
          URL: https://YOUR_IMMICH_DROP_URL/api/upload/file
          Method: POST
          Request Body: Form
          Add new field:
            - Type: File
            - Key: file
            - Value: [Repeat Item]

      15. Get Dictionary from [Contents of URL]

      16. If [status] equals "success"

          17. Calculate [uploadCount] + 1

          18. Set variable [uploadCount] to [Calculation Result]

      19. Otherwise

          20. Calculate [errorCount] + 1

          21. Set variable [errorCount] to [Calculation Result]

      22. End If

   23. End Repeat

   24. Show Notification
       Title: Immich Upload Complete
       Body: [uploadCount] uploaded, [errorCount] failed

25. End If
```

### Usage

**For Photos/Videos:**
1. Select photos/videos in Photos app (or any app)
2. Tap Share button
3. Select "Save to Immich"
4. All selected files upload with progress notification

**For Social Media URLs:**
1. Open TikTok, Instagram, Reddit, YouTube, Twitter
2. Find a video/post you want to save
3. Tap Share -> "Save to Immich"
4. Video downloads and uploads automatically


---


## Alternative: Separate Shortcuts

If you prefer simpler, single-purpose shortcuts:

### File Upload Only

```
1. Receive [Images, Media, Files] input from [Share Sheet]
   - Show in Share Sheet: ON

2. Set variable [uploadCount] to 0

3. Set variable [errorCount] to 0

4. Repeat with Each item in [Shortcut Input]

   5. Get Contents of URL
      URL: https://YOUR_IMMICH_DROP_URL/api/upload/file
      Method: POST
      Request Body: Form
      - Type: File
      - Key: file
      - Value: [Repeat Item]

   6. Get Dictionary from [Contents of URL]

   7. If [status] equals "success"
      8. Calculate [uploadCount] + 1
      9. Set variable [uploadCount] to [Calculation Result]
   10. Otherwise
      11. Calculate [errorCount] + 1
      12. Set variable [errorCount] to [Calculation Result]
   13. End If

14. End Repeat

15. Show Notification
    Title: Immich Upload
    Body: [uploadCount] uploaded, [errorCount] failed
```

### URL Upload Only

```
1. Receive [URLs, Text] input from [Share Sheet]
   - Show in Share Sheet: ON

2. Get Contents of URL
   URL: https://YOUR_IMMICH_DROP_URL/api/upload/url
   Method: POST
   Headers:
     Content-Type: application/json
   Request Body: JSON
   {
     "url": "[Shortcut Input]"
   }

3. Get Dictionary from [Contents of URL]

4. If [success] equals [true]

   5. Show Notification
      Title: Saved to Immich
      Body: [result.filename]

6. Otherwise

   7. Show Alert
      Title: Upload Failed
      Message: [error]

8. End If
```


---


## Configuration

Replace `YOUR_IMMICH_DROP_URL` with your actual immich-drop server URL:
- `https://drop.yourdomain.com`
- `http://192.168.1.100:8080`

### Optional: Album Parameter

Add `album_name` to save uploads to a specific album:

**For URL uploads** (JSON body):
```json
{
  "url": "[Shortcut Input]",
  "album_name": "Social Media Saves"
}
```

**For file uploads** (Form field):
- Add another Form field:
  - Type: Text
  - Key: album_name
  - Value: "Camera Uploads"


---


## Troubleshooting

### "Request failed" or timeout errors
- Check your server URL is correct
- Ensure your server is accessible from your phone (not just local network if on cellular)
- Large videos may take time to download - be patient

### "Unsupported URL" error
- Make sure you're sharing the video/post URL, not just text
- Supported platforms: TikTok, Instagram, Reddit, YouTube, Twitter/X

### Only one file uploads (FIXED)
- The updated shortcut uses "Repeat with Each" to upload files individually
- Make sure you're using the new shortcut instructions above

### Videos not downloading from Instagram
- Instagram stories/posts may require authentication
- Try public posts first

### "413 Request Entity Too Large"
- If using reverse proxy (nginx, Traefik), increase body size limit
- For nginx: `client_max_body_size 500M;`


---


## API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/upload/file` | POST | Upload single file (Form: file) |
| `/api/upload/batch` | POST | Upload multiple files (Form: files[]) |
| `/api/upload/url` | POST | Download and upload from URL (JSON: url) |
| `/api/upload/urls` | POST | Batch URL downloads (JSON: urls[]) |
| `/api/supported-platforms` | GET | List supported URL platforms |
