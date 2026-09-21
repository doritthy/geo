from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, files, formations, grids, maps, projects, surfaces, wells
from app.storage import ensure_bucket

settings = get_settings()

app = FastAPI(title="Subsurface 3D Workspace API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Cell-Count", "Content-Length"],
)


@app.on_event("startup")
def on_startup() -> None:
    # Best-effort: create the bucket if the object store is reachable. This
    # must never crash app startup (e.g. object store briefly unavailable).
    try:
        ensure_bucket()
    except Exception:
        pass


app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(files.router)
app.include_router(wells.router)
app.include_router(grids.router)
app.include_router(surfaces.router)
app.include_router(maps.router)
app.include_router(formations.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
