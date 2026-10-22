from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    analyses,
    branding,
    annotations,
    assets,
    auth,
    autodesk,
    crs,
    dashboard,
    documents,
    files,
    formations,
    grids,
    iot,
    issues,
    maps,
    organization,
    projects,
    push,
    schedule,
    surfaces,
    tokens,
    wells,
)
from app.storage import ensure_bucket

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Best-effort: create the bucket if the object store is reachable. This
    # must never crash app startup (e.g. object store briefly unavailable).
    try:
        ensure_bucket()
    except Exception:
        pass
    yield


app = FastAPI(title="Construction Digital Twin & Subsurface 3D API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Cell-Count", "Content-Length", "Content-Disposition"],
)


app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(files.router)
app.include_router(wells.router)
app.include_router(grids.router)
app.include_router(surfaces.router)
app.include_router(maps.router)
app.include_router(formations.router)
app.include_router(assets.router)
app.include_router(annotations.router)
app.include_router(documents.router)
app.include_router(crs.router)
app.include_router(autodesk.router)
app.include_router(analyses.router)
app.include_router(issues.router)
app.include_router(organization.router)
app.include_router(schedule.router)
app.include_router(dashboard.router)
app.include_router(push.router)
app.include_router(iot.router)
app.include_router(tokens.router)
app.include_router(branding.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
