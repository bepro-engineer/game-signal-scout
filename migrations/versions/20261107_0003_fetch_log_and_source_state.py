"""取得の記録（source_fetch）と、取得元ごとの最後の試行・成功・失敗（取得の間隔の管理と監視に使う）。

Revision ID: 0003
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE source_fetch (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL,
  source text NOT NULL,
  host text NOT NULL,
  endpoint text NOT NULL,
  status int,
  ok boolean NOT NULL,
  ms int,
  bytes bigint,
  error text
);
CREATE INDEX source_fetch_source_ts ON source_fetch (source, ts);

CREATE TABLE source_state (
  source text PRIMARY KEY,
  last_attempt_at timestamptz,
  last_ok_at timestamptz,
  last_error_type text,
  last_error_message text
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE source_state, source_fetch")
