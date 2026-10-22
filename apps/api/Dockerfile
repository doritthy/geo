FROM python:3.13-slim

# GDAL/GEOS/PROJ runtime libs are pulled in transitively by the rasterio/
# geopandas/pyproj wheels (they bundle their own), and IfcOpenShell's wheel
# bundles OpenCASCADE, so no system geo packages are required. libgomp1 is
# needed by the bundled OpenCASCADE/laszip builds and libexpat1 by the
# rasterio wheel; build-essential covers any
# source builds pip needs to do.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libgomp1 libexpat1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Geoid grids for normal -> ellipsoidal heights (upload option vertical_datum).
# EGM96 (2.7 MB) always; EGM2008 (~80 MB, ~10 cm) with --build-arg WITH_EGM2008=1.
ARG WITH_EGM2008=0
ENV PROJ_GRID_DIR=/opt/proj-grids
RUN mkdir -p /opt/proj-grids \
    && curl -fsSL https://cdn.proj.org/us_nga_egm96_15.tif -o /opt/proj-grids/us_nga_egm96_15.tif \
    && if [ "$WITH_EGM2008" = "1" ]; then curl -fsSL https://cdn.proj.org/us_nga_egm08_25.tif -o /opt/proj-grids/us_nga_egm08_25.tif; fi

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
