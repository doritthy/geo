"""Coordinate reference systems: resolve user input (EPSG / PROJ / WKT) to a
PROJ string the browser (proj4js) can use to show coordinates in the
project's CRS, plus presets relevant for Kazakhstan."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import CrsInfo
from app.security import get_current_user
from app.twin.georef import GeorefError, resolve_crs

router = APIRouter(prefix="/api/crs", tags=["crs"], dependencies=[Depends(get_current_user)])

PRESETS = [
    {"value": "EPSG:4326", "label": "WGS 84 (широта/долгота)"},
    *[{"value": f"EPSG:{32600 + z}", "label": f"WGS 84 / UTM зона {z}N"} for z in range(41, 46)],
    *[
        {"value": f"EPSG:{28400 + z}", "label": f"СК-42 (Пулково 1942) / Гаусс-Крюгер зона {z}"}
        for z in range(8, 16)
    ],
    {"value": "EPSG:3857", "label": "Web Mercator"},
]


@router.get("/presets")
def presets() -> list[dict]:
    return PRESETS


@router.get("/resolve", response_model=CrsInfo)
def resolve(value: str) -> CrsInfo:
    try:
        crs = resolve_crs(value)
    except GeorefError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if crs is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустое значение СК")
    auth = crs.to_authority()
    area = crs.area_of_use
    return CrsInfo(
        input=value,
        name=crs.name,
        code=f"{auth[0]}:{auth[1]}" if auth else None,
        proj4=crs.to_proj4(),
        is_projected=crs.is_projected,
        is_geographic=crs.is_geographic,
        area_of_use=area.name if area else None,
    )
