"""FastAPI application entry point and static document-finder frontend."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from document_finder.api.routes import router

app = FastAPI(title="Document Finder API", version="0.1.0")
app.include_router(router)
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
