# iOS Shortcuts for immich-drop

These shortcuts allow you to share photos, videos, and social media links directly to your Immich server.

## Combined Shortcut: Save to Immich (Recommended - Base64 Method)

**Note:** This uses the base64 endpoint which is more reliable than multipart form uploads from iOS Shortcuts.

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

   4. Get Dictionary from Input
      Input: [Contents of URL]

   5. Get Dictionary Value
      Get Value for Key: success
      in Dictionary: [Dictionary]

   6. If [Dictionary Value] equals 1

      7. Get Dictionary Value
         Get Value for Key: result
         in Dictionary: [Dictionary]

      8. Get Dictionary Value
         Get Value for Key: filename
         in Dictionary: [Dictionary Value]

      9. Show Alert
         Title: Saved to Immich
         Message: [Dictionary Value]
         Show Cancel Button: OFF

   10. Otherwise

      11. Get Dictionary Value
          Get Value for Key: error
          in Dictionary: [Dictionary]

      12. Show Alert
          Title: Upload Failed
          Message: [Dictionary Value]

   13. End If

14. Otherwise

   =============== FILE PATH (loops for multiple files) ===============

   15. Number
       Value: 0

   16. Set Variable
       Variable Name: uploadCount
       (uses Number output above)

   17. Number
       Value: 0

   18. Set Variable
       Variable Name: errorCount
       (uses Number output above)

   19. Repeat with Each item in [Shortcut Input]

      20. Base64 Encode
          Input: [Repeat Item]
          Line Breaks: None

      21. Get Name
          Input: [Repeat Item]

      22. Set Variable
          Variable Name: currentFilename

      23. Get Contents of URL
          URL: https://YOUR_IMMICH_DROP_URL/api/upload/base64
          Method: POST
          Request Body: JSON
          Add fields:
            - Key: data
              Type: Text
              Value: [Base64 Encoded]
            - Key: filename
              Type: Text
              Value: [currentFilename]

      24. Get Dictionary from Input
          Input: [Contents of URL]

      25. Get Dictionary Value
          Get Value for Key: status
          in Dictionary: [Dictionary]

      26. If [Dictionary Value] equals "success"

          27. Calculate
              Calculate: [uploadCount] + 1

          28. Set Variable
              Variable Name: uploadCount
              (uses Calculation Result)

      29. Otherwise

          30. Calculate
              Calculate: [errorCount] + 1

          31. Set Variable
              Variable Name: errorCount
              (uses Calculation Result)

      32. End If

   33. End Repeat

   34. Show Alert
       Title: Immich Upload Complete
       Message: [uploadCount] uploaded, [errorCount] failed
       Show Cancel Button: OFF

35. End If
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

### File Upload Only (Base64 Method)

```
1. Receive [Images, Media, Files] input from [Share Sheet]
   - Show in Share Sheet: ON

2. Number
   Value: 0

3. Set Variable
   Variable Name: uploadCount

4. Number
   Value: 0

5. Set Variable
   Variable Name: errorCount

6. Repeat with Each item in [Shortcut Input]

   7. Base64 Encode
      Input: [Repeat Item]
      Line Breaks: None

   8. Get Name
      Input: [Repeat Item]

   9. Set Variable
      Variable Name: currentFilename

   10. Get Contents of URL
       URL: https://YOUR_IMMICH_DROP_URL/api/upload/base64
       Method: POST
       Request Body: JSON
       Add fields:
         - Key: data
           Type: Text
           Value: [Base64 Encoded]
         - Key: filename
           Type: Text
           Value: [currentFilename]

   11. Get Dictionary from Input
       Input: [Contents of URL]

   12. Get Dictionary Value
       Get Value for Key: status
       in Dictionary: [Dictionary]

   13. If [Dictionary Value] equals "success"

       14. Calculate
           Calculate: [uploadCount] + 1

       15. Set Variable
           Variable Name: uploadCount

   16. Otherwise

       17. Calculate
           Calculate: [errorCount] + 1

       18. Set Variable
           Variable Name: errorCount

   19. End If

20. End Repeat

21. Show Alert
    Title: Immich Upload
    Message: [uploadCount] uploaded, [errorCount] failed
    Show Cancel Button: OFF
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

3. Get Dictionary from Input
   Input: [Contents of URL]

4. Get Dictionary Value
   Get Value for Key: success
   in Dictionary: [Dictionary]

5. If [Dictionary Value] equals 1

   6. Get Dictionary Value
      Get Value for Key: result
      in Dictionary: [Dictionary]

   7. Get Dictionary Value
      Get Value for Key: filename
      in Dictionary: [Dictionary Value]

   8. Show Alert
      Title: Saved to Immich
      Message: [Dictionary Value]
      Show Cancel Button: OFF

9. Otherwise

   10. Get Dictionary Value
       Get Value for Key: error
       in Dictionary: [Dictionary]

   11. Show Alert
       Title: Upload Failed
       Message: [Dictionary Value]

12. End If
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
| `/api/upload/base64` | POST | Upload base64-encoded file (JSON: data, filename) - Recommended for iOS |
| `/api/upload/file` | POST | Upload single file (Form: file) |
| `/api/upload/batch` | POST | Upload multiple files (Form: files[]) |
| `/api/upload/url` | POST | Download and upload from URL (JSON: url) |
| `/api/upload/urls` | POST | Batch URL downloads (JSON: urls[]) |
| `/api/supported-platforms` | GET | List supported URL platforms |
