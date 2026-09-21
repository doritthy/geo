"""Test infrastructure: spins up a real, isolated Postgres database (schema
applied from infra/db/schema.sql) and a real S3-compatible HTTP server
(moto's server mode -- an actual object-store HTTP server our boto3 client
talks to over the network, not a monkeypatch of app code) before the FastAPI
app is ever imported, so every test in the suite exercises the real
SQLAlchemy/psycopg + boto3 code paths end-to-end.

Genuine MinIO server binaries are no longer downloadable (the project
archived binary releases), so moto's server is the closest available
stand-in for local/sandbox test runs; docker-compose still wires the app to
real MinIO for actual deployment. See apps/api/README.md.

If Postgres is not reachable at all in a given environment, the whole DB-
backed suite is skipped with a clear reason rather than failing (e.g. a
minimal CI image with no local Postgres and no docker-compose available).
"""

import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = REPO_ROOT / "infra" / "db" / "schema.sql"
API_ROOT = Path(__file__).resolve().parents[1]

PG_HOST = os.environ.get("TEST_PG_HOST", "127.0.0.1")
PG_PORT = os.environ.get("TEST_PG_PORT", "5432")
PG_ADMIN_USER = os.environ.get("TEST_PG_USER", "subsurface")
PG_ADMIN_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "subsurface")

_TEST_DB_NAME = f"subsurface_test_{uuid.uuid4().hex[:10]}"

_state: dict = {"db_ready": False, "skip_reason": None, "moto_proc": None, "db_url": None}


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _setup_once() -> None:
    if not SCHEMA_SQL.exists():
        _state["skip_reason"] = f"schema.sql not found at {SCHEMA_SQL}"
        return

    # --- Postgres: create an isolated test DB and apply the real schema ---
    try:
        import psycopg

        admin_dsn = (
            f"postgresql://{PG_ADMIN_USER}:{PG_ADMIN_PASSWORD}@{PG_HOST}:{PG_PORT}/postgres"
        )
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    except Exception as exc:  # noqa: BLE001
        _state["skip_reason"] = f"Postgres not reachable for tests ({exc})"
        return

    db_dsn = f"postgresql://{PG_ADMIN_USER}:{PG_ADMIN_PASSWORD}@{PG_HOST}:{PG_PORT}/{_TEST_DB_NAME}"
    try:
        subprocess.run(
            ["psql", db_dsn, "-v", "ON_ERROR_STOP=1", "-f", str(SCHEMA_SQL)],
            check=True, capture_output=True, text=True,
        )
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "stderr", "") or str(exc)
        _state["skip_reason"] = f"Could not apply schema.sql to test DB ({detail})"
        return

    _state["db_url"] = db_dsn

    # --- S3-compatible object store: moto's real HTTP server (see module docstring) ---
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-H", "127.0.0.1", "-p", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(API_ROOT),
    )
    if not _wait_for_port("127.0.0.1", port, timeout=15.0):
        proc.terminate()
        _state["skip_reason"] = "moto S3 test server did not start"
        return
    _state["moto_proc"] = proc

    os.environ["DATABASE_URL"] = db_dsn
    os.environ["JWT_SECRET"] = "test-secret"
    os.environ["JWT_EXPIRE_MINUTES"] = "1440"
    os.environ["S3_ENDPOINT_URL"] = f"http://127.0.0.1:{port}"
    os.environ["S3_ACCESS_KEY"] = "test"
    os.environ["S3_SECRET_KEY"] = "test"
    os.environ["S3_BUCKET"] = "subsurface-data"
    os.environ["CORS_ORIGINS"] = "http://localhost:3000"

    _state["db_ready"] = True


_setup_once()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    proc = _state.get("moto_proc")
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()

    if _state.get("db_ready"):
        try:
            import psycopg

            admin_dsn = f"postgresql://{PG_ADMIN_USER}:{PG_ADMIN_PASSWORD}@{PG_HOST}:{PG_PORT}/postgres"
            with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (_TEST_DB_NAME,),
                )
                conn.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}"')
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(scope="session", autouse=True)
def _require_backend():
    if not _state["db_ready"]:
        pytest.skip(f"Skipping DB-backed test suite: {_state['skip_reason']}")


@pytest.fixture()
def db_session():
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate all app tables before each test so tests are independent."""
    from app.db import engine

    tables = [
        "formations", "map_layers", "surfaces", "grid_properties", "grids",
        "well_logs", "well_markers", "well_trajectory_points", "wells",
        "files", "project_members", "projects", "users", "organizations",
    ]
    with engine.begin() as conn:
        conn.exec_driver_sql(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
