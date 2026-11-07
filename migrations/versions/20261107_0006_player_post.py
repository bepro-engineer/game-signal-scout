"""プレイヤーの発言（player_post）: 発言の取得元（Bluesky）の投稿を正規化した行。作品は Steam の app ID で同定する（同定できなければ空）。

Revision ID: 0006
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE player_post (
  source text NOT NULL,
  item_id text NOT NULL,
  at timestamptz NOT NULL,
  author text NOT NULL,
  lang text,
  appid text,
  title text,
  matched_by text CHECK (matched_by IN ('steam_link', 'title')),
  flags jsonb NOT NULL DEFAULT '[]',
  text text NOT NULL,
  PRIMARY KEY (source, item_id),
  FOREIGN KEY (source, item_id) REFERENCES source_item (source, item_id) ON DELETE CASCADE
);
CREATE INDEX player_post_appid_at ON player_post (appid, at);
CREATE INDEX player_post_at ON player_post (at);
""")


def downgrade() -> None:
    op.execute("DROP TABLE player_post")
