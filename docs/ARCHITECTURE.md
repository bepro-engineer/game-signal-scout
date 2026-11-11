# 構造（ARCHITECTURE）

Game Signal Scout の構造の正本です。根拠は現行の `main` のコードと試験です。Anime Signal Scout の標準（3 層＋MVC・SourceAdapter / Factory・取得元に依らない共通層）に合わせています（Issue #3）。

> **取得元はすべて同列の交換可能な入力で、どれもなくてまったく困らない（外しても残りの取得元だけで動く）。特定の取得元を中心に置かない・目立たせない・個別に名前を挙げて取り上げない**（オーナーの厳命。[CLAUDE.md](../CLAUDE.md)）。

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
| 作品の属性 | `services/normalize.attributes`・`game_attribute` | 取得元のクラスの `attributes` が共通の形（作品・項目・値）にし、取得元・取得の時刻つきで持つ。画面の値は `ops/work_display.work_attrs`（取得元の名前で分けない） |
| 利用条件 | `source_terms.py`・`config/source_terms.toml` | 取得元ごとの一次資料の記録。禁止が明記された取得元・サイトは取得・集計・公開に入れない。引用は記録で許された取得元だけ |
| 画面に出す取得元 | `config/map_sources.toml` | 記述だけで集計・画面（作品詳細の取得元の切り替え・言語の地図）に入る |

共通の読み方（`sources/feeds.py`）: RSS / Atom / RSS 1.0・Discourse（`/posts.json`）・Lemmy・Mastodon のハッシュタグ・はてなブックマークのコメント。多くの掲示板は記述（URL・作品の app ID・言語）を足すだけです。

### 取得元を足す手順

1. 読み方が共通の形なら、`config/sources.toml` に記述（`adapter`・`normalizer = "…normalize:voices"`・URL）を足す。違う形なら `sources/<名前>.py` に `SourceReader` の子クラスを書く（payload は `author`・`text`・`lang`、作品が決まるなら `appid`）。
2. `config/map_sources.toml` に `[sources.<名前>]`（`reader = "foundation"`・`production = true`・`label = [日本語, 英語]`）を足す。
3. 試験（偽の応答）を足す。共通の処理は変えない。
4. 声の取得元は `resident = true` と `poll_seconds`（取得の間隔）を書く。どの取得元も同じ常駐の収集器（`ops/collector`。Anime の `sources/runner` と同じ。launchd の `collect-<取得元>`）が読む。

**証明**: `tests/test_new_source_extension_db.py` は、試験の中だけで定義した架空の取得元を、記述だけで登録します。そのうえで、共通の処理を 1 行も変えずに、収集 → 正規化 → 同定（取得元で・題名で）→ 観測の集計 → 公開の文書 → 作品詳細の取得元の切り替え → ダッシュボードまで進むことを確かめます。同じファイルで、共通の処理に取得元の名前の文字列がないことも確かめます。

## 3. Anime から流用した部分と Game 独自の部分

| 流用（Anime の現行のコードを名前だけ替えて移した） | Game 独自 |
|---|---|
| 観測の集計（`observations.py`・`repositories/observation.py`・移行 0011） | 発言の共通の表 `player_post`（レビュー・掲示板・SNS）と、その読み方（`read_foundation`） |
| 系列と判定（`foundation/series.py`・`signals.py`・`signal_cards.py`・`config/pages.toml`） | 作品 = ストアの作品番号（app ID。`game_profile`。§7 の構造の不適合）。ゲームでないソフトは作品にしない（`ops/work.py`） |
| 画面の文書（`signal/content.py` ほか）と web（JS・CSS・テンプレート・ルート） | メニューの遊び方 4 項目、作品詳細の「ゲーム内容」、メニューの下の「まもなく発売」（`signal/upcoming.py`） |
| 今日の兆し（`ops/dashboard_digest.py`・`digest_checks.py`・`finding_assess.py`・`job_artifact`） | 話題の種類（アップデート・性能・価格・論争など）と、プレイヤー向けの指示文。見出しの上限 70 字・長い題名は副題を省く |
| 公開（`public_document`・`public_build`・検査） | 取得元（ストアのレビュー・各国の掲示板など）と台帳 `config/source_candidates.toml` |

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
                       insight（共有の LLM）→ game_insight（体験・まとまり・同じ論点の賛否）
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
| **一部 → 2026-11-08 に是正** | 削除の事実を残す（§2: 消えた項目・アカウントを `source_gone` に記録し、本文は消す）、投稿者の参照を鍵付き HMAC に揃える（REQ-TERMS-003: 取得元の hash に `actor_key.keyed`。保存済みの値も同じ計算で置き換え）、同じ書き出しの文の独立性の検査（§10: 記述に `text = stored`）、言語の判定の確信度（§7: 掲示板なども `discovery/lang.detect`、0.8 未満は uncertain）、宣伝・告知・ニュースの印（§4: 全取得元に `flags_for`、`news` を既定で除く）、Retry-After（REQ-SRC-003） |
| 一部（残り） | 失敗の通知（§22。再試行は 2026-11-08 に是正: 日次は `daily-run --retry`）、欠けた日（§0: 取得が続きの位置から再開し、観測を毎日 28 日分作り直すので後から埋まる。ただし新着だけを返すフィードは止まっていた間の分を取れない）、正規化の版（§21。同定の版は 2026-11-08 に是正: `player_post.id_version`、辞書・規則が変われば題名で同定する発言を作り直す）、作品 ID がストアの作品番号そのもの（REQ-WRK-001。そのストアにない家庭用機の作品を扱えない。§7） |
| **オーナーの判断が要る** | 利用条件の門（§3.2・REQ-SRC-002: Anime は条件に合わない取得元を止める。Game はオーナーの方針〔取得してから使うかを決める〕で止めていない）、発言の判定の段（§9・REQ-OBS-012: Game は作品に結び付いた発言をすべて数える）、失敗の通知の経路（REQ-OPS-008） |

## 7. 残っていること（2026-11-11 の最終監査。#3）

- 2026-11-12 に是正（段階 A・B。§8）: 作品の鍵が 1 つのストアの作品番号そのものだった構造を、作品の表と外部の鍵の表を通す形に改めた。試験 `KNOWN_STORE_KEY_FILES` の例外は空にした。
- 取得元の契約の形（Anime の discover・fetch と Game の read）を 1 つにすること（G1。Anime #72 と一緒に決める）。
- 画面の置き場所と反映・切り戻しの仕組み（G7）、監視・通知の共有の仕組み（G8。退避は共有の `scout-backup` が Game の秘密も写す）。共有の基盤（scout-infra）の側と一緒に決める。
- 上の §6 の「一部（残り）」「オーナーの判断が要る」。
- 2026-11-11 に是正: 特定の取得元の報告を中心にした古い公開の文書（`overview`・`game/<appid>`。画面は読まない）と、その部品（`publication/content.py`・`themes.py`）を廃止した。公開の「最新の日」を、その報告の日付から、作った画面の日の一覧の最後に改めた。共通の処理の説明・注釈に残っていた取得元の名前を外し、それを捕まえる試験を足した。画面の部品に残っていた、Anime から流用した外部の作品情報のサービスの段（作品詳細・`extra.js`・`extra.css` の該当部分）を外し、画面の部品にも取得元の名前がないことを試験にした。

## 8. 作品の鍵を取得元に依らない形にする（2026-11-11 計画、2026-11-12 オーナーの承認を受けて段階 A・B を本番に入れた）

**今の形**: 作品の鍵 = 1 つのストアの作品番号（`appid`）。`appid` を持つ表は 13（`game_profile`・`player_post`・`game_attribute`・`game_insight`・`game_activity`・`game_upcoming`・`game_assets`・`player_report`・`shift_event` など）、コードの参照は 29 ファイル・277 行。本番の件数は作品 988・発言 約 81 万・観測 約 44 万（2026-11-11）。画面の作品の URL は `w<番号>`。

**方針（Anime の形に合わせる。最小の変更）**
1. 作品の表 `game_work`（`work_id`）と、外部の鍵の表 `game_work_key`（`key` → `work_id`。例: `store:<作品番号>`、別のストア・家庭用機の取得元の番号、題名の正規化）を足す。Anime の `work`・`work_key`（`repositories/work.py` はすでに `app:<番号>` の鍵の形で流用の部品に答えている）と同じ考え方。
2. **既存の作品は、今の番号をそのまま `work_id` にする**（`store:<番号>` → 同じ番号）。81 万件の発言・44 万件の観測・画面の URL を書き換えない。新しい作品（そのストアにない作品）は、衝突しない別の範囲の番号（例: 10 億から）を使う。
3. 作品の同定（`services/identify`）は、ストアのリンク・取得元の作品の番号・題名を、すべて `game_work_key` を引いて `work_id` にする（特定の取得元の番号を鍵として特別扱いしない）。作品の情報（`game_profile`）は `work_id` を鍵にし、どの取得元の作品の情報でも同じ形で入れられるようにする。
4. 列の名前 `appid` は、意味が `work_id` に変わるだけで値は変えない（名前の変更は後の段階。名前の変更は表の中身を書き換えない操作）。

**段階と切り戻し**
| 段階 | 中身 | 本番への影響 | 切り戻し |
|---|---|---|---|
| A | 移行の追加（表 2 つと番号の連番。既存の作品 988 件の鍵を入れる） | 表を足すだけ。既存の表・行は変えない | 足した表を消すだけ |
| B | コードを `game_work_key` 経由にする（同定・作品の情報・画面の作品の参照）。試験に「そのストアにない作品が、架空の取得元だけで同定され、画面に出る」を足す | 既存の作品は番号が同じなので、画面と URL は変わらない | 前のコードに戻す（表 A は残っていても害がない） |
| C | 試験 `KNOWN_STORE_KEY_FILES` の例外を外し、列の名前を `work_id` に改める | 名前の変更だけ | 名前を戻す |

**入れた形（2026-11-12）**
- 段階 A（移行 0021）: 表 `game_work`（`work_id`）・`game_work_key`（名前空間 `keyspace`・その中の番号 `ext_id` → `work_id`）・連番 `game_work_seq`（10 億から）。既存の 9 つの表にある作品の番号を `game_work` に入れる。発言の同定の方法の値に `link` を足す（既存の値はそのまま許す）。
- 名前空間は取得元の記述（`config/sources.toml`）の `work_keyspace` が決める。作品のページへのリンクの形は記述の `work_link`、作品の画像の配信元（画面の CSP）は記述の `image_hosts`。共通の処理は、どの取得元の記述も同じに読む。
- 既存の作品の鍵は `python -m game_signal_scout adopt-work-keys --keyspace <名前空間>` で一度だけ入れる（今の番号をそのまま作品の番号にする）。
- 段階 B: 正規化（発言・作品の情報・属性・画像・規模・これから発売・動作の報告）は、取得元の番号を名前空間で引いて作品の番号にする（知らない番号は新しい作品）。作品の番号そのものを渡す取得元（このサイトの作品を対象に集める取得元）は `work_id` で渡す。対象の作品を引いて取りに行く取得元は、作品の番号を自分の番号に引き直す（`SourceReader.own_ids`。鍵のない作品は取りに行かない）。
- 新しい作品は、どの取得元から来ても連番の番号（そのストアの新しい作品も同じ。特定の取得元の番号を作品の番号として扱わない）。
- 試験: 架空の家庭用機の目録と掲示板だけで、ほかの取得元にない作品が作品になり、同定・観測の集計・作品詳細の文書まで出る（`test_a_title_known_only_to_a_new_source_becomes_a_work_and_reaches_the_screen`）。`KNOWN_STORE_KEY_FILES` の例外は空。
- 残り（段階 C）: 列の名前 `appid` を `work_id` に改める（表の中身は書き換えない。本番の DB の変更なので、入れる前にオーナーに諮る）。
