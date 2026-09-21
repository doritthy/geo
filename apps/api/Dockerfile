FROM python:3.11-slim

# GDAL/GEOS/PROJ runtime libs are pulled in transitively by the rasterio/
# geopandas wheels (they bundle their own GDAL), so no system GDAL package is
# required here. build-essential covers any source builds pip needs to do.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
