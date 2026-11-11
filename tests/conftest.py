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
TABLES = ("game_work_key", "game_work", "source_gone", "game_attribute", "game_assets", "game_upcoming", "obs_post", "obs_work_lang_day", "obs_day_state", "job_artifact", "game_insight", "game_activity", "game_profile", "public_document", "public_build", "shift_event", "player_post", "player_report", "job_run", "source_checkpoint", "source_item", "source_fetch", "source_state")


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



@pytest.fixture
def stub_screen_docs(monkeypatch):
    """画面の文書（day/・days など）を最小の形に差し替える。取得・正規化・ProtonDB の文書の試験で使う
    （画面の文書が作れない公開は止める規則〔Anime の §16.1〕なので、観測のない試験では差し替える）。"""
    from game_signal_scout.signal import publishing as sp
    monkeypatch.setattr(sp, "build_documents", lambda conn, cfg: ({"day/2026-10-31": {}, "days": {"days": []}}, {"audit": []}))



@pytest.fixture(autouse=True)
def _author_key():
    """投稿者の参照の鍵（一時の runtime に作る。取得元の読み方が鍵付きの HMAC をかけるため）。"""
    from game_signal_scout import actor_key
    actor_key.create_key()



KS = "shop"   # 試験の取得元の作品の番号の名前空間（架空の名前。どの取得元の記述も同じ形）


def known_works(conn, ids, keyspace: str = KS) -> None:
    """移行の前からある作品（ARCHITECTURE §8: 既存の作品は、取得元の番号をそのまま作品の番号にする）と同じ状態を、試験の DB に作る。"""
    with conn.transaction():
        for i in ids:
            conn.execute("INSERT INTO game_work (work_id) VALUES (%s) ON CONFLICT DO NOTHING", (str(i),))
            conn.execute("INSERT INTO game_work_key (keyspace, ext_id, work_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (keyspace, str(i), str(i)))
    conn.commit()
