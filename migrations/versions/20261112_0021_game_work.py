"""作品の表（game_work）と外部の鍵の表（game_work_key）。作品の鍵を、1 つの取得元の番号に依らない形にする（#3 段階 A。ARCHITECTURE §8）。

- game_work: 作品の番号（work_id）。既存の作品は、今の番号をそのまま作品の番号にする（発言・観測・画面の URL を書き換えない）。
- game_work_key: 取得元の番号の名前空間（keyspace。取得元の記述 work_keyspace）と、その中の番号（ext_id）→ 作品の番号。
  どの取得元の番号も同じ形で引く。特定の取得元の番号を作品の番号として特別扱いしない。
- 新しい作品の番号は、既存と重ならない範囲（10 億から）の連番。
- 既存の表・行は変えない（足すだけ）。発言の同定の方法の値に「link」（作品のページへのリンク。取得元に依らない名前）を足す（既存の値はそのまま許す）。
  切り戻しは downgrade（足した表と連番を消し、値の制約を元に戻す。「link」の行は前の名前に戻す）。
- 既存の作品の鍵は、移行では入れない（どの名前空間の番号かは取得元の記述が決める。ops の adopt-work-keys で入れる）。

Revision ID: 0021
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

TABLES = ("game_profile", "player_post", "game_attribute", "game_insight", "game_activity", "game_upcoming", "game_assets", "player_report", "shift_event")


def upgrade() -> None:
    op.execute("""
CREATE SEQUENCE game_work_seq START 1000000000;
CREATE TABLE game_work (
  work_id text PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE game_work_key (
  keyspace text NOT NULL,
  ext_id text NOT NULL,
  work_id text NOT NULL REFERENCES game_work (work_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (keyspace, ext_id)
);
CREATE INDEX game_work_key_work ON game_work_key (work_id, keyspace);
""")
    op.execute("""
ALTER TABLE player_post DROP CONSTRAINT IF EXISTS player_post_matched_by_check;
ALTER TABLE player_post ADD CONSTRAINT player_post_matched_by_check CHECK (matched_by IN ('steam_link', 'title', 'source', 'link'));
""")
    union = " UNION ".join(f"SELECT appid FROM {t} WHERE appid IS NOT NULL" for t in TABLES)
    op.execute(f"INSERT INTO game_work (work_id) SELECT DISTINCT appid FROM ({union}) x ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.execute("""
UPDATE player_post SET matched_by = 'steam_link' WHERE matched_by = 'link';
ALTER TABLE player_post DROP CONSTRAINT IF EXISTS player_post_matched_by_check;
ALTER TABLE player_post ADD CONSTRAINT player_post_matched_by_check CHECK (matched_by IN ('steam_link', 'title', 'source'));
DROP TABLE game_work_key; DROP TABLE game_work; DROP SEQUENCE game_work_seq;
""")
