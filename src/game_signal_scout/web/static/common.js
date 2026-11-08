// 画面の共通の部品（全ページ）。表示言語（日本語 / English）、左の案内、作品名・画像・言語の札、日付の表示、作品詳細への行き先。
// 決まり: 作品名は省略しない（全文を折り返す）。色は言語にだけ使う。判定の基準の数字は画面に書かない。URL は日付で変えない。
(() => {
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return v; };
  const sstore = (k, v) => { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } return v; };
  // 表示言語: URL の ?lang=ja|en があればそれ（保存する）。なければ保存した設定。既定は日本語
  const qlang = (() => { try { return new URLSearchParams(location.search).get("lang"); } catch (e) { return null; } })();
  if (qlang === "ja" || qlang === "en") store("ass.lang", qlang);
  const lang = (qlang || store("ass.lang")) === "en" ? "en" : "ja";
  document.documentElement.lang = lang;
  const tr = (ja, en) => (lang === "en" ? en : ja);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const nm = n => (n == null ? "" : typeof n === "string" ? n : (n[lang] || n.ja || n.en || ""));
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const md = s => { if (!s) return ""; const m = +s.slice(5, 7), d = +s.slice(8, 10); return lang === "en" ? `${MON[m - 1]} ${d}` : `${m}/${d}`; };
  const num = n => Number(n || 0).toLocaleString(lang === "en" ? "en-US" : "ja-JP");
  const ppl = n => tr(`${num(n)}人`, `${num(n)} ${n === 1 ? "person" : "people"}`);
  const works = n => tr(`${num(n)}作品`, `${num(n)} ${n === 1 ? "title" : "titles"}`);
  // 作品名: 最大 2 行で、超える分は「…」（CSS の .wn.l1・.wn.l2）。文字は正式名称のまま入れ、title で全文を出す。lines はモックと同じ（1 = 1 行・2 = 2 行）
  const wn = (name, lines = 2, tag = "b") => `<${tag} class="wn l${lines === 1 ? 1 : 2}" title="${esc(nm(name))}">${esc(nm(name))}</${tag}>`;
  // 日本語の対応（#2。日本人が最初に判断する）: 音声 > 字幕 > UI の順に、いちばん深い対応を 1 つの札で。属性がなければ「未確認」（非対応と混ぜない）
  const jpLevel = w => !w || w.jp == null ? "unknown" : w.jp.voice ? "voice" : w.jp.sub ? "sub" : w.jp.ui ? "ui" : "none";
  // 日本語の対応（#2）: 遊びやすさの順に 4 段階。記号は使わず、印そのものに言葉で書く（音声も日本語＝吹き替え／字幕が日本語＝声は外国語／メニューだけ日本語／日本語なし）。
  // 色は強調の紫 1 系統の濃淡で段階の目安だけ。出典は販売元のストアの対応言語の表（凡例の下に書く）
  const JPL = { voice: ["音声も日本語", "Japanese voice"], sub: ["字幕が日本語", "Japanese subtitles"], ui: ["メニューだけ日本語", "Japanese menus only"],
    none: ["日本語なし", "No Japanese"], unknown: ["日本語は未確認", "Japanese unknown"] };
  const jpTag = w => { const k = jpLevel(w); return `<span class="jp jp-${k}">${esc(tr(...JPL[k]))}</span>`; };
  const jpLegend = () => `<div class="jp-legend"><b>${tr("日本語の対応", "Japanese support")}</b>
    <span><span class="jp jp-voice">${tr("音声も日本語", "Japanese voice")}</span>${tr("登場人物が日本語でしゃべる", "characters speak Japanese")}</span>
    <span><span class="jp jp-sub">${tr("字幕が日本語", "Japanese subtitles")}</span>${tr("声は外国語、せりふは日本語の字幕", "foreign voice, Japanese subtitles")}</span>
    <span><span class="jp jp-ui">${tr("メニューだけ日本語", "Japanese menus only")}</span>${tr("せりふは日本語にならない", "dialogue not in Japanese")}</span>
    <small>${tr("販売元がストアに載せている対応言語の表より", "From the publisher's store listing")}</small></div>`;
  // 凡例は必ず付ける（#2）: 日本語の印が出る領域（本文・左の列）ごとに、最初の印より前に凡例がなければ、その印を含む段の前に入れる。
  // 後から足される印（「もっと見る」など）は、同じ領域の先頭の凡例が受け持つ
  const ensureJpLegend = () => document.querySelectorAll("main, .sidecol").forEach(root => {
    const first = [...root.querySelectorAll(".jp")].find(j => !j.closest(".jp-legend")); if (!first) return;
    const lg = root.querySelector(".jp-legend");
    if (lg && (lg.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING)) return;
    if (lg) lg.remove();
    let sec = first; while (sec.parentElement && sec.parentElement !== root) sec = sec.parentElement;
    sec.insertAdjacentHTML("beforebegin", jpLegend()); });
  // 醍醐味の種類（services/insight の appeal_kind と同じ鍵）。体験から言えたときだけ付く
  const APPEAL = { conquer: ["強敵を自力で乗り越える手応え", "Overcoming tough challenges yourself"], explore: ["探して、見つける喜び", "The joy of exploring and finding"],
    story: ["物語と世界に浸る", "Getting lost in the story and world"], grow: ["育てて、作り上げる楽しさ", "Building and growing things"],
    team: ["仲間と作戦が決まる快感", "Teamwork that clicks"], versus: ["相手との読み合い・駆け引き", "Outplaying opponents"],
    feel: ["思いどおりに動かす気持ちよさ", "How good it feels to play"], surprise: ["予想外が起きる面白さ", "Surprises and unexpected play"] };
  // 作品の絵: 場面の画像（スクリーンショット）→ 横長の帯 → ストアのヘッダー → 縦長の表紙。i で場所ごとに別の 1 枚
  const shot = (w, i = 0) => { const xs = (w && w.shots) || []; return xs.length ? xs[i % xs.length] : (w && (w.banner || w.header || w.cover)) || ""; };
  const art = (w, alt) => `<div class="art">${w && w.cover ? `<img src="${esc(w.cover)}" alt="${esc(nm(alt || (w && w.name)))}" referrerpolicy="no-referrer" loading="lazy">` : ""}${w && "jp" in w ? jpTag(w) : ""}</div>`;
  // 開発元と国・地域（出典の記載のとおり。記載がなければ「国・地域は未確認」）
  // 多いときは max 社まで（残りは「ほか N 社」。作品詳細はすべて）
  const devName = w => { const ds = (w && w.dev) || []; return ds.length ? esc(ds[0].n) + (ds.length > 1 ? tr(`ほか${ds.length - 1}社`, ` +${ds.length - 1}`) : "") : ""; };
  const devLine = (w, max = 2) => { const ds = (w && w.dev) || []; if (!ds.length) return tr("開発元は未確認", "Developer unknown");
    const one = d => `${esc(d.n)}${d.c ? `（${esc(d.c.join("・"))}）` : tr("（国・地域は未確認）", " (country unknown)")}`;
    return ds.slice(0, max).map(one).join(tr("、", ", ")) + (ds.length > max ? tr(`ほか${ds.length - max}社`, ` +${ds.length - max} more`) : ""); };
  const workUrl = id => `work.html?id=${encodeURIComponent(id)}`;
  // 体験の観点（#2 6723386003: 固定の分類ではなく、プレイヤーの体験に付く観点。services/insight の style・input と同じ鍵）
  // [鍵, 名前, 英語, 醍醐味の説明, 英語, 体験の値を取る関数]。どの観点も、体験に書いてあったときだけ付く（作品の対応の有無ではない）
  const FACETS = [["solo", "ひとりで遊ぶ醍醐味", "The joy of playing solo", "自力の攻略・探索・没入", "Clearing it yourself, exploring, getting absorbed", f => f.style === "solo"],
    ["coop", "協力プレイの醍醐味", "The joy of co-op", "役割分担・連携が決まる瞬間", "Splitting roles, teamwork that clicks", f => f.style === "coop"],
    ["versus", "対戦の醍醐味", "The joy of versus", "駆け引き・読み合い・上達", "Mind games, reading opponents, getting better", f => f.style === "versus"],
    ["controller", "コントローラーで遊ぶ醍醐味", "The joy of a controller", "手に馴染む操作感", "How it feels in your hands", f => f.input === "controller"]];
  const facetHit = (f, k) => { const x = FACETS.find(y => y[0] === k); return !x || x[5](f); };
  // 変化の判定のページで、2 番目以降に登録した Source の系列で判定された作品の出典（人数はその Source の中の数。ADR 0050）
  const srcNote = w => w.src_label ? `<span class="rv-air">${esc(tr("出典：", "Source: ") + tr(...w.src_label))}</span>` : "";
  // 言語（色は言語にだけ使う）
  // 言語の色（明るく原色を避ける。主な言語圏は互いに見分けられるように。ADR 0049）。ない言語は灰色
  const LC = { ja: "#e07a9a", en: "#6f8fe0", pt: "#57b08a", fr: "#e09a5a", es: "#c58ad8", de: "#8fa0b8", ko: "#5fb8c8", th: "#b8a35f",
    zh: "#e2685f", ar: "#c9a63a", ru: "#7c6fc4", it: "#8cbf5a", tr: "#b8786a", id: "#4fa39a", pcm: "#9fbf6a", nl: "#e0b45a", pl: "#d47fb8",
    uk: "#6aa8d8", vi: "#a3b85f", tl: "#5f9fd0", hi: "#d99a6a", sw: "#6fbf9a", fa: "#b08ad0" };
  const LN = { ja: ["日本語", "Japanese"], en: ["英語", "English"], pt: ["ポルトガル語", "Portuguese"], fr: ["フランス語", "French"], es: ["スペイン語", "Spanish"],
    de: ["ドイツ語", "German"], ko: ["韓国語", "Korean"], th: ["タイ語", "Thai"], it: ["イタリア語", "Italian"], ru: ["ロシア語", "Russian"], uk: ["ウクライナ語", "Ukrainian"],
    cs: ["チェコ語", "Czech"], id: ["インドネシア語", "Indonesian"], ca: ["カタルーニャ語", "Catalan"], fi: ["フィンランド語", "Finnish"], ar: ["アラビア語", "Arabic"],
    tr: ["トルコ語", "Turkish"], el: ["ギリシャ語", "Greek"], pcm: ["ナイジェリア・ピジン語", "Nigerian Pidgin"], zh: ["中国語", "Chinese"], nl: ["オランダ語", "Dutch"],
    pl: ["ポーランド語", "Polish"], sv: ["スウェーデン語", "Swedish"], hu: ["ハンガリー語", "Hungarian"], vi: ["ベトナム語", "Vietnamese"], tl: ["タガログ語", "Tagalog"],
    hi: ["ヒンディー語", "Hindi"], sw: ["スワヒリ語", "Swahili"], fa: ["ペルシア語", "Persian"], ur: ["ウルドゥー語", "Urdu"], ro: ["ルーマニア語", "Romanian"],
    he: ["ヘブライ語", "Hebrew"], bn: ["ベンガル語", "Bengali"], ms: ["マレー語", "Malay"], am: ["アムハラ語", "Amharic"], ha: ["ハウサ語", "Hausa"], yo: ["ヨルバ語", "Yoruba"],
    da: ["デンマーク語", "Danish"], no: ["ノルウェー語", "Norwegian"], bg: ["ブルガリア語", "Bulgarian"], sk: ["スロバキア語", "Slovak"], sr: ["セルビア語", "Serbian"],
    hr: ["クロアチア語", "Croatian"], lt: ["リトアニア語", "Lithuanian"], lv: ["ラトビア語", "Latvian"], et: ["エストニア語", "Estonian"], sl: ["スロベニア語", "Slovenian"] };
  // 文字の区別つきのコード（zh-Hant など）は、元の言語の名前に文字を添える（ない文字は元の言語の名前だけ）
  const ln = c => {
    if (LN[c]) return LN[c][lang === "en" ? 1 : 0];
    const [base, sub] = String(c).split("-"), s = SCRIPT[sub];
    if (!LN[base]) return c;
    return s ? (lang === "en" ? s[1] : `${LN[base][0]}（${s[0]}）`) : LN[base][lang === "en" ? 1 : 0];
  };
  const lcol = c => LC[c] || LC[String(c).split("-")[0]] || "#9aa0b8";
  // o.src: その人数を数えた Source の表記（2 番目以降に登録した Source の言語だけ。人数は Source の中の数。ADR 0050）
  const chip = (c, o = {}) => `<span class="lc${o.add ? " add" : ""}" style="--lc:${lcol(c)}"><i></i>${esc(ln(c))}${o.n != null ? ` <b>${esc(ppl(o.n))}</b>` : ""}${o.src ? `<small>（${esc(tr(...o.src))}）</small>` : ""}${o.mark ? `<sup>${esc(o.mark)}</sup>` : ""}</span>`;   // mark: 出典の説明の印（説明は段の下にまとめる。#36）
  // 作品の情報の言葉（本番の Viewer と同じ）
  const L2 = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v[lang === "en" ? 1 : 0]]));
  const FMT = L2({ tv: ["TV", "TV"], tv_short: ["TV（短編）", "TV short"], movie: ["劇場版", "Movie"], special: ["特別編", "Special"], ova: ["OVA", "OVA"], ona: ["配信（ONA）", "ONA"], music: ["MV", "Music video"], other: ["その他", "Other"] });
  const SEASON = L2({ winter: ["冬", "Winter"], spring: ["春", "Spring"], summer: ["夏", "Summer"], fall: ["秋", "Fall"] });
  const AIR = L2({ airing: ["放送中", "Airing"], releasing: ["放送中", "Airing"], upcoming: ["放送前", "Upcoming"], not_yet_released: ["放送前", "Upcoming"], finished: ["放送終了", "Finished"],
    cancelled: ["中止", "Cancelled"], hiatus: ["休止中", "On hiatus"] });
  const SRC = L2({ original: ["オリジナル", "Original"], manga: ["漫画", "Manga"], light_novel: ["ライトノベル", "Light novel"], novel: ["小説", "Novel"], web_novel: ["Web 小説", "Web novel"],
    visual_novel: ["ノベルゲーム", "Visual novel"], game: ["ゲーム", "Game"], web_manga: ["Web 漫画", "Web manga"], picture_book: ["絵本", "Picture book"], live_action: ["実写", "Live action"], other: ["その他", "Other"] });
  const GENRE = L2({ action: ["アクション", "Action"], adventure: ["冒険", "Adventure"], comedy: ["コメディ", "Comedy"], drama: ["ドラマ", "Drama"], ecchi: ["お色気", "Ecchi"],
    fantasy: ["プレイヤータジー", "Fantasy"], horror: ["ホラー", "Horror"], mahou_shoujo: ["魔法少女", "Magical girl"], mecha: ["ロボット", "Mecha"], music: ["音楽", "Music"],
    mystery: ["ミステリー", "Mystery"], psychological: ["心理", "Psychological"], romance: ["恋愛", "Romance"], sci_fi: ["SF", "Sci-fi"], slice_of_life: ["日常", "Slice of life"],
    sports: ["スポーツ", "Sports"], supernatural: ["超常", "Supernatural"], thriller: ["スリラー", "Thriller"] });
  // 変化の種類（本番の Viewer の TYPES と同じ名前。日ごとの記録の種類 → 名前）
  const KIND = L2({ surge: ["急に増えた", "Sudden jump"], cont: ["増加が続いている", "Keeps growing"], persist: ["増加が続いている", "Keeps growing"],
    new: ["新しく出始めた", "Newly appearing"], emergence: ["新しく出始めた", "Newly appearing"], overseas: ["言語圏が広がった", "New language areas"],
    new_language: ["言語圏が広がった", "New language areas"], re: ["一度静かになって再び増えた", "Quiet, then back"], resurgence: ["一度静かになって再び増えた", "Quiet, then back"] });
  const OBSK = L2({ watch_start: ["見始めた", "Started watching"], watching: ["見ている・見た", "Watching / watched"], source_material_read: ["原作を読んだ", "Read the source"],
    recommend: ["薦めている", "Recommending"], fan_creation: ["作っている", "Making fan works"], share: ["共有している", "Sharing"], sequel_desire: ["続編を望む", "Wants a sequel"],
    complaint: ["不満がある", "Complaints"], desire: ["欲しい・見たい", "Wants / wants to see"], emotion: ["感情を表した", "Feelings"] });

  // 左の案内（全ページ共通）。表示中のページを示す。スマートフォンの幅では上の帯の「メニュー」で開く
  const ICO = {
    index: '<path d="M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>',
    finds: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
    revival: '<path d="M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4"/>',
    postair: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    langspread: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3v18"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    about: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    solo: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/>',
    coop: '<circle cx="8" cy="8" r="3.5"/><circle cx="16.5" cy="9" r="3"/><path d="M2 20c.8-3.5 3.3-5.5 6-5.5s5.2 2 6 5.5M14 15c3 0 5.3 1.6 6.2 5"/>',
    versus: '<path d="M4 4l7 7M20 4l-7 7M6 18l-2 2M18 18l2 2M9 13l-4 4M15 13l4 4"/>',
    pad: '<path d="M7 9h10a4 4 0 0 1 4 4v2a3 3 0 0 1-5.4 1.8L14.5 15h-5l-1.1 1.8A3 3 0 0 1 3 15v-2a4 4 0 0 1 4-4z"/><path d="M8 11.5v3M6.5 13h3"/>' };
  const NAV = [["index", "ダッシュボード", "Dashboard"], ["finds", "見つけた面白さ", "The fun players found"], ["langspread", "言語圏の広がり", "Language spread"], ["solo", "一人（ソロ）で遊べる", "Single-player"], ["coop", "協力プレイで遊べる", "Co-op"],
    ["versus", "対戦プレイで遊べる", "Versus"], ["pad", "コントローラで遊べる", "Controller"], ["search", "作品を探す", "Find titles"], ["about", "このサイトについて", "About"]];
  const page = (location.pathname.split("/").pop() || "index.html").replace(/\.html$/, "") || "index";
  document.documentElement.dataset.page = page;   // ページごとのアクセントの色（palette.css）
  function renderNav() {
    const nav = document.getElementById("nav"); if (!nav) return;
    nav.innerHTML = `${NAV.map(([k, ja, en]) => `<a${k === page ? ' class="on" aria-current="page"' : ""} href="${k}.html"><svg class="i" viewBox="0 0 24 24">${ICO[k]}</svg>${tr(ja, en)}</a>`).join("")}
      <div class="uiloc"><span>${tr("表示言語", "Language")}</span><div class="seg" role="group" aria-label="${tr("表示言語", "Language")}">
        <button type="button" data-lang="ja" class="${lang === "ja" ? "on" : ""}" aria-pressed="${lang === "ja"}">日本語</button>
        <button type="button" data-lang="en" class="${lang === "en" ? "on" : ""}" aria-pressed="${lang === "en"}">English</button></div></div>`;
    const top = document.querySelector("header.top");
    if (top && !document.getElementById("navbtn")) top.insertAdjacentHTML("beforeend", `<button type="button" id="navbtn" class="navbtn" aria-controls="nav" aria-expanded="false">${tr("メニュー", "Menu")}</button>`);
  }
  document.addEventListener("click", e => {
    const b = e.target.closest(".uiloc button[data-lang]"); if (b) { switchLang(b.dataset.lang); return; }   // 表示言語のボタンだけ（地図の国などの印と混ざらないように）
    const m = e.target.closest("#navbtn"); if (m) { const open = document.body.classList.toggle("navopen"); m.setAttribute("aria-expanded", String(open)); return; }
    if (e.target.closest("#nav a[href]")) { try { sessionStorage.removeItem("ass.day"); } catch (err) { /* なし */ } }   // ナビで移ったら公開済みの最新の日から（#48）
  });
  // 作品画像を読み込めなかったときは、画像を外して枠の背景（代わりの表示）を見せる
  document.addEventListener("error", e => { const t = e.target; if (t && t.tagName === "IMG" && t.closest(".art")) { t.closest(".art").classList.add("noart"); t.remove(); } }, true);

  // 表示言語の切り替え: 読み直す前に、画面のいちばん上に見えている段と、その中でどこまで読んでいたかを記録し、
  // 読み直して描き終わったら同じ段の同じ割合の位置に戻す（日英でページの構造は同じ。文章の長さが違っても見ていた段がずれない）。
  // URL の #… と ?lang= は外す（#… は先頭へ飛ばし、?lang= は保存した設定より優先されるため）。メニューを開いていたら開いたまま
  const ANCHOR = "main section, main article, main .card, main li, main h2, main h3, main tr, main .sec-h";
  const anchors = () => [...document.querySelectorAll(ANCHOR)].filter(el => el.getClientRects().length);   // 見えている段だけ（日英の本文を両方持つページの隠れている側を数えない）
  function switchLang(to) {
    if (to === lang) return;
    const els = anchors();
    const i = els.findIndex(el => { const r = el.getBoundingClientRect(); return r.height > 0 && r.bottom > 0; });
    const r = i >= 0 ? els[i].getBoundingClientRect() : null;
    sstore("ass.keep", JSON.stringify({ path: location.pathname, y: scrollY, i, frac: r && r.height ? Math.max(0, -r.top) / r.height : 0, top: r ? Math.max(0, r.top) : 0,
      nav: document.body.classList.contains("navopen") }));
    store("ass.lang", to);
    try { const u = new URL(location.href); u.searchParams.delete("lang"); u.hash = ""; history.replaceState(history.state, "", u.pathname + u.search); } catch (e) { /* そのまま */ }
    location.reload();
  }
  let keep = null;
  try { keep = JSON.parse(sstore("ass.keep") || "null"); } catch (e) { keep = null; }
  if (keep && keep.path === location.pathname) { try { history.scrollRestoration = "manual"; } catch (e) { /* 古いブラウザ */ } } else keep = null;
  try { sessionStorage.removeItem("ass.keep"); } catch (e) { /* なし */ }
  if (keep && keep.nav) document.addEventListener("DOMContentLoaded", () => { document.body.classList.add("navopen"); const m = document.getElementById("navbtn"); if (m) m.setAttribute("aria-expanded", "true"); });
  // ---- 作品詳細から前のページへ戻る（2026-10-12）。Referrer を送らない設定なので、移る前に、このタブの中だけの記録（sessionStorage）に残す ----
  // ass.from: 作品詳細へ移る直前のページ（URL・スクロール位置・ページの状態・移った先の作品）。作品詳細はこれがその作品のときだけ「前のページへ」を出す
  // ass.restore: 「前のページへ」で戻るときに戻す位置と状態。ass.pos:<URL>: ブラウザの戻るで戻ったときに戻す位置と状態
  const KEY = location.pathname.split("/").pop() + location.search;
  let restoring = null;
  try {
    const r = JSON.parse(sstore("ass.restore") || "null");
    if (r && r.key === KEY) restoring = r;
    sessionStorage.removeItem("ass.restore");
    const nav = (performance.getEntriesByType && performance.getEntriesByType("navigation")[0] || {}).type;
    if (!restoring && nav === "back_forward") restoring = JSON.parse(sstore("ass.pos:" + KEY) || "null");
  } catch (e) { restoring = null; }
  if (restoring && !keep) { try { history.scrollRestoration = "manual"; } catch (e) { /* 古いブラウザ */ } }
  const pageState = () => { try { return window.ASS && window.ASS.pageState ? window.ASS.pageState() : null; } catch (e) { return null; } };
  window.addEventListener("pagehide", () => { sstore("ass.pos:" + KEY, JSON.stringify({ key: KEY, y: scrollY, state: pageState() })); });
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("a[href]"); if (!a || page === "work") return;
    const m = /^work\.html\?id=(w\d+)/.exec(a.getAttribute("href") || ""); if (!m) return;
    sstore("ass.from", JSON.stringify({ href: KEY, key: KEY, page, target: m[1], y: scrollY, state: pageState(), at: Date.now() }));
  }, true);
  function fromPage(id) {   // 作品詳細で使う: この作品へ移ったときの記録（6 時間以内）なら返す
    try { const f = JSON.parse(sstore("ass.from") || "null"); return f && f.target === id && Date.now() - f.at < 6 * 3600e3 ? f : null; } catch (e) { return null; }
  }
  function goBack(f) { sstore("ass.restore", JSON.stringify({ key: f.key, y: f.y, state: f.state })); }
  // 描き終わったら呼ぶ（boot.js はページの JS の後、データを使わないページは読み込みの後）。文字の読み込みで高さが変わるので、その後にもう一度
  function restoreScroll() {
    if (!keep && restoring && typeof restoring.y === "number") {
      const y = restoring.y, go = () => window.scrollTo(0, y);
      go(); requestAnimationFrame(go);
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => requestAnimationFrame(go));
      setTimeout(go, 400);
      return;
    }
    if (!keep) return;
    const k = keep, go = () => {
      if (k.y < 2) { window.scrollTo(0, 0); return; }
      const el = k.i >= 0 ? anchors()[k.i] : null;
      if (!el) { window.scrollTo(0, k.y); return; }
      const r = el.getBoundingClientRect();
      window.scrollTo(0, Math.max(0, scrollY + r.top + r.height * k.frac - k.top));
    };
    go(); requestAnimationFrame(go);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => requestAnimationFrame(go));
    setTimeout(() => { go(); keep = null; }, 400);
  }
  // 表示する日の切り替え（ダッシュボード・世界で広がる・言語別）。URL は変えず、選んだ日を覚えて読み直す（boot.js の A.setDay）。
  // 日付の札を押すと月間カレンダーが開く（データのある日だけ選べる。前後の月へ移れる）。横の「最新に戻る」で公開済みの最新の日へ
  function dayBar(el, where = "beforebegin") {   // where: 置く位置（ダッシュボードは紹介のブロックの下 = afterend。2026-10-15）
    const A = window.ASS, B = A.days.built, have = new Set(B), i = B.indexOf(A.day), L = A.days.labels, latest = B.at(-1);
    const lab = d => (L[d] ? L[d][lang] : d);
    const ym = d => d.slice(0, 7), first = ym(B[0]), last = ym(latest);
    const WD = lang === "en" ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] : ["日", "月", "火", "水", "木", "金", "土"];
    const MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const title = m => { const [y, mo] = m.split("-").map(Number); return lang === "en" ? `${MONTH[mo - 1]} ${y}` : `${y}年${mo}月`; };
    const shift = (m, k) => { let [y, mo] = m.split("-").map(Number); mo += k; while (mo < 1) { mo += 12; y--; } while (mo > 12) { mo -= 12; y++; } return `${y}-${String(mo).padStart(2, "0")}`; };
    const pad = n => String(n).padStart(2, "0");
    el.insertAdjacentHTML(where, `<div class="g-daybar${where === "afterend" ? " g-daybar-r" : ""}"><span class="g-dl">${tr("表示している日", "Showing")}</span><span class="daynav g-dn">
      <button type="button" class="rb" data-day="${B[i - 1] || ""}" aria-label="${tr("前日", "Previous day")}"${i > 0 ? "" : " disabled"}>‹</button>
      <span class="dcal-w"><button type="button" class="pill dsel" aria-haspopup="dialog" aria-expanded="false"><span aria-hidden="true">📅</span>${esc(lab(A.day))}<span class="dcar" aria-hidden="true">▾</span></button>
        <div class="dcal" role="dialog" aria-label="${tr("日付を選ぶ", "Choose a date")}" hidden></div></span>
      <button type="button" class="rb" data-day="${B[i + 1] || ""}" aria-label="${tr("翌日", "Next day")}"${i < B.length - 1 ? "" : " disabled"}>›</button>
      <button type="button" class="latest" data-day="${latest}"${A.day === latest ? ' disabled aria-disabled="true"' : ""} title="${esc(lab(latest))}">${tr("最新に戻る", "Back to latest")}</button></span></div>`);
    const bar = where === "afterend" ? el.nextElementSibling : el.previousElementSibling, btn = bar.querySelector(".dsel"), cal = bar.querySelector(".dcal");
    let cur = ym(A.day);
    const draw = () => {
      const [y, mo] = cur.split("-").map(Number), start = new Date(Date.UTC(y, mo - 1, 1)).getUTCDay(), n = new Date(Date.UTC(y, mo, 0)).getUTCDate();
      let cells = "";
      for (let k = 0; k < start; k++) cells += '<span class="dc-e"></span>';
      for (let dd = 1; dd <= n; dd++) {
        const d = `${cur}-${pad(dd)}`, ok = have.has(d), on = d === A.day;
        cells += ok ? `<button type="button" class="dc-d${on ? " on" : ""}${d === latest ? " lt" : ""}" data-day="${d}" aria-label="${esc(lab(d))}"${on ? ' aria-current="date"' : ""}>${dd}</button>`
          : `<span class="dc-d off" aria-hidden="true">${dd}</span>`;
      }
      cal.innerHTML = `<div class="dc-h"><button type="button" class="dc-m" data-m="-1" aria-label="${tr("前の月", "Previous month")}"${cur <= first ? " disabled" : ""}>‹</button>
        <b>${title(cur)}</b><button type="button" class="dc-m" data-m="1" aria-label="${tr("次の月", "Next month")}"${cur >= last ? " disabled" : ""}>›</button></div>
        <div class="dc-g">${WD.map((w, k) => `<span class="dc-w${k === 0 ? " su" : k === 6 ? " sa" : ""}">${w}</span>`).join("")}${cells}</div>
        <p class="dc-n">${tr("色の付いた日を選べます（データのある日）", "Highlighted days have data")}</p>`;
    };
    const open = v => { cal.hidden = !v; btn.setAttribute("aria-expanded", String(v)); if (v) { cur = ym(A.day); draw(); (cal.querySelector(".dc-d.on") || cal.querySelector("button")).focus(); } };
    btn.addEventListener("click", e => { e.stopPropagation(); open(cal.hidden); });
    cal.addEventListener("click", e => { e.stopPropagation();
      const m = e.target.closest(".dc-m"); if (m && !m.disabled) { cur = shift(cur, +m.dataset.m); draw(); return; }
      const d = e.target.closest(".dc-d[data-day]"); if (d) A.setDay(d.dataset.day); });
    document.addEventListener("click", () => { if (!cal.hidden) open(false); });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && !cal.hidden) { open(false); btn.focus(); } });
    bar.addEventListener("click", e => { const b = e.target.closest(".rb[data-day], .latest[data-day]"); if (b && b.dataset.day && !b.disabled) A.setDay(b.dataset.day); });
  }
  // 今日の兆しの文章の組版（6 ページ共通。文章は変えない）: 1 文目を見出し（そのページで注目すること）、残りを読みやすい段落に。
  // 数字（% ・人・作品・日）を強める。作品名（『』の太字）はそのまま。タグを壊さないよう、文の区切りはタグの外の「。」「. 」だけで切る
  function shapeDigest(p, opt = {}) {
    if (!p || p.dataset.shaped) return; p.dataset.shaped = "1";
    const html = p.innerHTML.trim(), out = [], re = lang === "en" ? /(\.)(\s+)(?=[A-Z“"<])/g : /(。)/g;
    let depth = 0, last = 0, q = 0, dq = false;   // q・dq: 引用（「」・"…"）の中か（opt.quotes のときだけ。引用の中の句点で文を分けない）
    for (let i = 0; i < html.length; i++) {
      const c = html[i];
      if (c === "<") depth++; else if (c === ">") depth--;
      if (opt.quotes && depth === 0) {
        if (c === "「") q++; else if (c === "」") q = Math.max(0, q - 1);
        else if (c === "“") q++; else if (c === "”") q = Math.max(0, q - 1);
        else if (html.startsWith("&quot;", i)) dq = !dq;
        if (q > 0 || dq) continue;
      }
      if (depth === 0 && (lang === "en" ? (c === "." && /\s/.test(html[i + 1] || "") && (opt.quotes ? /[A-Z\d“"<&]/ : /[A-Z“"<]/).test((html.slice(i + 1).trimStart())[0] || "")) : c === "。")) { out.push(html.slice(last, i + 1).trim()); last = i + 1; }
    }
    if (html.slice(last).trim()) out.push(html.slice(last).trim());
    const em = t => t.replace(/(?<![\w>])(\d[\d,.]*(?:\s?[〜–-]\s?\d[\d,.]*)?\s?(?:%|％|人|作品|日|言語|people|title\(s\)|titles?|day\(s\)|days?|languages?))/g, '<strong class="dg-num">$1</strong>');
    // 英語の 1 文目が長いとき（コロン・セミコロンで続く）は、そこまでを見出しにし、残りを本文の先頭へ
    // 生成した文の区切りがあれば、それを使う（「。」で数え直さない。引用の後で 1 文を 2 段落に分けない）
    let given = null; try { given = p.dataset.sents ? JSON.parse(p.dataset.sents) : null; } catch (e) { given = null; }
    if (given && given.length) out.splice(0, out.length, ...given.map(t => esc(t).replace(/『([^』]+)』/g, (_, n) => `<b class="nb">『${n}』</b>`)));
    if (lang === "en" && out.length && out[0].replace(/<[^>]+>/g, "").length > 110) { const m = /^(.*?[:;])\s+(.*)$/s.exec(out[0]); if (m && m[1].replace(/<[^>]+>/g, "").length > 30) { out.splice(0, 1, m[1].replace(/[:;]$/, "."), m[2][0].toUpperCase() + m[2].slice(1)); } }
    if (out.length <= 1 && !opt.lead) { p.innerHTML = em(html); p.classList.add("dg-shaped"); return; }
    const lead = opt.lead === false ? null : out.shift(), body = out;
    const paras = []; for (let i = 0; i < body.length; i += 2) paras.push(body.slice(i, i + 2).join(lang === "en" ? " " : ""));
    const box = document.createElement("div"); box.className = "dg-text";
    box.innerHTML = (lead ? `<p class="dg-lead">${em(lead)}</p>` : "") + paras.map(x => `<p class="dg-para">${em(x)}</p>`).join("");
    if (p.id) box.id = p.id;
    p.replaceWith(box);
  }
  // 観測の範囲（地図の色とは別に説明する。ADR 0047）: 話題の作品の根拠が 1 つの文字（繁体字・簡体字）の投稿だけのとき、その言語の色が言語圏全体の目安であることと分けて書く
  const SCRIPT = { Hant: ["繁体字", "Traditional Chinese"], Hans: ["簡体字", "Simplified Chinese"] };
  const scopeNote = l => {
    const sc = ((l && l.scope) || {}).scripts || [];
    if (sc.length !== 1 || !SCRIPT[sc[0]]) return "";
    const [ja, en] = SCRIPT[sc[0]];
    return tr(`${ln(l.code)}は、この日、${ja}の投稿だけを観測しました。地図の色は${ln(l.code)}圏全体の目安で、色の付いた国・地域で投稿があったことを示すものではありません。`,
      `For ${ln(l.code)}, only posts in ${en} were observed on this day. The map color shows the ${ln(l.code)}-language area as a whole, not where posts were made.`);
  };
  // 観測が届いていない言語圏の、止まっている段の説明と直近 7 日の件数（web/area_input._thin_areas。人気・関心の低さではない）
  const THIN_STAGE = { collection_stopped: ["収集が止まっています", "Collection has stopped"],
    no_posts: ["この言語の投稿は、このサイトの観測源にまだ集まっていません", "Posts in this language have not yet reached this site's sources"],
    no_anime: ["この言語の投稿は集まっていますが、ゲームの投稿はまだ見つかっていません", "Posts are collected, but no game posts have been found yet"],
    not_identified: ["ゲームの投稿はありますが、作品をまだ特定できていません", "There are game posts, but the titles are not yet identified"],
    below_condition: ["作品を特定できた投稿はありますが、同じ日に同じ作品を書いた人が 2 人に届いていません", "Some titles are identified, but no title reached 2 people on the same day"] };
  const thinNote = t => t ? { stage: tr(...(THIN_STAGE[t.stage] || ["観測が十分ではありません", "Not well observed"])),
    counts: tr(`直近 7 日: 集まった投稿 ${t.collected7}・ゲームの投稿 ${t.anime7}・作品を特定できた投稿 ${t.identified7}`,
      `Last 7 days: ${t.collected7} posts collected, ${t.anime7} about games, ${t.identified7} with an identified title`) } : null;
  // 今日の兆しの引用（出典。ADR 0052）: 文章とは分け、言語・読者の言語の訳・原文・投稿へのリンクを 1 行ずつ。読者の言語の原文は訳を付けない
  const CITE_ROLE = { for: ["一方の意見", "One side"], against: ["もう一方の意見", "The other side"], contrast: ["違う方向の声", "A different view"], also: ["ほかの論点", "Another point"] };
  const cites = list => !list || !list.length ? "" : `<ul class="dg-cites" aria-label="${tr("プレイヤーの声（原文）", "Fan posts (original)")}">${list.map(c => {
    const role = CITE_ROLE[c.role] ? `<span class="ct-r">${esc(tr(...CITE_ROLE[c.role]))}</span>` : "";
    const orig = c.url ? `<a class="ct-o" href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.quote)}</a>` : `<span class="ct-o">${esc(c.quote)}</span>`;
    const lang = c.lang ? `<span class="ct-l" style="--lc:${lcol(c.lang)}">${esc(ln(c.lang))}</span>` : "";   // 言語が分からない引用は言語の札を出さない（#41）
    return `<li>${lang}${role}${c.meaning ? `<span class="ct-m">${tr(`「${esc(c.meaning)}」`, `“${esc(c.meaning)}”`)}</span>${orig}` : orig.replace('class="ct-o"', 'class="ct-o ct-own"')}</li>`; }).join("")}</ul>`;
  // 長い一覧: 最初の first 件だけを描き、「もっと見る」を押すたびに step 件ずつ足す（描いていない行は DOM に置かない。高さで切って隠さない。Issue #16）。
  // box: 行を入れる要素（display: contents の .more-box なら、親の一覧の並び・間隔はそのまま）。ボタンは box のすぐ後ろ。件数は config/pages.toml [display]
  // label(rest): ボタンの文言（省略時は「もっと見る（残り N 作品）」）。first = 0 なら区分ごと畳む
  // 長い一覧: 初めの first 件を描き、残りは「もっと見る」で step 件ずつ足す。全部を開いたら「閉じる」で初めの件数に戻す（#24。描いていない行は DOM に置かない）
  const moreList = (box, rows, first, step = first, label = null) => {
    let n = 0;
    const row = document.createElement("div"); row.className = "more-row"; box.after(row);
    const btn = () => { const rest = rows.length - n;
      row.innerHTML = rest ? `<button type="button" data-act="more" aria-expanded="false">${label ? label(rest) : tr(`もっと見る（残り${num(rest)}作品）`, `Show more (${num(rest)} left)`)}</button>`
        : rows.length > first ? `<button type="button" data-act="less" aria-expanded="true">${tr("閉じる", "Show less")}</button>` : "";
      if (!row.innerHTML) row.remove(); };
    const add = k => { box.insertAdjacentHTML("beforeend", rows.slice(n, n + k).join("")); n = Math.min(rows.length, n + k); btn(); };
    row.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.act === "less") { box.innerHTML = ""; n = 0; add(first); row.querySelector("button")?.focus(); row.scrollIntoView({ block: "nearest" }); }
      else { add(step); row.querySelector("button")?.focus(); } });
    add(first);
  };
  // 醍醐味の部品（トップ・プレイヤーの発見で共通。#2）: 絵 → 醍醐味の一文 → 根拠（何をして → 何が起きたか）→ 人数・日本語の順。原文は出さない
  const VJ = { fun: ["面白い", "Fun"], mixed: ["賛否あり", "Mixed"], frustration: ["不満", "Frustrating"] };
  const CJ = { time: ["時間がかかる", "Takes time"], price: ["価格・課金", "Price"], performance: ["動作が重い", "Performance"], bugs: ["不具合", "Bugs"], difficulty: ["難しい", "Difficulty"], online: ["接続・対戦相手", "Online"] };
  // 醍醐味つきの体験の一覧（複数の人のまとまり ＋ ひとりの体験）。人数の多い順、同じなら面白いを先に
  const appealItems = FI => FI.flatMap(w => [
    ...w.finds.filter(f => f.appeal).map(f => ({ w, appeal: f.appeal, kind: f.appeal_kind, verdict: f.verdict, people: f.people, ev: (f.examples || [])[0] || {}, caution: f.caution, trend: f.trend,
      against: f.verdict === "fun" ? f.frustration : f.verdict === "frustration" ? f.fun : 0, style: f.style, input: f.input })),
    ...w.singles.filter(e => e.appeal).map(e => ({ w, appeal: e.appeal, kind: e.appeal_kind, verdict: e.verdict, people: 1, ev: e, caution: e.caution, against: 0, style: e.style, input: e.input }))])
    .sort((a, b) => b.people - a.people || (a.verdict === "fun" ? 0 : 1) - (b.verdict === "fun" ? 0 : 1));
  const pplWrote = n => n > 1 ? tr(`${num(n)}人が同じことを書いた`, `${num(n)} players wrote the same`) : tr("1人の体験（まだ重なる声なし）", "One player (not yet echoed)");
  const evLine = ev => ev && ev.did ? `<b>${esc(ev.did)}</b> → ${esc(ev.happened)}` : "";
  const dHero = x => `<section class="dh"><img src="${esc(shot(x.w, 0))}" alt="" referrerpolicy="no-referrer">
      <div class="dh-in"><span class="dh-k">${tr("いま、プレイヤーが夢中になっていること", "What players are into right now")}</span>
        <h1>${esc(x.appeal)}</h1><p class="dh-g">${tr(`<b>${esc(nm(x.w.name))}</b> を遊んだプレイヤーの体験から`, `From players of <b>${esc(nm(x.w.name))}</b>`)}</p>
        <p class="dh-ev">${evLine(x.ev)}</p>
        <div class="dh-m"><span class="dh-p">${pplWrote(x.people)}</span><a class="dbtn" href="${workUrl(x.w.id)}">${tr("この作品の体験を見る", "See this title")}</a></div></div></section>`;
  const dKinds = (items, href) => { const ks = Object.keys(APPEAL).map(k => ({ k, xs: items.filter(x => x.kind === k) })).filter(x => x.xs.length).sort((a, b) => b.xs.length - a.xs.length);
    return ks.length ? `<div class="dk">${ks.map(({ k, xs }, i) => `<a class="dk-t" href="${href(k)}"><img src="${esc(shot(xs[0].w, i + 1))}" alt="" referrerpolicy="no-referrer" loading="lazy">
      <div><b>${esc(tr(...APPEAL[k]))}</b><small>${[...new Set(xs.map(x => nm(x.w.name)))].slice(0, 2).map(esc).join(tr("・", ", "))}${tr(`　体験 ${num(xs.length)}件`, ` · ${num(xs.length)}`)}</small></div></a>`).join("")}</div>` : ""; };
  const dCard = (x, i) => `<a class="dc" href="${workUrl(x.w.id)}"><img src="${esc(i ? shot(x.w, i + 3) : (x.w.header || shot(x.w, 0)))}" alt="" referrerpolicy="no-referrer" loading="lazy">
      <div class="dc-in"><span class="dc-g">${esc(nm(x.w.name))}</span><h3>${esc(x.appeal)}</h3><p>${evLine(x.ev)}</p>
        <div class="dc-f"><span class="dc-v dc-v-${esc(x.verdict)}">${esc(tr(...VJ[x.verdict]))}</span><span>${pplWrote(x.people)}</span>
          ${x.against ? `<span class="dc-w">${tr(`反対の声 ${num(x.against)}人`, `${num(x.against)} disagreed`)}</span>` : ""}
          ${x.caution ? `<span class="dc-w">${tr("注意: ", "Note: ")}${esc(tr(...CJ[x.caution]))}</span>` : ""}${jpTag(x.w)}</div></div></a>`;
  const discover = { items: appealItems, hero: dHero, kinds: dKinds, card: dCard, VJ, CJ, pplWrote, evLine };
  window.ASS = Object.assign(window.ASS || {}, { moreList, cites, srcNote, thinNote, scopeNote, shapeDigest, lang, tr, esc, nm, md, num, ppl, works, wn, art, jpLevel, jpTag, devLine, devName, discover, ensureJpLegend, workUrl, FACETS, facetHit, jpLegend, APPEAL, shot, LC, LN, ln, lcol, chip, FMT, SEASON, AIR, SRC, GENRE, KIND, OBSK, page,
    renderNav, store, sstore, dayBar, restoreScroll, fromPage, goBack, restoring });
  renderNav();
  // まもなく発売（メニューの下の枠。Anime の「まもなく放送」に当たる。signal/upcoming.py・接続口 api/soon）:
  // 発売日が近い作品（日付の順。過ぎた日は開いた時点の日本時間の暦で外す）と、Steam で注目の近日発売（発売日が月・四半期・未定）
  (async () => {
    const el = document.getElementById("soon"); if (!el) return;
    let S; try { const r = await fetch("api/soon", { cache: "no-store" }); if (!r.ok) return; S = await r.json(); } catch (e) { return; }
    const today = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
    const dated = (S.dated || []).filter(x => x.release.date >= today), picks = S.picks || [];
    const WD = [["日", "Sun"], ["月", "Mon"], ["火", "Tue"], ["水", "Wed"], ["木", "Thu"], ["金", "Fri"], ["土", "Sat"]];
    const when = x => { if (!x.release.date) return tr(x.release.ja, x.release.en);
      const d = new Date(x.release.date + "T00:00:00Z"), w = WD[d.getUTCDay()];
      return x.release.date === today ? tr("今日発売", "Out today") : tr(`${d.getUTCMonth() + 1}/${d.getUTCDate()}（${w[0]}）発売`, `Out ${w[1]} ${d.getUTCMonth() + 1}/${d.getUTCDate()}`); };
    const SHOW = 3;   // それぞれ 3 つ（残りは「もっと見る」）
    const href = x => x.id ? `href="${workUrl(x.id)}"` : `href="${esc(x.store)}" target="_blank" rel="noopener noreferrer"`;
    const li = (x, i) => `<li${i >= SHOW ? " hidden" : ""}><a class="cardlink" ${href(x)} aria-label="${esc(nm(x.name))}"></a>${art(x)}<div class="sn-t">${wn(x.name, 2)}
      <span class="sn-w">${when(x)}${x.people ? " · " + tr(`${num(x.people)}人が話題に`, `${num(x.people)} talking`) : ""}</span></div></li>`;
    el.innerHTML = `<h2>${tr("まもなく発売", "Coming soon")}</h2><p class="sn-note">${tr("Steam の人気の近日発売（発売日は Steam のストアの表示）", "Popular upcoming games on Steam (release dates as shown on the Steam store)")}</p>`
      + (dated.length ? `<h3 class="sn-h">${tr("発売日が近い", "Releasing soon")}</h3><ul class="sn-list">${dated.map(li).join("")}</ul>` : "")
      + (picks.length ? `<h3 class="sn-h">${tr("注目の近日発売", "Anticipated")}</h3><ul class="sn-list">${picks.map(li).join("")}</ul>` : "")
      + (!dated.length && !picks.length ? `<p class="sn-none">${tr("これから発売の作品は、まだ分かっていません。", "No upcoming games are known yet.")}</p>` : "");
    const rest = Math.max(0, dated.length - SHOW) + Math.max(0, picks.length - SHOW);
    if (rest) el.insertAdjacentHTML("beforeend", `<button type="button" class="sn-more" aria-expanded="false">${tr(`もっと見る（${rest}作品）`, `Show ${rest} more`)}</button>`);
    el.hidden = false;
    const b = el.querySelector(".sn-more");
    if (b) b.addEventListener("click", () => { const open = b.getAttribute("aria-expanded") !== "true"; b.setAttribute("aria-expanded", String(open));
      el.querySelectorAll(".sn-list").forEach(ul => ul.querySelectorAll("li").forEach((x, i) => { if (i >= SHOW) x.hidden = !open; }));
      el.closest(".sidecol").classList.toggle("sn-open", open);
      b.textContent = open ? tr("閉じる", "Close") : tr(`もっと見る（${rest}作品）`, `Show ${rest} more`); });
  })();
  // 固定の文の英語: data-en を持つ要素は English のときに差し替える（日本語は HTML のまま）
  if (lang === "en") document.querySelectorAll("[data-en]").forEach(el => { el.textContent = el.dataset.en; });
  const t = document.querySelector("meta[name=title-en]"); if (lang === "en" && t) document.title = t.content;
  if (!document.querySelector("script[data-run]")) window.addEventListener("load", restoreScroll);   // データを使わないページ（このサイトについて など）
})();
