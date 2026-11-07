"""設定の読み込み（config/*.toml）と DB の接続先。

接続先の名前の規則（他の Scout の DB へ書かないため）:
- 環境変数は GSS_ だけを読む（Anime の ASS_DB_DSN が残ったシェルでも、それを使わない）。
- database の名前は game_signal_scout で始まるものだけを受け付ける。
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config"
# 実行時の出力先（配布データの一時置き場など。Git の外）。試験は一時ディレクトリに向ける
RUNTIME = Path(os.environ["GSS_RUNTIME_DIR"]) if os.environ.get("GSS_RUNTIME_DIR") else REPO / "runtime"
DB_ENV = REPO / "runtime" / "db.env"
DB_PREFIX = "game_signal_scout"


class WrongDatabaseError(RuntimeError):
    """Game のものでない DB への接続を止めた。"""


def load_toml(name: str) -> dict:
    with open(CONFIG / name, "rb") as f:
        return tomllib.load(f)


def load_daily_config() -> dict:
    """運用の設定。試験などで別の設定を使うときは GSS_DAILY_CONFIG にパスを置く。"""
    p = os.environ.get("GSS_DAILY_CONFIG")
    if p:
        with open(p, "rb") as f:
            return tomllib.load(f)
    return load_toml("daily.toml")


def env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def check_dbname(name: str | None) -> str:
    """Game の DB の名前でなければ止める。"""
    if not name or not name.startswith(DB_PREFIX):
        raise WrongDatabaseError(f"Game の DB ではない: {name!r}（{DB_PREFIX} で始まる名前だけを使う）")
    return name


def db_dsn() -> str:
    """接続先: GSS_DB_DSN、なければ runtime/db.env。GSS_TEST_DATABASE があれば（試験中）database だけを替える。"""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    dsn = os.environ.get("GSS_DB_DSN") or env_value(DB_ENV, "GSS_DB_DSN")
    if not dsn:
        raise RuntimeError("GSS_DB_DSN が見つからない（環境変数か runtime/db.env）")
    test_db = os.environ.get("GSS_TEST_DATABASE")
    if test_db:
        if conninfo_to_dict(dsn).get("dbname") == test_db:
            raise WrongDatabaseError(f"試験の database が本来の接続先と同じ名前: {test_db}")
        dsn = make_conninfo(dsn, dbname=test_db)
    check_dbname(conninfo_to_dict(dsn).get("dbname"))
    return dsn
