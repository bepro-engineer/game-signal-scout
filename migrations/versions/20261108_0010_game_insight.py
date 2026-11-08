"""プレイヤーの声の読み取り（game_insight）: 作品ごとに、AI が最近のプレイヤーの発言から書いた日本語のまとめと根拠の番号（services/insight）。

Revision ID: 0010
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE game_insight (
  appid text PRIMARY KEY,
  generated_at timestamptz NOT NULL,
  model text NOT NULL,
  input_hash text NOT NULL,
  body jsonb NOT NULL
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE game_insight")
