"""
Thin entrypoint so you can run `python main.py` from project root.
"""
import os
import uvicorn
from dotenv import load_dotenv
load_dotenv()


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app.app:app", host=host, port=port, reload=True)