# 運用（OPERATIONS）

Mac mini で動いています（2026-11-08 から。外への公開はしていません）。DB は共有の PostgreSQL（VAIO）の `game_signal_scout`。接続文字列は `runtime/db.env`（Git の外）だけにあります。

## 1. 動いているもの（launchd。`python -m game_signal_scout launchd --apply` で登録）

| 名前 | 起動 | 中身 | 状態 |
|---|---|---|---|
| `com.bepro.game-signal-scout.daily-run` | 毎日 6:15 | collect → normalize → observe → analyze → insight → digest → publish（`--retry`: 再試行できる失敗は 30 分ごとに 3 回まで） | 動作中 |
| `com.bepro.game-signal-scout.web` | 常駐 | Viewer（127.0.0.1:8720） | 動作中 |
| `com.bepro.game-signal-scout.collect-<取得元>` | 常駐（異常終了のときだけ起動し直す） | ストリームの取得元（`resident = true`）の受信 | 動作中 |
| `com.bepro.game-signal-scout.poll` | 10 分ごと | `poll = true` の掲示板の取得元を collect → 正規化 | 動作中（2026-11-08 オーナーの承認で登録） |

## 2. 確かめ方

```bash
python -m game_signal_scout status        # 段ごとの最後の結果・取得元ごとの件数と鮮度・公開の状態（1 行の JSON）
curl -s http://127.0.0.1:8720/healthz      # Viewer と DB
curl -s http://127.0.0.1:8720/api/days     # 画面に出している日
launchctl list | grep game-signal-scout
```

ログは `runtime/logs/`（`daily-run.launchd.log`・`web.launchd.log`・`collect-<取得元>.launchd.log`・`poll.launchd.log`）です。

## 3. 再試行・再開・障害

- **段**: 失敗すると `job_run` に誤りの種類と再試行の可否を残し、終了コードで返します。同じ日をもう一度流しても同じ結果になります（冪等）。日の排他は advisory lock（`daily:<日>`）です。
- **収集**: 束ごとに続きの位置を同じ取引で記録するので、途中で落ちても続きから読みます。1 つの取得元の失敗で他を止めません。
- **今日の兆し**: 入力の鍵と生成の版（`dashboard_digest.VERSION`）が同じなら作り直しません。規則を変えたら版を上げます。
- **Viewer**: テンプレートやプログラムを変えたら、すぐに起動し直します（`launchctl kickstart -k gui/$(id -u)/com.bepro.game-signal-scout.web`）。
- **作品の情報を一括で取り直すとき**: 版の変わった項目は、正規化の行がいったん消え、次の正規化で作り直されます。日次の処理は取得 → 正規化 → 公開の順なので、欠けたまま公開されることはありません。手で一括に取り直すときも、20 作品ずつ取得してすぐ正規化してください（2026-11-08 に、一括の取り直しの途中で公開して作品が 30 に減ったため）。

## 4. 導入と切り戻し

- 導入: `git pull` → `.venv/bin/alembic upgrade head`（`runtime/db.env` を読み込んで）→ 試験 → Viewer の起動し直し → `daily-run --only publish`。
- 切り戻し: 前の commit に戻して、Viewer を起動し直します。移行は `alembic downgrade <版>` で戻せます（0013 ゲーム内容・0014 近日発売・0015 各言語の題名は、列・表を消すだけ）。
- 取得元を止める: `config/sources.toml` の `enabled = false`（必要なら保存した項目を消す）。画面から外すだけなら `config/map_sources.toml` から外します。

## 5. バックアップ

DB は共有の PostgreSQL のバックアップに含まれます（Game 専用のバックアップは作っていません）。`runtime/` の取得の一時ファイルは作り直せるものだけです。

## 6. 実証済みと未実証

- 実証済み: 日次の各段・Viewer・取得元ごとの収集（手動の 1 回）・試験（一時の PostgreSQL）。
- 未実証: 障害からの自動復旧の実地（試験だけ）、外への公開（していない）。
