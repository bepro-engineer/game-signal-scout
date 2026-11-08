"""これから発売の作品（Anime の「まもなく放送」に当たる）: Steam の人気の近日発売の一覧（game_upcoming。日ごとの順位）と、作品の情報の「発売前」の印（game_profile.coming_soon）。

Revision ID: 0014
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE game_profile ADD COLUMN coming_soon boolean;
CREATE TABLE game_upcoming (
  appid text NOT NULL,
  day date NOT NULL,
  source text NOT NULL,
  item_id text NOT NULL,
  rank integer,
  PRIMARY KEY (appid, day, source),
  FOREIGN KEY (source, item_id) REFERENCES source_item (source, item_id) ON DELETE CASCADE
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE game_upcoming; ALTER TABLE game_profile DROP COLUMN coming_soon")
