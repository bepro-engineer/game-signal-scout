"""作品の情報にゲーム内容（Steam のストアの「このゲームについて」）を足す: 日本語の文（about_ja）・英語の文（about_en）。作品詳細の「ゲーム内容」に出す。

Revision ID: 0013
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE game_profile ADD COLUMN about_ja text, ADD COLUMN about_en text")


def downgrade() -> None:
    op.execute("ALTER TABLE game_profile DROP COLUMN about_ja, DROP COLUMN about_en")
