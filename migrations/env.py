"""Alembic の実行環境。接続先は GSS_DB_DSN（db.connect が Game の DB であることを確かめる）。"""
from alembic import context
from sqlalchemy import create_engine

from game_signal_scout import db


def run() -> None:
    raw = db.connect(autocommit=True)
    engine = create_engine("postgresql+psycopg://", creator=lambda: raw)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    raw.close()


run()
