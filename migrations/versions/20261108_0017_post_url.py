"""発言の公開の URL（player_post.url）: 引用から原投稿へ辿れるようにする（Anime の §8・REQ-EVD-005）。URL を作れない取得元は NULL（引用に link を付けない）。

Revision ID: 0017
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE player_post ADD COLUMN url text")


def downgrade() -> None:
    op.execute("ALTER TABLE player_post DROP COLUMN url")
