# Game Signal Scout（非公開の試作）

PC・家庭用ゲームのプレイヤーの声（レビュー・掲示板・SNS など多くの取得元）から、ほかでは見えにくい変化（アップデートの影響・不満・評価の変化・言語圏を越えた広がり）を見つけ、限られた休日に遊ぶゲームを選ぶ材料にする試作です。価値の検証と経緯は [Issue #1](https://github.com/bepro-engineer/game-signal-scout/issues/1) が正本です。

**外への公開はしていません。** 2026-11-08 から Mac mini で動いています（承認済み）: Game の DB は共有の PostgreSQL（VAIO）の `game_signal_scout`、常駐は Viewer（127.0.0.1:8720、自分の機械だけ）、毎日 6:15 の daily-run（`launchd --apply`）。10 分ごとの poll（掲示板の新着）も 2026-11-08 に登録しました。


> **取得元はすべて同列の交換可能な入力で、どれもなくてまったく困らない（外しても残りの取得元だけで動く）。特定の取得元を中心に置かない・目立たせない・個別に名前を挙げて取り上げない**（オーナーの厳命。[CLAUDE.md](CLAUDE.md)）。

## 構成

Anime Signal Scout の基本モデルから、Game に必要な部分だけを移植しています。

| 層 | 場所 | 内容 |
|---|---|---|
| 入口（Controller） | `cli.py`、`web/app.py`・`web/routers/` | コマンド（1 行の JSON）と Viewer のルート（`/`・`/spread.html` などのページ、`/api/days`・`/api/days/<日>`・`/api/pages`・`/api/search`・`/api/soon`・`/api/works/<id>`、`/healthz`） |
| 画面（View） | `web/pages.py`・`web/templates`・`web/static` | Anime の web をそのまま流用（ページの枠は HTML、中身は JS が `/api/…` の文書から組む。日英） |
| 運用 | `ops/` | 段（collect → normalize → observe → analyze → insight → digest → publish）の実行と記録（`job_run`）・排他・再試行、短い間隔の収集（`poll`）・launchd の定義 |
| 業務（Service） | `services/`・`observations.py`・`foundation/`・`signal/`・`publication/`・`ops/dashboard_digest.py`・`web/services/` | 収集・正規化・作品の同定、観測の集計（`obs_*`）と系列、画面の文書（Anime の content を流用）、今日の兆し（共有の LLM）、公開（検査して `public_document` を置き換え） |
| データ（Repository） | `repositories/` | SQL はここだけ（試験 `test_sql_only_in_repositories`） |
| 取得元 | `sources/` | 取得元の契約（`SourceReader`）、記述から作る Factory、節度のある取得（`Fetcher`）、共通の読み方（`feeds.py`）と取得元ごとの読み方 |
| LLM 枠 | `llm_gate.py`・`llm.py` | 共有の部品（scout-infra の `scout_llm_gate`）への接続口。Game は専用の LLM・ロック・常駐を持たない |

設計の詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（構造・取得元の足し方・Anime との境界）、[docs/DESIGN.md](docs/DESIGN.md)（目的・データ・判定と公開の基準）、[docs/OPERATIONS.md](docs/OPERATIONS.md)（動かし方・確かめ方・障害と切り戻し）、[docs/database.md](docs/database.md)（DB を作った手順）です。

- 取得元を足すときに書くのは、`SourceReader` の子クラス、`config/sources.toml` の記述、試験だけです。
- どの段も、何度流しても同じ結果になります。収集は同じ報告を 1 件にし、途中で落ちても続きの位置から読み直します。
- 取得元ごとに、前回の成功から `min_interval_hours` の間は取りに行きません。1 つの取得元が失敗しても、他の取得元は集めます（段としては失敗を返し、再試行に回します）。通信の記録は `source_fetch` に、最後の試行・成功・失敗は `source_state` に残ります。

## 他の Scout との分離

- 環境変数は `GSS_` だけを読みます。Anime の `ASS_DB_DSN` が残っていても使いません。
- 接続できるのは、名前が `game_signal_scout` で始まり、表 `scout_identity` が `game` の DB だけです。
- advisory lock の名前には `game_signal_scout:` を付けます（DB ごとの排他で、他の Scout とは衝突しません）。機械全体で 1 つにする LLM の排他は、共有の LLM 枠を使います。
- PostgreSQL のサーバーは共有し、論理 DB（`game_signal_scout`）とロール（`gss`）を分けています（2026-11-08 に作成。[docs/database.md](docs/database.md)）。

## 取得元

プレイヤーの声は、どれか 1 つの取得元に頼らず、取得元ごとに数えます（人数は取得元をまたいで足しません）。候補の台帳は [config/source_candidates.toml](config/source_candidates.toml)（107 件。ready・needs_key・needs_decision・rejected と、外すための手順）。
足すときに書くのは記述（`config/sources.toml`）だけで済むものが多く、共通の読み方は `sources/feeds.py`（RSS / Atom / RSS 1.0・Discourse・Lemmy・Mastodon・はてなブックマークのコメント）です。

| 種類 | 取得元 |
|---|---|
| 作品ごとのレビュー | Steam のユーザーレビュー（`GetAppReviews`。28 日分そろうまで遡る）・GOG のレビュー |
| 作品の公式の掲示板 | Blizzard（Overwatch 2・Diablo IV。9 言語）・MSFS・EVE Online・War Thunder（英・露）・Funcom・Guild Wars 2・CD PROJEKT RED・Warframe・Stardew Valley・Kerbal Space Program・BeamNG.drive |
| ゲームの総合の掲示板・コミュニティ | NeoGAF・Tildes・Lemmy・Mastodon・GTPlanet・Famiboards（英）、ComputerBase・PCGH・Mein-MMO・PC Games（独）、Gamekult（仏）、ElOtroLado（西）、SpazioGames・Tom's Hardware Italia（伊）、CD-Action（波）、Outer Space・Adrenaline（葡）、PlayUA（宇）、True Gaming（亜）、PTT（繁中）、Keylol・Stage1st（簡中）、Pantip（泰）、ニコニコ大百科の掲示板・ゲームの記事へのはてなブックマークのコメント（日）、Bluesky |
| 作品の情報 | Steam のストア（`appdetails`。画像・ゲーム内容〔日・英〕・ジャンル・遊び方・機種・日本語・発売日・各言語の題名） |
| 規模・これから | Steam の「最も遊ばれているゲーム」・Steam の人気の近日発売（メニューの下の「まもなく発売」） |
| 補助 | ProtonDB の公開配布データ（Linux・Steam Deck の動作） |

- **保留**: Steam の掲示板・ワークショップ・告知へのコメント（Steam の利用規約 4.C に関わるため、オーナーの指示で保留・除外。`steam_discussions` は `enabled = false`）。
- 年齢確認・ログイン・Cloudflare の遮断・robots.txt の禁止があるサイトは、回避して取得しません（台帳に記録）。
- 作品の同定: 作品が決まる取得元（作品の掲示板・レビュー）は取得元で決め、総合の掲示板は本文の題名で決めます（英語などは語の並び、日本語・中国語・韓国語は各言語の題名の部分一致。`services/identify.py`）。
- ゲームでないソフト（Steam のジャンルがユーティリティ・映像や音声の制作など）は作品として出しません（`ops/work.py`）。

`python -m game_signal_scout status` は、段ごとの最後の結果・取得元ごとの件数とデータの鮮度・分析の結果・公開の状態を分けて出します（監視が読む形）。共有の PostgreSQL に Game の DB を作った手順は [docs/database.md](docs/database.md) です（2026-11-08 に実行済み）。

## Viewer

```bash
python -m game_signal_scout daily-run   # 収集 → 正規化 → 観測の集計 → 今日の兆し → 公開
python -m game_signal_scout web         # http://127.0.0.1:8720/
```

- **Anime Signal Scout の画面と層をそのまま流用**しています（観測の集計 `obs_*`・系列・文書 `signal/`・web の JS / CSS / テンプレート）。メニューは Anime のまま（ダッシュボード・世界で広がる・再燃・言語圏の広がり・作品を探す・このサイトについて）に、遊び方の 4 項目（一人（ソロ）で遊べる・協力プレイで遊べる・対戦プレイで遊べる・コントローラで遊べる）を足しました。日本語と英語を切り替えられます。
- **今日の兆し**: Anime の dashboard_digest を流用し、観測の集計に入れているすべての取得元のプレイヤーの声を共有のローカル LLM（`scout_llm_gate`）が読んで、ゲームの話題（アップデートの影響・不満・評価の変化など）を見つけます。見出しは 70 字まで（長い題名は副題を省く）。
- **作品詳細**: あらすじの代わりに「ゲーム内容」（Steam のストアの「このゲームについて」）、話題の動きは取得元ごとに切り替え。
- **まもなく発売**（メニューの下）: Steam の人気の近日発売。発売日が近い作品と、注目の近日発売。
- 画面に出す日は、Game が観測を始めた日から（`config/daily.toml` `[publish] start_day`）。
- 狭い幅（320・390px）から PC（1280px 以上）まで、親の枠を越える要素・横スクロールがないことを DOM で確かめています（Issue #2）。画面は [docs/screenshots](docs/screenshots)。
- 開き方: Mac mini で `http://127.0.0.1:8720/`。ほかの Mac からは `ssh -N -L 8720:127.0.0.1:8720 bepro@mac-mini.tail3744fc.ts.net` を張ったまま、その Mac で `http://127.0.0.1:8720/`。
- 表 `public_document`・`public_build` を読むだけです（Anime と同じ形）。DB に届かなければ 503 を返します。

## 常駐と起動の定義

Anime の `ops/launchd`（agent の形）と `sources/runner` を移植しています。

| 名前 | 起動 | 中身 |
|------|------|------|
| `daily-run` | 毎日 6:15 | collect → normalize → analyze → publish |
| `web` | 常駐 | Viewer（127.0.0.1:8720） |
| `poll` | 10 分ごと（2026-11-08 登録） | `poll`（`poll = true` の掲示板の取得元を collect → 正規化。新着だけを返すフィードの取りこぼしを防ぐ） |

- `python -m game_signal_scout launchd` は定義を `runtime/launchd` に書くだけです（見るため）。
- `python -m game_signal_scout launchd --apply` は `~/Library/LaunchAgents` に書き、変わった・新しい定義を bootout → bootstrap し、一覧にない定義を消します。
- 前提: `runtime/db.env` の `GSS_DB_DSN`（Game の DB）と `init-author-key`。

## 試験

```bash
pip install -e '.[test]'
pytest
```

DB の試験は、一時の PostgreSQL の管理用の接続 `GSS_TEST_ADMIN_DSN` があるときだけ動きます。毎回 `game_signal_scout_test_<乱数>` を作り、終わったら消します。共有の LLM 枠の試験は、`scout_llm_gate` を読み込めるときだけ動きます。

## 守ること

- 秘密（接続文字列のパスワード、キー）は commit しません。接続先は `GSS_DB_DSN` か `runtime/db.env`（Git の外）に置きます。
- Anime と共有の基盤の本番を変更しません。Game の本番の起動、公開、外部の契約、費用の発生は、本人の承認が必要です。
