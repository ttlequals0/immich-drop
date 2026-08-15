"""Thin entrypoint for local development.
Reads host/port from environment and starts Uvicorn.
"""
import os
import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    # Load .env for host/port only; app config loads in app.config
    try:
        load_dotenv()
    except Exception:
        pass
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    
    kwargs = {"host": host, "port": port, "reload": True}
    trusted_proxy = os.getenv("TRUSTED_PROXY")
    if trusted_proxy:
        kwargs["proxy_headers"] = True
        kwargs["forwarded_allow_ips"] = trusted_proxy
        
    uvicorn.run("app.app:app", **kwargs)
