"""遊ばれている規模（game_activity）: 作品ごと・日ごとの順位と同時に遊んだ人数の最大。取得元に依らない形。
「どれだけ遊ばれているか」の補助で、満足度・自分に合うかの根拠にはしない（Issue #2）。

Revision ID: 0008
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE game_activity (
  appid text NOT NULL,
  day date NOT NULL,
  source text NOT NULL,
  item_id text NOT NULL,
  rank integer,
  prev_rank integer,
  peak_players integer,
  PRIMARY KEY (appid, day, source),
  FOREIGN KEY (source, item_id) REFERENCES source_item (source, item_id) ON DELETE CASCADE
);
CREATE INDEX game_activity_item ON game_activity (source, item_id);
CREATE INDEX game_activity_day ON game_activity (day);
""")


def downgrade() -> None:
    op.execute("DROP TABLE game_activity")
