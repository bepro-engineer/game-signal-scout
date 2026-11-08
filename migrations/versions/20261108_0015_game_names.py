"""作品の各言語の題名（Steam のストアの繁体字・簡体字・韓国語の表示名）: game_profile.names（{"zh-Hant": …, "zh-Hans": …, "ko": …}）。
中国語・韓国語の掲示板の発言を、その言語の題名で作品に結び付ける（services/identify）。

Revision ID: 0015
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE game_profile ADD COLUMN names jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE game_profile DROP COLUMN names")
