// 作品を探す（search.html）。data/search.json（事前計算: 本番の work_index ＋ 各ページにだけ載っている作品）を、このページの中で絞り込む。
// 探せるもの: 作品名（日本語・英語・別の表記）・日本語・変化の種類・言語圏・発売年・タグ・ジャンル、遊び方のページでは遊び方（オンライン・同じ画面・LAN など）。並び: 最後に動いた日（本番の既定）・動いた日数・いちばん多い日の人数。
// 変化の種類は色で分けない（紫 1 色の札）。色は言語にだけ使う。判定の基準の数字は書かない。作品名は省略しない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, num, wn, art, ln, lcol, FMT, SEASON, AIR, GENRE } = A, P = A.S, $ = id => document.getElementById(id);
  const KIND = { surge: A.KIND.surge, cont: A.KIND.cont, new: A.KIND.new, overseas: A.KIND.overseas, re: A.KIND.re };
  const MAIN_L = ["ja", "en", "pt", "es"], PER = 30;
  const AIRS = ["airing", "upcoming", "finished"];
  // Game: 遊び方のページ（solo / coop / versus / pad）は、作品を探すと同じ一覧を遊び方で絞る
  const MODE_PAGES = { solo: "ひとりで遊べる", coop: "協力プレイ", versus: "対戦", pad: "コントローラーで遊べる" };
  const PAGE = document.documentElement.dataset.page, MODE = MODE_PAGES[PAGE];
  const W = P.works.filter(w => !MODE || (w.modes || []).includes(MODE)), NPAGE = W.filter(w => w.page_only).length;
  // 遊び方のページごとの選び方（#2 2026-11-11 オーナー: 3 ページが同じ作品の一覧に見えないように、そのページの遊び方で何ができるかを選べる・カードに出す）。
  // 値はストアの表示（作品の情報の modes）だけ。表示のない作品はどれにも入れない（推測で付けない）
  const has = (w, m) => (w.modes || []).includes(m);
  const OTHERS = ["協力プレイ", "対戦", "みんなで遊べる", "画面分割・同じ画面で"];
  const HOW = {
    solo: { note: tr("「ひとり用だけ」は、ストアに協力・対戦・マルチプレイの表示がない作品です。", "\"Single-player only\" means the store lists no co-op, versus or multiplayer."),
      opts: [["only", tr("ひとり用だけ", "Single-player only"), w => !OTHERS.some(m => has(w, m))], ["multi", tr("ほかの人とも遊べる", "Also with others"), w => OTHERS.some(m => has(w, m))]] },
    coop: { note: tr("どこでつながって協力できるかは、ストアの表示です。表示のない作品は、どれにも入りません。", "Where you can play together is as listed on the store. Titles without that listing are in none of these."),
      opts: [["online", tr("オンラインで協力", "Online co-op"), w => has(w, "オンラインで協力")], ["local", tr("同じ画面で協力", "Same-screen co-op"), w => has(w, "同じ画面で協力")], ["lan", tr("LANで協力", "LAN co-op"), w => has(w, "LANで協力")]] },
    versus: { note: tr("どこでつながって対戦できるかは、ストアの表示です。表示のない作品は、どれにも入りません。", "Where you can play against others is as listed on the store. Titles without that listing are in none of these."),
      opts: [["online", tr("オンラインで対戦", "Online versus"), w => has(w, "オンラインで対戦")], ["local", tr("同じ画面で対戦", "Same-screen versus"), w => has(w, "同じ画面で対戦")], ["lan", tr("LANで対戦", "LAN versus"), w => has(w, "LANで対戦")]] },
  }[PAGE];
  const howOf = k => (HOW ? HOW.opts.find(o => o[0] === k) : null);
  const st = { q: "", jp: "", kind: "", lang: "", air: "", genre: "", score: "", year: "", tag: "", sort: "last", how: "", n: PER };
  const EX = A.EXTRA || { tag: t => t };
  try { st.q = new URLSearchParams(location.search).get("q") || ""; } catch (e) { /* 既定で表示 */ }
  // 作品詳細から戻ったとき（前のページへ・ブラウザの戻る）は、探す条件と表示した件数を戻す
  if (A.restoring && A.restoring.state && A.restoring.state.search) Object.assign(st, A.restoring.state.search);
  A.pageState = () => ({ search: { ...st } });

  /* ---------- 絞り込み ---------- */
  const norm = s => String(s || "").toLowerCase().normalize("NFKC").replace(/\s+/g, "");
  const hitQ = (w, q) => !q || [w.name.ja, w.name.en, ...(w.keys || [])].some(n => norm(n).includes(q));
  const hitL = (w, l) => !l || (l === "other" ? w.langs.some(([c]) => !MAIN_L.includes(c)) : w.langs.some(([c]) => c === l));
  // 日本語で遊べるか（#2）: any = UI・字幕・音声のどれか、sub = 字幕以上、voice = 音声。未確認は「日本語で遊べる」に入れない
  const JPF = { any: w => ["ui", "sub", "voice"].includes(A.jpLevel(w)), sub: w => ["sub", "voice"].includes(A.jpLevel(w)), voice: w => A.jpLevel(w) === "voice" };
  const hitJ = (w, j) => !j || (JPF[j] ? JPF[j](w) : A.jpLevel(w) === j);
  const airOf = w => (w.rs === "releasing" ? "airing" : w.rs === "not_yet_released" ? "upcoming" : w.rs);
  const filtered = () => { const q = norm(st.q);
    const list = W.filter(w => hitQ(w, q) && hitJ(w, st.jp) && (!st.kind || w.kinds.includes(st.kind)) && hitL(w, st.lang) && (!st.air || airOf(w) === st.air) && (!st.genre || w.genres.includes(st.genre))
      && (!st.score || (w.score || 0) >= Number(st.score)) && (!st.year || String(w.year) === st.year) && (!st.tag || (w.tags || []).includes(st.tag)) && (!st.how || !howOf(st.how) || howOf(st.how)[2](w)));
    if (st.sort === "score") return [...list].sort((a, b) => (b.score || 0) - (a.score || 0) || (b.pop || 0) - (a.pop || 0));
    if (st.sort === "pop") return [...list].sort((a, b) => (b.pop || 0) - (a.pop || 0));
    if (st.sort === "days") return [...list].sort((a, b) => b.days - a.days || b.peak - a.peak);
    if (st.sort === "peak") return [...list].sort((a, b) => b.peak - a.peak || ((a.last || "") < (b.last || "") ? 1 : -1));
    return list; };   // 既定は本番の API の順（最後に動いた日の新しい順 → いちばん多い日の人数）。ページにだけ載っている作品は後ろ

  /* ---------- 探す欄 ---------- */
  const cnt = f => W.filter(f).length;
  const chipBtn = (grp, val, label, n, extra = "") => `<button type="button" class="sr-chip" data-g="${grp}" data-v="${val}" aria-pressed="${String(st[grp] === val)}"${extra}>${label}${n != null ? `<small>${num(n)}</small>` : ""}</button>`;
  const genres = Object.entries(W.reduce((a, w) => (w.genres.forEach(g => { a[g] = (a[g] || 0) + 1; }), a), {})).sort((a, b) => b[1] - a[1]);
  const years = Object.entries(W.reduce((a, w) => (w.year && (a[w.year] = (a[w.year] || 0) + 1), a), {})).sort((a, b) => b[0] - a[0]);
  const tagsAll = Object.entries(W.reduce((a, w) => ((w.tags || []).forEach(t => { a[t] = (a[t] || 0) + 1; }), a), {})).filter(([, n]) => n >= 2)
    .sort((a, b) => b[1] - a[1] || (EX.tag(a[0]) < EX.tag(b[0]) ? -1 : 1));
  $("sr-panel").innerHTML = `<label class="sr-q"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
      <input id="sr-q" type="search" autocomplete="off" placeholder="${tr("作品名で探す（日本語・英語どちらでも）", "Search by title (Japanese or English)")}" value="${esc(st.q)}" aria-label="${tr("作品名", "Title")}"></label>
    ${HOW ? `<div class="sr-row sr-how-row"><span class="sr-l">${tr("遊び方", "How to play")}</span><span class="sr-chips">${chipBtn("how", "", tr("すべて", "All"), W.length)}${HOW.opts.map(([k, l, f]) => chipBtn("how", k, l, cnt(f))).join("")}</span><p class="sr-how-note">${esc(HOW.note)}</p></div>` : ""}
    <div class="sr-row"><span class="sr-l">${tr("日本語", "Japanese")}</span><span class="sr-chips">${chipBtn("jp", "", tr("すべて", "All"), W.length)}${[["any", tr("日本語で遊べる", "Playable in Japanese")], ["sub", tr("字幕あり", "Subtitles")], ["voice", tr("音声あり", "Voice")], ["none", tr("日本語なし", "No Japanese")], ["unknown", tr("未確認", "Unknown")]].map(([k, l]) => chipBtn("jp", k, l, cnt(w => hitJ(w, k)))).join("")}</span></div>
    <div class="sr-row"><span class="sr-l">${tr("変化の種類", "Type of change")}</span><span class="sr-chips">${chipBtn("kind", "", tr("すべて", "All"), W.length)}${Object.keys(KIND).map(k => chipBtn("kind", k, esc(KIND[k]), cnt(w => w.kinds.includes(k)))).join("")}</span></div>
    <div class="sr-row"><span class="sr-l">${tr("言語圏", "Language area")}</span><span class="sr-chips">${chipBtn("lang", "", tr("すべて", "All"))}${MAIN_L.map(l => chipBtn("lang", l, `<i style="background:${lcol(l)}"></i>${esc(ln(l))}`, cnt(w => hitL(w, l)), ` style="--lc:${lcol(l)}"`)).join("")}${chipBtn("lang", "other", tr("そのほか", "Other"), cnt(w => hitL(w, "other")))}</span></div>
    <div class="sr-row"><span class="sr-l">${tr("発売年", "Year")}</span><span class="sr-sel"><select id="sr-year" aria-label="${tr("発売年", "Year")}"><option value="">${tr("すべて", "All")}</option>${years.map(([y, n]) => `<option value="${esc(y)}">${tr(`${y}年（${n}）`, `${y} (${n})`)}</option>`).join("")}</select></span>
      ${tagsAll.length ? `<span class="sr-l sr-l2">${tr("タグ", "Tag")}</span><span class="sr-sel"><select id="sr-tag" aria-label="${tr("タグ", "Tag")}"><option value="">${tr("すべて", "All")}</option>${tagsAll.map(([t, n]) => `<option value="${esc(t)}">${esc(EX.tag(t))}${tr(`（${n}）`, ` (${n})`)}</option>`).join("")}</select></span>` : ""}</div>
    <div class="sr-row"><span class="sr-l">${tr("ジャンル", "Genre")}</span><span class="sr-sel"><select id="sr-genre" aria-label="${tr("ジャンル", "Genre")}"><option value="">${tr("すべて", "All")}</option>${genres.map(([g, n]) => `<option value="${esc(g)}">${esc(GENRE[g] || g)}${tr(`（${n}）`, ` (${n})`)}</option>`).join("")}</select></span>
      <span class="sr-l sr-l2">${tr("並び順", "Sort")}</span><span class="sr-sel"><select id="sr-sort" aria-label="${tr("並び順", "Sort")}"><option value="last">${tr("最後に動いた日が新しい順", "Most recent change")}</option><option value="days">${tr("動いた日数が多い順", "Most days with a change")}</option><option value="peak">${tr("いちばん多い日の人数が多い順", "Largest single-day count")}</option></select></span></div>`;

  /* ---------- 結果のカード（作品詳細へのリンク） ---------- */
  const meta = w => [FMT[w.fmt], w.year && w.season ? tr(`${w.year}年${SEASON[w.season]}`, `${SEASON[w.season]} ${w.year}`) : w.year ? String(w.year) : "", AIR[w.rs]].filter(Boolean).join(tr("・", " · "));
  const score = () => "";   // Game に作品の採点はない（Anime の名残の採点の表示をしない）
  // カード: 作品画像・作品名・基本情報（形式・年・放送の状況・平均評価）・変化の種類だけ（2026-10-16 のユーザーの指示）。
  // 言語圏・最後に動いた日・動いた日数・いちばん多い日の人数・各ページへの案内は作品詳細に（一覧には出さない）。札は省略せず、必要なときだけ折り返す
  const kinds = w => {
    const ks = (st.kind && w.kinds.includes(st.kind) ? [st.kind, ...w.kinds.filter(k => k !== st.kind)] : w.kinds).filter(k => KIND[k]);
    return ks.length ? `<span class="sr-k">${ks.map(k => `<span class="kt${st.kind === k ? " on" : ""}" data-kind="${esc(k)}">${esc(KIND[k])}</span>`).join("")}</span>` : "";
  };
  const howTags = w => { if (!HOW) return ""; const t = HOW.opts.filter(([k, , f]) => (PAGE !== "solo" || k === "only") && f(w)).map(([, l]) => `<span class="hw">${esc(l)}</span>`);
    return t.length ? `<span class="sr-hw">${t.join("")}</span>` : ""; };
  const card = w => `<article class="sr-card"><a class="sr-link" href="${A.workUrl(w.id)}" aria-label="${esc(nm(w.name))}"></a>${art(w)}
    <div class="sr-t">${wn(w.name, 2, "h3")}${meta(w) || w.score != null ? `<span class="sr-meta">${esc(meta(w))}${score(w)}</span>` : ""}<span class="sr-dev">${A.jpTag(w)}${A.priceTag(w)} ${A.devLine(w)}</span>${howTags(w)}${kinds(w)}
    </div></article>`;

  function render() {
    const list = filtered(), shown = list.slice(0, st.n);
    const JPN = { any: tr("日本語で遊べる", "Playable in Japanese"), sub: tr("日本語字幕あり", "JP subtitles"), voice: tr("日本語音声あり", "JP voice"), none: tr("日本語なし", "No Japanese"), unknown: tr("日本語は未確認", "JP unknown") };
    const conds = [st.q && `「${esc(st.q)}」`, st.jp && JPN[st.jp], st.kind && esc(KIND[st.kind]), st.lang && (st.lang === "other" ? tr("そのほかの言語圏", "Other language areas") : esc(ln(st.lang))), st.air && esc(AIR[st.air]), st.genre && esc(GENRE[st.genre] || st.genre),
      st.score && tr(`平均評価${st.score}点以上`, `Score ${st.score}+`), st.year && tr(`${esc(st.year)}年`, esc(st.year)), st.tag && esc(EX.tag(st.tag)), st.how && howOf(st.how) && esc(howOf(st.how)[1])].filter(Boolean);
    $("sr-count").innerHTML = `<b>${num(list.length)}</b>${tr("作品", " titles")}<span>${tr(`（全${W.length}作品中。${md(P.first)}〜${md(P.latest)}に話題の変化を観測した${W.length - NPAGE}作品と、各ページにだけ載っている${NPAGE}作品）`,
      ` (of ${W.length}: ${W.length - NPAGE} with a change seen ${md(P.first)}–${md(P.latest)}, and ${NPAGE} shown only on other pages)`)}</span>
      ${conds.length ? `<span class="sr-cond">${conds.map(c => `<em>${c}</em>`).join("")}<button type="button" id="sr-clear">${tr("条件をすべて外す", "Clear all")}</button></span>` : ""}`;
    $("sr-list").innerHTML = shown.length ? shown.map(card).join("")
      : `<div class="rv-empty sr-empty"><span class="ic"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg></span><div><b>${tr("条件に合う作品はありません", "No titles match")}</b><p>${tr("作品名の一部だけで探すか、条件を外してみてください。まだ話題の変化を観測していない作品は、ここには出ません。", "Try part of the title, or clear some filters. Titles we have not seen change yet are not listed.")}</p></div></div>`;
    $("sr-more").innerHTML = list.length > shown.length ? `<button type="button" id="sr-morebtn">${tr(`もっと見る（残り${list.length - shown.length}作品）`, `Show more (${list.length - shown.length} left)`)}</button>` : "";
    document.querySelectorAll(".sr-chip").forEach(b => b.setAttribute("aria-pressed", String(st[b.dataset.g] === b.dataset.v)));
    $("sr-genre").value = st.genre; $("sr-sort").value = st.sort; $("sr-year").value = st.year; if ($("sr-tag")) $("sr-tag").value = st.tag;
  }
  $("sr-q").addEventListener("input", e => { st.q = e.target.value; st.n = PER; render(); });
  $("sr-genre").addEventListener("change", e => { st.genre = e.target.value; st.n = PER; render(); });
  $("sr-sort").addEventListener("change", e => { st.sort = e.target.value; render(); });
  $("sr-year").addEventListener("change", e => { st.year = e.target.value; st.n = PER; render(); });
  if ($("sr-tag")) $("sr-tag").addEventListener("change", e => { st.tag = e.target.value; st.n = PER; render(); });
  document.addEventListener("click", e => {
    const c = e.target.closest(".sr-chip"); if (c) { st[c.dataset.g] = c.dataset.v; st.n = PER; render(); return; }
    if (e.target.closest("#sr-morebtn")) { st.n += PER; render(); return; }
    if (e.target.closest("#sr-clear")) { Object.assign(st, { q: "", kind: "", lang: "", air: "", genre: "", score: "", year: "", tag: "", how: "", n: PER }); $("sr-q").value = ""; render(); }
  });
  render();
})();
