# Game Signal Scout（非公開の試作）

PC・家庭用ゲームのプレイヤーの具体的な発言・報告から、ほかでは見えにくい変化（例: ある更新から遊べなくなった）を見つける試作です。価値の検証と経緯は [Issue #1](https://github.com/bepro-engineer/game-signal-scout/issues/1) が正本です。

**外への公開はしていません。** 2026-11-08 から Mac mini で動いています（承認済み）: Game の DB は共有の PostgreSQL（VAIO）の `game_signal_scout`、常駐は Viewer（127.0.0.1:8720、自分の機械だけ）と Bluesky の受信、毎日 6:15 の daily-run（`launchd --apply`）。

## 構成

Anime Signal Scout の基本モデルから、Game に必要な部分だけを移植しています。

| 層 | 場所 | 内容 |
|---|---|---|
| 入口（Controller） | `cli.py`、`web/app.py` | コマンドと 1 行の JSON の出力。Viewer のルート（`/` 今週末なにを遊ぶ？、`/games` ゲームを探す、`/games/<appid>` 作品、`/cautions` 買う前の注意、`/about` このサイトについて、`/api/…` 文書の JSON、`/healthz`） |
| 画面（View） | `web/templates`、`web/static` | サーバー側で HTML にする（JavaScript なし）。根拠の記述は escape する。見た目は Anime の明るい UI（白いカード・意味の色・段の見出しの線）を踏襲し、外の文字や画像は読み込まない（Issue #2） |
| 運用 | `ops/runner.py` | 段（collect → normalize → analyze → publish）の実行、段ごとの排他、実行の記録（`job_run`）、再試行の可否と終了コード |
| 業務（Service） | `services/`、`publication/`、`web/public_content.py` | 収集（束ごとの保存と続きの位置）、正規化、変化の検出。公開用の文書を作って検査し、表 `public_document` に置き換える（Anime の publishing を移植）。Viewer はその文書を鍵で読むだけ |
| データ（Repository） | `repositories/` | SQL はここだけ |
| 取得元 | `sources/`、`discovery/` | 取得元の契約（`SourceReader`）、記述から作る Factory、節度のある取得（`Fetcher`）、ProtonDB の配布データ、Bluesky、Steam のストアの作品情報・遊ばれている規模。正規化は記述の `normalizer` で選ぶ（取得元に依らない表: `player_report`・`player_post`・`game_profile`・`game_activity`） |
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
| Steam のストアの作品情報（`store.steampowered.com/api/appdetails`。キー不要・日本語） | 作品を選ぶための項目（画像の URL・短い説明・ジャンル・遊び方・機種・日本語・発売日）→ 表 `game_profile`。対象はプレイヤーの報告・発言・遊ばれている規模の多い作品だけ（最大 150、30 日ごとに取り直し）。画像は複製せず、ブラウザが Steam の配信元から読む。レビューは取らない |
| Steam Web API の「最も遊ばれているゲーム」（`ISteamChartsService/GetMostPlayedGames`。キー不要） | 上位 100 作品の順位・前の週の順位・同時に遊んだ人数の最大 → 表 `game_activity`。遊ばれている規模の目安で、満足度・自分に合うかの根拠にはしない |
| Bluesky（Jetstream。Anime の取得元を移植） | キー不要の公式の live tail。ゲームの文脈の語か Steam のストアのリンクがある投稿だけを保存し、削除・アカウントの停止に追従する。投稿者は HMAC（`init-author-key` で鍵を作る）。**常駐で受信する**（`resident = true`。launchd の `collect-bluesky` が `source-collect --source bluesky` を動かし、日次の collect は読まない）。作品の同定は正規化で行う（Steam のリンク、または題名の一致。規則は `services/identify.py`） |
| Steam のユーザーレビュー（`GetAppReviews`） | **無効**（`enabled = false`）。利用条件が未解決のため、偽の応答による試験だけ |

`python -m game_signal_scout status` は、段ごとの最後の結果・取得元ごとの件数とデータの鮮度・分析の結果・公開の状態を分けて出します（監視が読む形）。共有の PostgreSQL に Game の DB を作った手順は [docs/database.md](docs/database.md) です（2026-11-08 に実行済み）。

## Viewer

```bash
python -m game_signal_scout daily-run   # 収集 → 正規化 → 分析 → 文書の置き換え
python -m game_signal_scout web         # http://127.0.0.1:8720/
```

- 目的は「限られた休日に、自分に合うゲームを選ぶ」こと（Issue #2）。案内は 4 つ: 今週末なにを遊ぶ？（遊び方の入口・いま多く遊ばれているゲーム・プレイヤーの声が届いているゲーム・買う前に知っておきたいこと）／ゲームを探す（遊び方・ジャンル・日本語で絞り込み）／買う前の注意／このサイトについて。
- 作品のページ: 作品の画像と説明 → 自分に合うか、の材料（遊び方・日本語・遊べる機種と Linux の動作の報告・遊ばれている規模）→ 買う前の注意 → プレイヤーの声 → 動作の推移 → まだ分からないこと。
- 根拠のないもの（クリアまでの時間・満足度・向き不向き・推薦）は作らず、「まだ分からないこと」として示します。
- 買う前の注意は、変化ごとに「何が・いつから・どれだけ・その後」を日本語の 1 文で出し、根拠の報告に書かれていた内容を件数つきで並べます（`publication/themes.py`。語の一致で数え、原因は言い切りません）。
- 文書を作るプログラムを替えると、次の回で文書を作り直します（プログラムの指紋を材料の版に含める）。
- 見た目は Anime の現行の画面と同じ枠組み（ヘッダー画像の表示の比率 約 4.8:1・左の案内 210px・本文の 2 列・白い角丸カード・同じ行のカードの高さをそろえる。900px 以下は「メニュー」で開く）。ヘッダーは指定の画像（repo 直下の PNG）から切り出した `web/static/banner*.jpg`。画面の見本と Anime との比較は [docs/screenshots](docs/screenshots)。
- 開き方: Viewer は Mac mini の 127.0.0.1:8720 だけで待ち受けます（外へは出さない）。Mac mini では `http://127.0.0.1:8720/`。
  ほかの Mac からは、Tailscale の SSH のトンネル `ssh -N -L 8720:127.0.0.1:8720 bepro@mac-mini.tail3744fc.ts.net` を張ったまま、その Mac で `http://127.0.0.1:8720/`。
- 表 `public_document`・`public_build` を読むだけです（Anime と同じ形）。検査に通らなかった回は表を変えず、画面は前の内容のまま「前の内容のまま」と出します。
- 接続のたびに Game の DB であることを確かめます。DB に届かなければ 503 を返します。

## 常駐と起動の定義

Anime の `ops/launchd`（agent の形）と `sources/runner` を移植しています。

| 名前 | 起動 | 中身 |
|------|------|------|
| `daily-run` | 毎日 6:15 | collect → normalize → analyze → publish |
| `web` | 常駐 | Viewer（127.0.0.1:8720） |
| `collect-bluesky` | 常駐（異常終了のときだけ起動し直す） | `source-collect --source bluesky`（30 秒ずつ受信して保存。二重起動は 75 で終わり 60 秒後に取り直す。止めの合図で周期の区切りで止まる） |

- `python -m game_signal_scout launchd` は定義を `runtime/launchd` に書くだけです（見るため）。
- `python -m game_signal_scout launchd --apply` は `~/Library/LaunchAgents` に書き、変わった・新しい定義を bootout → bootstrap し、一覧にない定義を消します。
- 前提: `runtime/db.env` の `GSS_DB_DSN`（Game の DB）と `init-author-key`。常駐の受信の生きている印は `runtime/sources/<取得元>.heartbeat`（`status` に出る）。

## 試験

```bash
pip install -e '.[test]'
pytest
```

DB の試験は、一時の PostgreSQL の管理用の接続 `GSS_TEST_ADMIN_DSN` があるときだけ動きます。毎回 `game_signal_scout_test_<乱数>` を作り、終わったら消します。共有の LLM 枠の試験は、`scout_llm_gate` を読み込めるときだけ動きます。

## 守ること

- 秘密（接続文字列のパスワード、キー）は commit しません。接続先は `GSS_DB_DSN` か `runtime/db.env`（Git の外）に置きます。
- Anime と共有の基盤の本番を変更しません。Game の本番の起動、公開、外部の契約、費用の発生は、本人の承認が必要です。
