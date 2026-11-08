"""作品の属性（game_attribute）: 日本語の UI・字幕・音声、開発元、開発元の国・地域などを、取得元ごとに出典・取得の時刻つきで持つ（#2）。
どの取得元も同じ形（作品・項目・取得元・値）。取得元の項目が消えれば一緒に消える。

Revision ID: 0020
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE game_attribute (
  appid text NOT NULL,
  key text NOT NULL,
  source text NOT NULL,
  item_id text NOT NULL,
  value jsonb NOT NULL,
  fetched_at timestamptz NOT NULL,
  PRIMARY KEY (appid, key, source),
  FOREIGN KEY (source, item_id) REFERENCES source_item (source, item_id) ON DELETE CASCADE
);
CREATE INDEX game_attribute_item ON game_attribute (source, item_id);
""")


def downgrade() -> None:
    op.execute("DROP TABLE game_attribute")
