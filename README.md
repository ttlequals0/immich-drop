# Immich Drop Uploader

A tiny, zero-login web app for collecting photos/videos into your **Immich** server.

![Immich Drop Uploader Dark Mode UI](./screenshot.png)

## Features

- **No accounts** — open the page, drop files, done  
- **Queue with progress** via WebSocket (success / duplicate / error)  
- **Duplicate prevention** (local SHA‑1 cache + optional Immich bulk‑check)  
- **Original dates preserved** (EXIF → `fileCreatedAt` / `fileModifiedAt`)  
- **Mobile‑friendly** 
- **.env‑only config** (clean deploys) + Docker/Compose  
- **Privacy‑first**: never lists server media; UI only shows the current session
- **Dark mode support** — automatically detects system preference, with manual toggle
- **Album integration** — auto-adds uploads to a configured album (creates if needed)

---

## Table of contents
- [Quick start](#quick-start)
- [New Features](#new-features)
- [Architecture](#architecture)
- [Folder structure](#folder-structure)
- [Requirements](#requirements)
- [Configuration (.env)](#configuration-env)
- [How it works](#how-it-works)
- [Mobile notes](#mobile-notes)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [Development](#development)
- [License](#license)

---
## Quick start
Copy the docker-compose.yml and the .env file to a common folder,
update the .env file before executing the CLI commands to quick start the container.

### docker-compose.yml
```yaml
version: "3.9"

services:
  immich-drop:
    image: ghcr.io/nasogaa/immich-drop:latest
    pull_policy: always
    container_name: immich-drop
    restart: unless-stopped

    # Optional: Set album name for auto-adding uploads
    environment:
      IMMICH_ALBUM_NAME: dead-drop  # Optional: uploads will be added to this album

    # Load all variables from your repo's .env (PORT, IMMICH_BASE_URL, IMMICH_API_KEY, etc.)
    env_file:
      - ./.env

    # Expose the app on the same port as configured in .env (defaults to 8080)
    ports:
      - 8080:8080

    # Persist local dedupe cache (state.db) across restarts
    volumes:
      - immich_drop_data:/data

    # Simple healthcheck
    healthcheck:
      test: ["CMD-SHELL", "python - <<'PY'\nimport os,urllib.request,sys; url=f\"http://127.0.0.1:{os.getenv('PORT','8080')}/\";\ntry: urllib.request.urlopen(url, timeout=3); sys.exit(0)\nexcept Exception: sys.exit(1)\nPY"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  immich_drop_data:
```

### .env 

```
HOST=0.0.0.0
PORT=8080
IMMICH_BASE_URL=http://REPLACE_ME:2283/api
IMMICH_API_KEY=REPLACE_ME
MAX_CONCURRENT=3
IMMICH_ALBUM_NAME=dead-drop  # Optional: auto-add uploads to this album
STATE_DB=/data/state.db
```

### CLI
```bash
docker compose pull
docker compose up -d
```
---

## New Features

### 🌙 Dark Mode
- Automatically detects system dark/light preference on first visit
- Manual toggle button in the header (sun/moon icon)
- Preference saved in browser localStorage
- Smooth color transitions for better UX
- All UI elements properly themed for both modes

### 📁 Album Integration
- Configure `IMMICH_ALBUM_NAME` environment variable to auto-add uploads to a specific album
- Album is automatically created if it doesn't exist
- Efficient caching of album ID to minimize API calls
- Visual feedback showing which album uploads are being added to
- Works seamlessly with existing duplicate detection

### 🐛 Bug Fixes
- Fixed WebSocket disconnection error that occurred when clients closed connections
- Improved error handling for edge cases

---

## Architecture

- **Frontend:** static HTML/JS (Tailwind). Drag & drop or "Choose files", queue UI with progress and status chips.  
- **Backend:** FastAPI + Uvicorn.  
  - Proxies uploads to Immich `/assets`  
  - Computes SHA‑1 and checks a local SQLite cache (`state.db`)  
  - Optional Immich de‑dupe via `/assets/bulk-upload-check`  
  - WebSocket `/ws` pushes per‑item progress to the current browser session only  
- **Persistence:** local SQLite (`state.db`) prevents re‑uploads across sessions/runs.

---

## Folder structure

```
immich_drop/
├─ app/                    # FastAPI application (Python package)
│  ├─ __init__.py
│  ├─ app.py               # uvicorn app:app
│  └─ config.py            # loads .env from repo root
├─ frontend/               # static UI served at /static
│  ├─ index.html
│  └─ app.js
├─ main.py                 # thin entrypoint (python main.py)
├─ requirements.txt        # Python deps
├─ .env                    # single config file (see below)
├─ Dockerfile
├─ docker-compose.yml
└─ README.md
```

---

## Requirements

- **Python** 3.11
- An **Immich** server + **API key**

---
## Configuration (.env)

```ini
# Server
HOST=0.0.0.0 
PORT=8080

# Immich connection (include /api)
IMMICH_BASE_URL=http://REPLACE_ME:2283/api
IMMICH_API_KEY=ADD-YOUR-API-KEY   #key needs asset.upload (default functions)

MAX_CONCURRENT=3

# Optional: Album name for auto-adding uploads (creates if doesn't exist)
IMMICH_ALBUM_NAME=dead-drop       #key needs album.create,album.read,albumAsset.create (extended functions)

# Local dedupe cache
STATE_DB=./data/state.db         # local dev -> ./state.db (data folder is created in docker image)
# In Docker this is overridden to /data/state.db by docker-compose.yml
```


You can keep a checked‑in `/.env.example` with the keys above for onboarding.

---

## How it works

1. **Queue** – Files selected in the browser are queued; each gets a client‑side ID.  
2. **De‑dupe (local)** – Server computes **SHA‑1** and checks `state.db`. If seen, marks as **duplicate**.  
3. **De‑dupe (server)** – Attempts Immich `/assets/bulk-upload-check`; if Immich reports duplicate, marks accordingly.  
4. **Upload** – Multipart POST to `${IMMICH_BASE_URL}/assets` with:
   - `assetData`, `deviceAssetId`, `deviceId`,  
   - `fileCreatedAt`, `fileModifiedAt` (from EXIF when available; else `lastModified`),  
   - `isFavorite=false`, `filename`, and header `x-immich-checksum`.  
5. **Album** – If `IMMICH_ALBUM_NAME` is configured, adds the uploaded asset to the album (creates album if it doesn't exist).  
6. **Progress** – Backend streams progress via WebSocket to the same session.  
7. **Privacy** – UI shows only the current session's items. It never lists server media.

---


## Mobile notes

- Uses a **label‑wrapped input** + short **ghost‑click suppression** so the system picker does **not** re‑open after tapping **Done** (fixes iOS/Android quirks).  
- Drag‑and‑drop is desktop‑oriented; on touch, use **Choose files**.

---

## Troubleshooting

**Uploads don't start on phones / picker re‑opens**  
– Hard‑refresh; current UI suppresses ghost clicks and resets the input.  
– If using a PWA/WebView, test in Safari/Chrome directly to rule out container quirks.

**WebSocket connects/disconnects in a loop**  
– Match schemes: `ws://` for `http://`, `wss://` for `https://`.  
– If behind a reverse proxy, ensure it forwards WebSockets.

**413 Request Entity Too Large**  
– If running behind nginx/Traefik/etc., bump body size limits (`client_max_body_size` for nginx).

**/assets returns 401**  
– Check `IMMICH_API_KEY` and ensure the base URL includes `/api` (e.g., `http://<host>:2283/api`).

**Duplicate detected but you expect an upload**  
– The proxy caches SHA‑1 in `state.db`. For a fresh run, delete that DB or point `STATE_DB` to a new file.

---

## Security notes

- The app is **unauthenticated** by design. Share the URL only with trusted people or keep it on a private network/VPN.  
- The Immich API key remains **server‑side**; the browser never sees it.  
- No browsing of uploaded media; only ephemeral session state is shown.

---

## Development

Run with live reload:

```bash
python main.py
```

The backend contains docstrings so you can generate docs later if desired.

---

## License

MIT.
