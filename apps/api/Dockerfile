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

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
