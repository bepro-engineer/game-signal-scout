"""削除の事実（source_gone）: 取得元で消えた項目・アカウントの、取得元・ID（または投稿者の参照）・消えた時刻・理由。本文は持たない（Anime の §2）。

Revision ID: 0019
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE source_gone (
  source text NOT NULL,
  ref text NOT NULL,
  kind text NOT NULL,
  gone_at timestamptz NOT NULL,
  PRIMARY KEY (source, kind, ref)
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE source_gone")
