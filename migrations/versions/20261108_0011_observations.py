"""観測の集計（Anime の schema/observations.sql をそのまま流用。game_signal_scout/observations.py が確定し、画面が読む）。
work_id は Steam の app ID（数）。人数は取得元の中で数え、取得元をまたいで足さない（Anime の ADR 0035）。

Revision ID: 0011
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS obs_work_lang_day (
  source      text NOT NULL,          -- Source（bluesky・ptt …）。人数は Source の中で数え、Source をまたいで足さない（ADR 0035）
  target_day  date NOT NULL,          -- 放送日（JST 3:00〜翌 3:00）
  work_id     bigint NOT NULL,        -- 本番の Work
  lang        text NOT NULL,          -- 言語コード（投稿の言語。zh-Hant など）
  persons     int NOT NULL,           -- その日その言語でその作品について書いた、Source の中の独立した投稿者
  posts       int NOT NULL,           -- 数えた記録の数
  version     text NOT NULL,          -- 集計・判定・同定の版（確定したときの）
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source, target_day, work_id, lang)
);
CREATE INDEX IF NOT EXISTS obs_work_lang_day_day ON obs_work_lang_day (target_day);

-- Source × 日の状態。complete = 確定した値がある（obs_work_lang_day）。incomplete = まだ一度も確定していない（画面は 0 ではなく集計中）。
-- 新しい計算がそろわない（判定待ちなど）ときは、前に確定した値と版を残し、reason と attempted_at だけ更新する
CREATE TABLE IF NOT EXISTS obs_day_state (
  source       text NOT NULL,
  target_day   date NOT NULL,
  state        text NOT NULL,         -- complete / provisional（判定済みの分だけの途中の値）/ incomplete / not_covered（観測の範囲外の日）
  version      text NOT NULL,
  reason       text,                  -- 最後の計算がそろわなかった理由（judgments_pending / fetch_hours …）。そろえば NULL
  detail       jsonb NOT NULL DEFAULT '{}',
  attempted_at timestamptz NOT NULL DEFAULT now(),
  finalized_at timestamptz,           -- 最後に確定した時刻
  PRIMARY KEY (source, target_day)
);

-- 数えた記録（投稿者ごと）。変化の判定のページ（再燃・放送後も熱い・言語圏の広がり）が Source ごとの系列を作る材料（sources/observations.series_set）。
-- 確定のしかたは obs_work_lang_day と同じ（そろった日に置き換え、そろわない日は前の確定を残す）。本文は持たない（head は書き出し 30 字の派生）
CREATE TABLE IF NOT EXISTS obs_post (
  source     text NOT NULL,
  target_day date NOT NULL,
  unit       text NOT NULL,           -- 投稿・発言の識別子（Source の中で一意）
  work_id    bigint NOT NULL,
  lang       text,                    -- 言語コード（言語でないものも含めてそのまま）
  actor      text NOT NULL,           -- 投稿者（Source の中のハッシュ）
  head       text,                    -- 文の書き出し（独立性の検査）
  anime      boolean NOT NULL,        -- アニメとの結びつき
  at         timestamptz,             -- 投稿の時刻
  PRIMARY KEY (source, target_day, unit, work_id)
);
CREATE INDEX IF NOT EXISTS obs_post_day ON obs_post (source, target_day);
""")


def downgrade() -> None:
    op.execute("DROP TABLE obs_post; DROP TABLE obs_day_state; DROP TABLE obs_work_lang_day")
