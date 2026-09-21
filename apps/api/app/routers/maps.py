import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_project_scoped_or_404, project_viewer
from app.models import MapLayer, Project, User
from app.schemas import MapLayerRasterDetail, MapLayerSummary, MapLayerVectorDetail
from app.security import get_current_user
from app.storage import presigned_url

router = APIRouter(tags=["maps"])


@router.get("/api/projects/{project_id}/map-layers", response_model=list[MapLayerSummary])
def list_map_layers(project: Project = Depends(project_viewer), db: Session = Depends(get_db)) -> list[MapLayer]:
    return db.query(MapLayer).filter(MapLayer.project_id == project.id).order_by(MapLayer.name).all()


@router.get("/api/map-layers/{layer_id}")
def get_map_layer(
    layer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    layer: MapLayer = get_project_scoped_or_404(MapLayer, layer_id, db, user)
    if layer.layer_kind == "vector":
        return MapLayerVectorDetail(
            id=layer.id, name=layer.name, layer_kind=layer.layer_kind,
            bounds_geojson=layer.bounds_geojson, geojson=layer.geojson,
        )
    image_url = presigned_url(layer.storage_key) if layer.storage_key else ""
    return MapLayerRasterDetail(
        id=layer.id, name=layer.name, layer_kind=layer.layer_kind,
        bounds_geojson=layer.bounds_geojson, image_url=image_url,
    )
