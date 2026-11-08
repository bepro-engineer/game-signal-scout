"""プレイヤーの発言（player_post）を取得元に依らない形に広げる: 作品が取得元で決まっている発言（レビューなど）の matched_by = 'source'、
肯定・否定（stance）と、書いた時点の遊んだ時間（playtime_minutes。分かる取得元だけ）。

Revision ID: 0009
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE player_post DROP CONSTRAINT IF EXISTS player_post_matched_by_check;
ALTER TABLE player_post ADD CONSTRAINT player_post_matched_by_check CHECK (matched_by IN ('steam_link', 'title', 'source'));
ALTER TABLE player_post ADD COLUMN stance text CHECK (stance IN ('positive', 'negative'));
ALTER TABLE player_post ADD COLUMN playtime_minutes integer;
""")


def downgrade() -> None:
    op.execute("""
ALTER TABLE player_post DROP COLUMN playtime_minutes;
ALTER TABLE player_post DROP COLUMN stance;
DELETE FROM player_post WHERE matched_by = 'source';
ALTER TABLE player_post DROP CONSTRAINT IF EXISTS player_post_matched_by_check;
ALTER TABLE player_post ADD CONSTRAINT player_post_matched_by_check CHECK (matched_by IN ('steam_link', 'title'));
""")
