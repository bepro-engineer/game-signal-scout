"""作品の情報（game_profile）: 利用者がゲームを選ぶための、取得元に依らない作品の項目（画像・説明・ジャンル・遊び方・機種・日本語・発売日）。
取得元ごとの正規化（config/sources.toml の normalizer）が書く。1 作品 1 行（Steam の app ID）。どの取得元から来たかは source・item_id に残す。

Revision ID: 0007
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE game_profile (
  appid text PRIMARY KEY,
  source text NOT NULL,
  item_id text NOT NULL,
  title text NOT NULL,
  summary text,
  image_url text,
  genres jsonb NOT NULL DEFAULT '[]',
  modes jsonb NOT NULL DEFAULT '[]',
  platforms jsonb NOT NULL DEFAULT '[]',
  ja_text boolean,
  ja_voice boolean,
  released text,
  store_url text,
  fetched_at timestamptz NOT NULL,
  FOREIGN KEY (source, item_id) REFERENCES source_item (source, item_id) ON DELETE CASCADE
);
CREATE INDEX game_profile_item ON game_profile (source, item_id);
""")


def downgrade() -> None:
    op.execute("DROP TABLE game_profile")
