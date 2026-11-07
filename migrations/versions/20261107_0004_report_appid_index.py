"""Viewer が作品ごとに報告を読むための索引（player_report の appid と時刻）。

Revision ID: 0004
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX player_report_appid_at ON player_report (appid, at)")


def downgrade() -> None:
    op.execute("DROP INDEX player_report_appid_at")
