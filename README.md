# Immich Drop Uploader – Clean Split (FastAPI + Static Frontend)

- **backend/** FastAPI server (upload proxy, WebSocket progress, runtime config API)
- **frontend/** Static HTML/JS (drag & drop, queue, ephemeral banner, settings modal)

## Run
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit base URL, API key, CONFIG_TOKEN (optional)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8080
# open http://localhost:8080
```
