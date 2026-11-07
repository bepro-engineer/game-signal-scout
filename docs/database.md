# Game の論理 DB と権限を、共有の PostgreSQL に作る手順（未実行）

**この手順は本番では実行していません。** 実行には本人の承認が必要です。共有の PostgreSQL のサーバー（インスタンス）は 1 つのまま、Game の論理 DB と専用のロールを足す前提です（Game 専用のサーバーやコンテナは作りません）。秘密（パスワード）はこの文書にも commit にも書きません。

## 作るもの

| 名前 | 種類 | 権限 |
|---|---|---|
| `game_signal_scout` | 論理 DB | 所有者は `gss`。`PUBLIC` の CONNECT を外す |
| `gss` | ロール（ログイン可） | Game の DB の所有者。移行と日次の処理が使う。他の DB には CONNECT できない |
| `gss_viewer` | ロール（ログイン可） | 将来の画面用の読み取り専用。今は作らない（画面がないため） |

名前の規則: 論理 DB は `game_signal_scout` で始め、ロールは `gss` で始めます。Anime の `ass`・`ass_viewer` と重ならないようにします。ロールはクラスタ全体で共有される名前なので、同じ名前を使うと他の Scout の権限やパスワードを上書きします（Issue #1 の監査 R8）。

## 事前の確認（すべて読み取りのみ）

1. 同じ名前の DB とロールがないこと。
   ```sql
   SELECT datname FROM pg_database WHERE datname LIKE 'game_signal_scout%';
   SELECT rolname FROM pg_roles WHERE rolname LIKE 'gss%';
   ```
2. 接続数に余裕があること（Game は日次の処理で最大 3 接続: 本体・段の排他・日の排他）。
   ```sql
   SELECT count(*), current_setting('max_connections') FROM pg_stat_activity;
   ```
3. ディスクの空き。ProtonDB の配布データ全件で約 1.5〜2GB を見込みます（検証の一時 DB の実測で、約 40 万件の保存と正規化が tmpfs 上で 1.8GB）。
4. バックアップの仕組みが新しい DB も対象にすること。共有のバックアップの処理は、途中の DB の失敗で後ろの DB の dump が止まる不具合があります（監査 R9。Anime #69 側の F4 で修正予定）。**修正前に Game の DB を足すと、名前順で後ろになる DB の dump が Anime の失敗で止まり得ます。**
5. `pg_hba.conf`（または `pg_hba.d`）に、`gss` が `game_signal_scout` にだけ接続できる行を足す場所があること。既存の行の書き方に合わせます（中身は監査時点で未確認）。

## 実行（承認後。作業者は PostgreSQL の管理者）

```sql
CREATE ROLE gss LOGIN PASSWORD :'gss_password';   -- 値は対話で入れる。履歴・ファイルに残さない
CREATE DATABASE game_signal_scout OWNER gss;
REVOKE CONNECT ON DATABASE game_signal_scout FROM PUBLIC;
GRANT CONNECT ON DATABASE game_signal_scout TO gss;
```

他の Scout の DB に `PUBLIC` の CONNECT が残っている場合、`gss` から接続できてしまいます。各 DB の `REVOKE CONNECT ... FROM PUBLIC` は Anime 側の判断なので、ここでは確認だけにします。

```sql
SELECT datname, has_database_privilege('gss', datname, 'CONNECT') FROM pg_database WHERE datname NOT IN ('template0', 'template1');
```

接続先は、Game の実行環境の `runtime/db.env`（Git の外）に `GSS_DB_DSN=...` として置きます。続けて、移行を当てます。

```bash
alembic upgrade head
```

## 合否

| 確認 | 合格の条件 |
|---|---|
| 移行 | `alembic current` が最新の版、`scout_identity` が `game` の 1 行 |
| 権限 | `gss` で Anime の DB に接続すると拒否される。`has_database_privilege` が Game の DB だけ真 |
| 誤接続の防止 | `GSS_DB_DSN` の DB 名を Anime の DB にすると、Game の処理が接続の前に止まる（試験 `test_only_game_databases_are_accepted`・`test_refuses_database_of_another_scout` と同じ） |
| 他の Scout への影響 | 作業の前後で、Anime の接続数・日次の結果・バックアップの結果が変わらない |
| バックアップ | 翌朝の dump に `game_signal_scout` が含まれ、他の DB の dump も揃っている |

## 切り戻し

Game の DB にはまだ他から参照されるデータがないので、消せば元に戻ります。

```sql
-- 必要なら先に dump を取る: pg_dump -Fc game_signal_scout > game_signal_scout.dump
DROP DATABASE game_signal_scout WITH (FORCE);
DROP ROLE gss;
```

`pg_hba` に足した行を消し、設定を読み直します。Anime の DB・ロール・設定には触れていないので、Anime 側の切り戻しは不要です。

## 隔離の試験で確かめたこと

一時の PostgreSQL 17（Docker）で、上の作り方に相当する状態（Game の名前の DB・`scout_identity`）を作り、移行・1 周期・再実行・途中の失敗からの再開・削除への追従・保持期限・誤接続の拒否を試験しています（`tests/test_pipeline_db.py`）。本番と同じ PostgreSQL 18 では未確認です。
