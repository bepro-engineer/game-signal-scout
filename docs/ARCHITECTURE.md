# 構造（ARCHITECTURE）

Game Signal Scout の構造の正本です。根拠は現行の `main` のコードと試験です。Anime Signal Scout の標準（3 層＋MVC・SourceAdapter / Factory・取得元に依らない共通層）に合わせています（Issue #3）。

## 1. 層と依存の向き

```
Controller  cli.py / web/app.py・web/routers/            ← 入口。SQL を書かない
   │
View        web/pages.py・templates・static（Anime の web を流用）  ← 文書（JSON）を表示するだけ。集計・判定をしない
   │
Service     ops/runner（段の実行）
            services/collect・normalize・identify          ← 収集・正規化・作品の同定
            observations.py・foundation/                   ← 観測の集計（obs_*）・系列・判定
            signal/・ops/dashboard_digest・publication/    ← 画面の文書・今日の兆し・公開
            web/services/public_content                    ← 公開した文書を鍵で読む
   │
Repository  repositories/                                  ← SQL はここだけ
   │
DB          PostgreSQL（共有のサーバーの論理 DB game_signal_scout）

取得元      sources/（SourceReader の子クラス）            ← 「どこから・どう読むか」だけ。保存・続きの位置・再試行は services/collect
```

- **SQL は `repositories/` と `db.py` だけ**（試験 `tests/test_new_source_extension_db.py::test_sql_only_in_repositories`）。
- **View は文書を表示するだけ**: 画面の JS は `/api/days|pages|search|soon|works` の文書を組み立てて表示します。人数・判定・文は Service が作ります（`signal/content.py`）。
- Controller はテンプレートとルートだけです（`web/routers/pages.py`・`api.py`）。

## 2. 取得元（SourceAdapter / Factory / 記述）

| 部品 | 場所 | 役割 |
|---|---|---|
| 契約 | `sources/contract.py` | `SourceReader.read(cursor) → Batch(items, cursor)`。`SourceItem(source, item_id, occurred_at, payload, version)` |
| Factory | `sources/factory.py` | 記述（`config/sources.toml` の `adapter = "module:Class"`）からクラスを作る。取得元の名前で分岐しない |
| 共通の収集 | `services/collect.py` | 束ごとに保存（同じ項目は 1 件・版が変われば置き換え）・続きの位置を同じ取引で記録・削除への追従 |
| 共通の正規化 | `services/normalize.py` | 記述の `normalizer` で選ぶ。発言はどの取得元も `voices`（→ `player_post`） |
| 作品の同定 | `services/identify.py` | payload に `appid` があれば取得元で決まる（作品の掲示板・レビュー）。なければ本文の題名（英語などは語の並び、日本語・中国語・韓国語は各言語の題名の部分一致）。`game_only` の取得元は文脈の語を求めない |
| 観測の集計 | `observations.py`（Anime の `sources/observations` の流用） | 取得元 × 日 × 作品 × 言語の独立した投稿者（`obs_work_lang_day`・`obs_post`・`obs_day_state`）。取得元をまたいで人数を足さない |
| 画面に出す取得元 | `config/map_sources.toml` | 記述だけで集計・画面（作品詳細の取得元の切り替え・言語の地図）に入る |

共通の読み方（`sources/feeds.py`）: RSS / Atom / RSS 1.0・Discourse（`/posts.json`）・Lemmy・Mastodon のハッシュタグ・はてなブックマークのコメント。多くの掲示板は記述（URL・作品の app ID・言語）を足すだけです。

### 取得元を足す手順

1. 読み方が共通の形なら、`config/sources.toml` に記述（`adapter`・`normalizer = "…normalize:voices"`・URL）を足す。違う形なら `sources/<名前>.py` に `SourceReader` の子クラスを書く（payload は `author`・`text`・`lang`、作品が決まるなら `appid`）。
2. `config/map_sources.toml` に `[sources.<名前>]`（`reader = "foundation"`・`production = true`・`label = [日本語, 英語]`）を足す。
3. 試験（偽の応答）を足す。共通の処理は変えない。
4. 新着だけを返すフィードは `poll = true`（10 分ごとの `poll`）。

**証明**: `tests/test_new_source_extension_db.py` は、試験の中だけで定義した架空の取得元を、記述だけで登録します。そのうえで、共通の処理を 1 行も変えずに、収集 → 正規化 → 同定（取得元で・題名で）→ 観測の集計 → 公開の文書 → 作品詳細の取得元の切り替え → ダッシュボードまで進むことを確かめます。同じファイルで、共通の処理に取得元の名前の文字列がないことも確かめます。

## 3. Anime から流用した部分と Game 独自の部分

| 流用（Anime の現行のコードを名前だけ替えて移した） | Game 独自 |
|---|---|
| 観測の集計（`observations.py`・`repositories/observation.py`・移行 0011） | 発言の共通の表 `player_post`（レビュー・掲示板・SNS）と、その読み方（`read_foundation`） |
| 系列と判定（`foundation/series.py`・`signals.py`・`signal_cards.py`・`config/pages.toml`） | 作品 = Steam の app ID（`game_profile`）。ゲームでないソフトは作品にしない（`ops/work.py`） |
| 画面の文書（`signal/content.py` ほか）と web（JS・CSS・テンプレート・ルート） | メニューの遊び方 4 項目、作品詳細の「ゲーム内容」、メニューの下の「まもなく発売」（`signal/upcoming.py`） |
| 今日の兆し（`ops/dashboard_digest.py`・`digest_checks.py`・`finding_assess.py`・`job_artifact`） | 話題の種類（アップデート・性能・価格・論争など）と、プレイヤー向けの指示文。見出しの上限 70 字・長い題名は副題を省く |
| 公開（`public_document`・`public_build`・検査） | 取得元（Steam のレビュー・GOG・各国の掲示板など）と台帳 `config/source_candidates.toml` |

Anime のコードへの実行時の依存はありません（`anime_signal_scout` を import しない）。Anime の放送・話数のための項目は、Game では空の値で返します（`catalog/profile.brief` の `status = None` など）。

## 4. 資源の共有と、データの分離

- **共有**: PostgreSQL のサーバー（VAIO。1 つのインスタンス）、ローカル LLM（Ollama。共有の枠 `scout_llm_gate`。`/Users/Shared/scout-infra`）、Mac mini。Game 専用の DB サーバー・LLM・ロックは作りません。
- **分離**: 論理 DB `game_signal_scout`・ロール `gss`・環境変数 `GSS_`・advisory lock の接頭辞 `game_signal_scout:`・launchd の `com.bepro.game-signal-scout.*`・データは `runtime/`（Git の外）。接続のたびに `scout_identity = game` を確かめます（`db.verify_identity`）。

## 5. 処理とデータの流れ

```
取得元（sources/）─collect→ source_item ─normalize→ player_post（発言）／game_profile（作品の情報）／game_activity・game_upcoming
                                                     │
                                       observe → obs_post・obs_work_lang_day・obs_day_state（取得元 × 日 × 作品 × 言語）
                                                     │
                       digest（共有の LLM）→ job_artifact（今日の兆し）
                                                     │
                       publish → public_document（day/<日>・pages・search・soon・work/w<appid>・days）→ Viewer（/api/…）
```

## 6. Anime の設計書（docs/DESIGN.md・REQUIREMENTS.md）との対照（2026-11-08）

Anime の現行の規則のうち、どの Scout にも当てはまるものを、Game の実コードと対照した結果です（アニメの放送・期の 2 層・人の意味品質の確認など、アニメ固有か Anime でも未実装の規則は対象外）。

| 区分 | 項目（Anime の節） |
|---|---|
| 準拠 | 層と取得元の名前で分岐しない（§1）、比較用の時系列の蓄積（§2）、取得元の契約（§3.1）、同じ文の別の投稿者を統合しない（REQ-RAW-005）、発言の単位（§6）、LLM の文の検査（§9.3）、変化の検出・成立の下限・人気と変化の分離（§10）、日の単位（§12）、公開の文書の置き換え（§17.0）、翻訳を判定に使わない（§18）、cache・冪等・再開・二重起動（§19・§20）、実行時のデータと秘密（REQ-OPS-007） |
| **不適合 → 2026-11-08 に是正** | 観測の範囲（§14: 観測を始める前の日は not_covered。`observations.read_foundation`・記述 `history`）、検査に落ちたら公開しない（§16.1: `publication/publishing.build_documents` が画面の文書の検査・作れないときに止める）、作れないときは前のまま（REQ-OPS-006: 例外を握りつぶさない）、引用から原投稿へ（§8: `player_post.url`・`factory.permalink` は https だけ。原投稿へ辿れない発言は作品詳細で引用しない） |
| **一部 → 2026-11-08 に是正** | 同じ書き出しの文の独立性の検査（§10: 記述に `text = stored`）、言語の判定の確信度（§7: 掲示板なども `discovery/lang.detect`、0.8 未満は uncertain）、宣伝・告知・ニュースの印（§4: 全取得元に `flags_for`、`news` を既定で除く）、Retry-After（REQ-SRC-003） |
| 一部（残り） | 欠けた日を後から埋める・失敗の通知（§0・§22。再試行は 2026-11-08 に是正: 日次は `daily-run --retry`）、削除の事実を残す（§2）、正規化・同定の版（§5.3・§21）、投稿者の参照を鍵付き HMAC に揃える（REQ-TERMS-003。掲示板などは鍵のない hash）、作品 ID が Steam の app ID そのもの（REQ-WRK-001。Steam にない家庭用機の作品を扱えない） |
| **オーナーの判断が要る** | 利用条件の門（§3.2・REQ-SRC-002: Anime は条件に合わない取得元を止める。Game はオーナーの方針〔取得してから使うかを決める〕で止めていない）、発言の判定の段（§9・REQ-OBS-012: Game は作品に結び付いた発言をすべて数える）、失敗の通知の経路（REQ-OPS-008） |

## 7. 残っていること（未対応）

- 上の「一部（残り）」と「オーナーの判断が要る」。

- 古い公開の文書（`publication/content.py` の `overview`・`game/<appid>`。ProtonDB の報告の変化）は、まだ作っています。今の Viewer は読みません。消すかどうかは #1（ProtonDB の扱い）とあわせて決めます。
