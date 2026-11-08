"""発言の同定の版（player_post.id_version）: 同定の規則・作品の辞書が変わったら、本文の題名で同定する発言を作り直す（Anime の §5.3・§21）。

Revision ID: 0018
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE player_post ADD COLUMN id_version text")


def downgrade() -> None:
    op.execute("ALTER TABLE player_post DROP COLUMN id_version")
