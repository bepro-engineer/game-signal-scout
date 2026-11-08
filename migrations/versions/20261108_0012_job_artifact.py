"""日ごとの成果物（job_artifact。Anime の schema/tables.sql の定義のまま）: 今日の兆し（ops/dashboard_digest）の保存先。

Revision ID: 0012
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS job_artifact (
  job               text NOT NULL,
  target_day        date NOT NULL,
  input_hash        text NOT NULL,
  generator_version text NOT NULL,
  created_at        timestamptz NOT NULL,
  output            jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (job, target_day, input_hash, generator_version)
);""")


def downgrade() -> None:
    op.execute("DROP TABLE job_artifact")
