import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import auth, designs, documents, media, paste, templates
from .config import settings
from .database.session import Base, engine
from .models import db as _models  # noqa: F401  (registers tables)

Base.metadata.create_all(engine)

app = FastAPI(title="SmartDoc", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-SmartDoc-Warnings", "X-SmartDoc-Note"])
for r in (auth.router, templates.router, documents.router, media.router, paste.router, designs.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    from .document_engine.pdf import soffice_path
    return {"status": "ok", "pdf_export": soffice_path() is not None}


if os.path.isdir(settings.frontend_dist):   # serve the built frontend when present
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
