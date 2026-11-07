"""最初の表: Scout の印・取り込んだ項目・続きの位置・実行の記録・正規化した報告・検出した変化。

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE scout_identity (scout text PRIMARY KEY CHECK (scout = 'game'));
INSERT INTO scout_identity VALUES ('game');

CREATE TABLE source_item (
  source text NOT NULL,
  item_id text NOT NULL,
  occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  PRIMARY KEY (source, item_id)
);
CREATE INDEX source_item_occurred ON source_item (source, occurred_at);

CREATE TABLE source_checkpoint (
  source text PRIMARY KEY,
  cursor jsonb NOT NULL,
  updated_at timestamptz NOT NULL
);

CREATE TABLE job_run (
  id bigserial PRIMARY KEY,
  daily_run_id text NOT NULL,
  job text NOT NULL,
  target_day date NOT NULL,
  attempt int NOT NULL,
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  status text NOT NULL CHECK (status IN ('running', 'ok', 'skipped', 'failed', 'locked', 'abandoned')),
  retry_count int NOT NULL DEFAULT 0,
  input_count int,
  output_count int,
  elapsed_seconds double precision,
  retryable boolean,
  error_type text,
  error_message text,
  detail jsonb
);
CREATE INDEX job_run_job_day ON job_run (job, target_day);

CREATE TABLE player_report (
  source text NOT NULL,
  item_id text NOT NULL,
  appid text,
  title text,
  at timestamptz NOT NULL,
  failed boolean NOT NULL,
  config_hash text NOT NULL,
  proton text,
  notes text,
  PRIMARY KEY (source, item_id),
  FOREIGN KEY (source, item_id) REFERENCES source_item (source, item_id) ON DELETE CASCADE
);
CREATE INDEX player_report_at ON player_report (at);

CREATE TABLE shift_event (
  version text NOT NULL,
  side text NOT NULL CHECK (side IN ('fail', 'fix')),
  appid text NOT NULL,
  window_start timestamptz NOT NULL,
  n_key int NOT NULL,
  n_window int NOT NULL,
  share_prev double precision NOT NULL,
  share_window double precision NOT NULL,
  n_prev int NOT NULL,
  item_ids jsonb NOT NULL,
  PRIMARY KEY (version, side, appid, window_start)
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE shift_event, player_report, job_run, source_checkpoint, source_item, scout_identity")
