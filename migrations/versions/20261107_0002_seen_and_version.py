"""削除への追従と更新の取り直し: 項目を最後に見た配布物（seen_in）と、取得元の版（version）。

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE source_item ADD COLUMN seen_in text, ADD COLUMN version text;
CREATE INDEX source_item_seen ON source_item (source, seen_in);
""")


def downgrade() -> None:
    op.execute("DROP INDEX source_item_seen; ALTER TABLE source_item DROP COLUMN seen_in, DROP COLUMN version")
