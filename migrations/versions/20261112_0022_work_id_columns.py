"""作品の番号の列の名前を work_id に改める（#3 段階 C。ARCHITECTURE §8）。

作品の番号は 2026-11-12 の段階 A・B から、このサイトの作品の番号（game_work）で、1 つの取得元の番号ではない。列の名前をそれに合わせる。
名前の変更だけで、表の中身は書き換えない（行・索引・制約はそのまま付いてくる）。切り戻しは downgrade（名前を戻す）。

Revision ID: 0022
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

TABLES = ("game_profile", "player_post", "game_attribute", "game_insight", "game_activity", "game_upcoming", "game_assets", "player_report", "shift_event")


def upgrade() -> None:
    op.execute("".join(f"ALTER TABLE {t} RENAME COLUMN appid TO work_id;\n" for t in TABLES))


def downgrade() -> None:
    op.execute("".join(f"ALTER TABLE {t} RENAME COLUMN work_id TO appid;\n" for t in TABLES))
