# Subsurface 3D Workspace — API

FastAPI backend for the Subsurface 3D Workspace. Implements
`docs/API_CONTRACT.md` against a real Postgres+PostGIS database and a real
S3-compatible object store (MinIO in production/docker-compose).

## Running via docker-compose (recommended)

From the repo root:

```bash
docker compose up --build
```

This builds the `api` image from this directory, and wires it to the
`postgres` and `minio` services with the env vars in `docker-compose.yml`
(`DATABASE_URL`, `JWT_SECRET`, `S3_*`, `CORS_ORIGINS`). The API listens on
`http://localhost:8000`; interactive docs are at `http://localhost:8000/docs`.
`infra/db/schema.sql` is applied automatically by the `postgres` container on
first start.

## Running standalone (uvicorn)

Requires a reachable Postgres+PostGIS instance (with `infra/db/schema.sql`
applied) and an S3-compatible endpoint (MinIO or similar).

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql://subsurface:subsurface@localhost:5432/subsurface
export JWT_SECRET=change-me
export JWT_EXPIRE_MINUTES=1440
export S3_ENDPOINT_URL=http://localhost:9000
export S3_ACCESS_KEY=subsurface
export S3_SECRET_KEY=subsurface123
export S3_BUCKET=subsurface-data
export CORS_ORIGINS=http://localhost:3000

uvicorn app.main:app --reload --port 8000
```

`DATABASE_URL` may be given as plain `postgresql://...` (as docker-compose
does) — `app/db.py` rewrites it to the `psycopg` (v3) driver internally, so
no `psycopg2` dependency is needed.

## Running tests

```bash
cd apps/api
source .venv/bin/activate
pip install -r requirements-dev.txt   # requirements.txt + moto[server], test-only
pytest
```

`tests/conftest.py` sets up its own **real** test infrastructure per session,
so no manual setup is needed beyond having Postgres reachable:

- Creates an isolated, throwaway Postgres database (`subsurface_test_<random>`)
  on the Postgres server at `TEST_PG_HOST`/`TEST_PG_PORT`
  (default `127.0.0.1:5432`, user/password `subsurface`/`subsurface` —
  override via `TEST_PG_HOST`, `TEST_PG_PORT`, `TEST_PG_USER`,
  `TEST_PG_PASSWORD` if needed) and applies `infra/db/schema.sql` to it via
  `psql`. The database is dropped again at the end of the test session.
- Starts a real S3-compatible HTTP server (`moto`'s server mode, i.e. a real
  process our boto3 client talks to over HTTP — see "Object store in tests"
  below) on a free local port and points `S3_ENDPOINT_URL` at it.
- Every test gets a clean set of tables (`TRUNCATE ... CASCADE` before each
  test) and a fresh `TestClient`.

If Postgres isn't reachable at all, the whole DB-backed suite is skipped
with a clear reason (`pytest.skip`) instead of failing. Tests that need
`rasterio`/`geopandas` (GDAL) additionally skip individually
(`pytest.importorskip`) if those aren't importable in a given environment,
per the effort brief, so a missing optional geospatial dependency doesn't
block the rest of the suite.

### Object store in tests

Genuine MinIO server binaries are no longer published for download (the
upstream project archived its open-source server/client releases), so this
sandbox couldn't install real MinIO to test against. Tests instead run a
real S3-compatible HTTP server via `moto`'s server mode
(`python -m moto.server`) — an actual process listening on a real port that
`boto3`/`app/storage.py` talk to over genuine HTTP, exercising every line of
the real upload/download/presign code path. It is not a mock of any
application code, only a stand-in object-store *implementation* for local
test runs. `docker-compose.yml` is unchanged and still wires the app to real
MinIO for actual deployment.

## Project layout

See `app/` for the FastAPI app (routers, parsers, background job dispatch),
matching `docs/API_CONTRACT.md` and `infra/db/schema.sql` exactly (SQLAlchemy
models in `app/models.py` are a column-for-column match to the schema).
