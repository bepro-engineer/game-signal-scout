"""作品の画像（Steam のストアの縦長の表紙 library_capsule と横長の帯 library_hero）: game_assets。画面の作品の画像の枠（縦 3:4）と作品詳細の帯に使う。

Revision ID: 0016
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE game_assets (
  appid text PRIMARY KEY,
  source text NOT NULL,
  item_id text NOT NULL,
  capsule_url text,
  hero_url text,
  fetched_at timestamptz NOT NULL,
  FOREIGN KEY (source, item_id) REFERENCES source_item (source, item_id) ON DELETE CASCADE
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE game_assets")
