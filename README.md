# Game Signal Scout（非公開の試作）

PC・家庭用ゲームのプレイヤーの具体的な発言・報告から、ほかでは見えにくい変化（例: ある更新から遊べなくなった）を見つける試作です。価値の検証と経緯は [Issue #1](https://github.com/bepro-engineer/game-signal-scout/issues/1) が正本です。

**本番の稼働・公開はしていません。** 常駐、定時の起動、公開の画面はありません（Viewer は自分の機械だけで手で動かす）。

## 構成

Anime Signal Scout の基本モデルから、Game に必要な部分だけを移植しています。

| 層 | 場所 | 内容 |
|---|---|---|
| 入口（Controller） | `cli.py`、`web/app.py` | コマンドと 1 行の JSON の出力。Viewer のルート（`/` 変化の一覧、`/games/<appid>` 作品、`/api/…` 文書の JSON、`/healthz`） |
| 画面（View） | `web/templates`、`web/static` | サーバー側で HTML にする（JavaScript なし）。根拠の記述は escape する |
| 運用 | `ops/runner.py` | 段（collect → normalize → analyze → publish）の実行、段ごとの排他、実行の記録（`job_run`）、再試行の可否と終了コード |
| 業務（Service） | `services/`、`publication/`、`web/public_content.py` | 収集（束ごとの保存と続きの位置）、正規化、変化の検出。公開用の文書を作って検査し、表 `public_document` に置き換える（Anime の publishing を移植）。Viewer はその文書を鍵で読むだけ |
| データ（Repository） | `repositories/` | SQL はここだけ |
| 取得元 | `sources/`、`discovery/` | 取得元の契約（`SourceReader`）、記述から作る Factory、節度のある取得（`Fetcher`）、ProtonDB の配布データ、Bluesky。正規化は記述の `normalizer` で選ぶ |
| LLM 枠 | `llm_gate.py` | 共有の部品（scout-infra の `scout_llm_gate`）への接続口。Game は専用の LLM・ロック・常駐を持たない |

- 取得元を足すときに書くのは、`SourceReader` の子クラス、`config/sources.toml` の記述、試験だけです。
- どの段も、何度流しても同じ結果になります。収集は同じ報告を 1 件にし、途中で落ちても続きの位置から読み直します。
- 取得元ごとに、前回の成功から `min_interval_hours` の間は取りに行きません。1 つの取得元が失敗しても、他の取得元は集めます（段としては失敗を返し、再試行に回します）。通信の記録は `source_fetch` に、最後の試行・成功・失敗は `source_state` に残ります。

## 他の Scout との分離

- 環境変数は `GSS_` だけを読みます。Anime の `ASS_DB_DSN` が残っていても使いません。
- 接続できるのは、名前が `game_signal_scout` で始まり、表 `scout_identity` が `game` の DB だけです。
- advisory lock の名前には `game_signal_scout:` を付けます（DB ごとの排他で、他の Scout とは衝突しません）。機械全体で 1 つにする LLM の排他は、共有の LLM 枠を使います。
- PostgreSQL のサーバーは共有し、論理 DB とロールを分ける前提です（本番の DB はまだ作っていません）。

## 取得元

| 取得元 | 条件 |
|---|---|
| ProtonDB の公開配布データ（GitHub `bdefore/protondb-data`） | ODbL 1.0 / DbCL 1.0。本体のサイトは取得しない（robots.txt が AI のクローラーを拒否）。新しい月の配布物を読み終えたら、そこから消えた報告を消す（配布物が保存済みの 9 割より少なければ、壊れた疑いとして消さない） |
| Bluesky（Jetstream。Anime の取得元を移植） | キー不要の公式の live tail。ゲームの文脈の語か Steam のストアのリンクがある投稿だけを保存し、削除・アカウントの停止に追従する。投稿者は HMAC（`init-author-key` で鍵を作る）。**既定は無効**（取りこぼさずに集めるには常駐の受信が要り、Game の常駐は未承認）。作品の同定は正規化で行う（Steam のリンク、または題名の一致。規則は `services/identify.py`） |
| Steam のユーザーレビュー（`GetAppReviews`） | **無効**（`enabled = false`）。利用条件が未解決のため、偽の応答による試験だけ |

`python -m game_signal_scout status` は、段ごとの最後の結果・取得元ごとの件数とデータの鮮度・分析の結果・公開の状態を分けて出します（監視が読む形）。共有の PostgreSQL に Game の DB を作る手順は [docs/database.md](docs/database.md) です（未実行）。

## Viewer

```bash
python -m game_signal_scout daily-run   # 収集 → 正規化 → 分析 → 文書の置き換え
python -m game_signal_scout web         # http://127.0.0.1:8720/
```

- 変化の一覧（遊べなくなった・直った作品）、取得元ごとのデータの鮮度と段の結果、作品ごとの週の推移と、変化の根拠になったプレイヤーの記述を出します。
- 表 `public_document`・`public_build` を読むだけです（Anime と同じ形）。検査に通らなかった回は表を変えず、画面は前の内容のまま「前の内容のまま」と出します。
- 接続のたびに Game の DB であることを確かめます。DB に届かなければ 503 を返します。

## 起動の定義（未反映）

`python -m game_signal_scout launchd` は、daily-run（毎日 6:15）と Viewer の launchd の定義を `runtime/launchd` に書くだけです（Anime の `ops/launchd` の作り方を移植）。launchd への反映は、本番の稼働の承認の後に Anime の反映の処理を移して行います。

## 試験

```bash
pip install -e '.[test]'
pytest
```

DB の試験は、一時の PostgreSQL の管理用の接続 `GSS_TEST_ADMIN_DSN` があるときだけ動きます。毎回 `game_signal_scout_test_<乱数>` を作り、終わったら消します。共有の LLM 枠の試験は、`scout_llm_gate` を読み込めるときだけ動きます。

## 守ること

- 秘密（接続文字列のパスワード、キー）は commit しません。接続先は `GSS_DB_DSN` か `runtime/db.env`（Git の外）に置きます。
- Anime と共有の基盤の本番を変更しません。Game の本番の起動、公開、外部の契約、費用の発生は、本人の承認が必要です。
