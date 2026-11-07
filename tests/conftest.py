"""試験の共通部品。

DB の試験は GSS_TEST_ADMIN_DSN（一時の PostgreSQL の管理用の接続。例: postgresql://postgres:pw@127.0.0.1:56057/postgres）が
あるときだけ動く。毎回 game_signal_scout_test_<乱数> の database を作り、移行を当て、終わったら消す。本番の DB には接続しない。
"""
from __future__ import annotations

import io
import json
import os
import secrets
import tarfile
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("GSS_RUNTIME_DIR", tempfile.mkdtemp(prefix="gss-runtime-"))
ADMIN = os.environ.get("GSS_TEST_ADMIN_DSN")
REPO = Path(__file__).resolve().parents[1]
TABLES = ("shift_event", "player_report", "job_run", "source_checkpoint", "source_item", "source_fetch", "source_state")


def make_dump(path: Path, records: list[dict]) -> Path:
    """ProtonDB の配布ファイルと同じ形（tar.gz の中の reports_piiremoved.json）。"""
    data = json.dumps(records, indent=2).encode()
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("reports_piiremoved.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return path


def report(appid: str, ts: int, fail: bool, cfg: int, note: str = "") -> dict:
    return {"app": {"steam": {"appId": appid}, "title": f"Game {appid}"},
            "responses": {"verdict": "no" if fail else "yes", "startsPlay": "yes", "notes": {"verdict": note} if note else {}},
            "systemInfo": {"cpu": f"cpu{cfg}", "gpu": "gpu", "kernel": "6.1", "os": "Linux", "ram": "16 GB"}, "timestamp": ts}


@pytest.fixture(scope="session")
def test_db():
    if not ADMIN:
        pytest.skip("GSS_TEST_ADMIN_DSN がない（一時の PostgreSQL がない）")
    import psycopg
    from psycopg.conninfo import make_conninfo
    name = f"game_signal_scout_test_{secrets.token_hex(4)}"
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    dsn = make_conninfo(ADMIN, dbname=name)
    old = os.environ.get("GSS_DB_DSN")
    os.environ["GSS_DB_DSN"] = dsn
    from alembic import command
    from alembic.config import Config
    acfg = Config(str(REPO / "alembic.ini"))
    acfg.set_main_option("script_location", str(REPO / "migrations"))
    command.upgrade(acfg, "head")
    yield {"dsn": dsn, "name": name, "alembic": acfg}
    if old is None:
        os.environ.pop("GSS_DB_DSN", None)
    else:
        os.environ["GSS_DB_DSN"] = old
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def conn(test_db):
    from game_signal_scout import db
    c = db.connect(test_db["dsn"])
    c.execute("TRUNCATE " + ", ".join(TABLES))
    c.commit()
    yield c
    c.close()
