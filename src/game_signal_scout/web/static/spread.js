// 世界で広がる作品（spread.html）。data/day/<日>.json の spread（事前計算: 2 つ以上の言語で話題の作品）と dashboard（今日の兆し）だけを使う。
// 構成: 今日の兆し → 今日の広がり（代表の作品を大きく）→ 帯 → 前日になかった言語にも広がった作品（時系列）→ 初めて複数の言語で話題になった作品 → 前から複数の言語で話題の作品。
// 世界地図と言語ごとの作品数はダッシュボードにあるので繰り返さない。矢印・時系列は観測の順で、言語どうしの影響ではない。作品名は省略しない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, wn, art, ln, lcol, chip } = A, $ = id => document.getElementById(id);
  const S = A.D.spread, G = A.D.dashboard, day = S.day, W = S.items;
  const grew = W.filter(w => w.group === "grew"), nw = W.filter(w => w.group === "new"), cont = W.filter(w => w.group === "cont");
  const sumN = w => Object.values(w.n).reduce((a, b) => a + b, 0);
  const link = w => `<a class="cardlink" href="${A.workUrl(w.id)}" aria-label="${esc(nm(w.name))}"></a>`;
  const airTag = w => { const a = w.air; if (!a) return "";
    if (a.status === "upcoming") return `<span class="tag-air up">${tr(`放送前${a.year ? `（${a.year}年予定）` : "（時期は未発表）"}`, `Upcoming${a.year ? ` (${a.year})` : ""}`)}</span>`;
    if (a.status === "airing" && a.start === day) return `<span class="tag-air on">${tr(`${md(day)} 放送開始`, `Premiered ${md(day)}`)}</span>`;
    if (a.status === "airing") return `<span class="tag-air on">${tr("放送中", "Airing")}</span>`;
    if (a.status === "finished") return `<span class="tag-air done">${tr("放送終了", "Finished")}</span>`; return ""; };

  // 代表の作品: 新しく加わった言語が「このサイトで初めて」で、その言語の人数がいちばん多い作品（規則で選ぶ）
  // 2 番目以降に登録した Source で数えた言語の人数には、その Source の表記を添える（人数は Source の中の数。Source をまたいで比べない）
  const SL = (w, l) => (w.src_lang_label || {})[l], SLT = (w, l) => SL(w, l) ? `（${esc(tr(...SL(w, l)))}）` : "";
  const rank = w => { const a = w.added[0]; return [w.first[a] === day ? 1 : 0, SL(w, a) ? 0 : (w.n[a] || 0)]; };
  // 先頭の組（S.lead。ADR 0052）: 今日の兆しの文章・引用と今日の広がりの作品は、サーバーが 1 つの発見から作った組だけを使う。
  // 旗が切の間（lead なし）はこれまでどおり人数の規則で選ぶ
  const LD = G.ui_next ? S.lead : null;
  const hero = LD ? (LD.work ? W.find(w => w.id === LD.work) : null) : [...grew].sort((x, y) => { const a = rank(x), b = rank(y); return b[0] - a[0] || b[1] - a[1]; })[0];

  const timeline = (w, big) => {
    const ev = Object.entries(w.first).map(([l, d]) => ({ l, d, add: (w.added || []).includes(l) && d === day }));
    (w.added || []).forEach(l => { if (w.first[l] !== day) ev.push({ l, d: day, add: true, again: true }); });
    ev.sort((a, b) => a.d < b.d ? -1 : a.d > b.d ? 1 : 0);
    // 点が多いときは、最初の点と最後の点だけを見せ、あいだを「＋N」にまとめる（押すと全部を開く。モックのカードの大きさを保つ）
    const max = big ? 3 : 5, hide = ev.length > max ? ev.length - max + 1 : 0, keepTail = max - 2;
    const li = (e, x) => `<li class="${e.add ? (e.again ? "add again" : "add") : ""}${x ? " tl-x" : ""}" style="--lc:${lcol(e.l)}"><span class="dot"></span><span class="d">${md(e.d)}</span><span class="l">${esc(ln(e.l))}</span>${e.add ? `<span class="new${e.again ? " again" : ""}">${e.again ? tr("再び", "again") : tr("新しく", "new")}</span>` : ""}</li>`;
    const items = ev.map((e, i) => li(e, hide && i >= 1 && i < ev.length - keepTail));
    if (hide) items.splice(1, 0, `<li class="tl-more"><button type="button" aria-label="${tr(`ほか${hide}言語を表示`, `Show ${hide} more`)}">＋${hide}</button></li>`);
    return `<ol class="tl${big ? " big" : ""}${hide ? " short" : ""}" style="--n:${hide ? max : ev.length}">${items.join("")}</ol>`; };
  document.addEventListener("click", e => { const b = e.target.closest(".tl-more button"); if (!b) return; const ol = b.closest(".tl"); ol.classList.remove("short"); ol.classList.add("wrap", "open"); b.parentElement.remove(); });

  /* ---------- 今日の兆し（AI の解説。ない日・その言語では数から組み立てた事実の文） ---------- */
  // 文章: 発見の文章（finding）か、今日の広がりの作品の観測の事実から組む集計の文（aggregate）。ダッシュボードの見出しを使わない（別の発見。仕様 §2）
  const aggText = () => { if (!hero) return tr(`${md(day)}に、前日になかった言語にも広がった作品はありませんでした。${W.length}作品が2つ以上の言語で話題になっています。`,
      `On ${md(day)}, no title spread to a language it did not have the day before. ${W.length} title(s) were talked about in two or more languages.`);
    const a = LD.lang, prev = (LD.prev || []).map(l => ln(l));
    return (prev.length ? tr(`「${nm(hero.name)}」は前日、${prev.join("・")}で2人以上が話題にしていた作品で、この日は${ln(a)}で投稿した${LD.n}人もこの作品に触れました。`,
        `${nm(hero.name)} was talked about by at least 2 people in ${prev.join(", ")} the day before; on this day, ${LD.n} people posting in ${ln(a)} also mentioned it.`)
      : tr(`「${nm(hero.name)}」は前日、どの言語でも2人以上が話題にしていなかった作品で、この日は${ln(a)}で投稿した${LD.n}人がこの作品に触れました。`,
        `${nm(hero.name)} was not talked about by 2 or more people in any language the day before; on this day, ${LD.n} people posting in ${ln(a)} mentioned it.`))
      + tr(`この日、前日になかった言語にも広がった作品は${LD.grew}作品でした。`, ` On this day, ${LD.grew} title(s) spread to a language they did not have the day before.`); };
  { const ss = LD && LD.kind === "finding" ? (LD.sents || {})[A.lang] : null, el = $("sp-digest"); el.hidden = false;
    const t = LD ? (ss ? ss.join(A.lang === "ja" ? "" : " ") : aggText()) : null;
    // 先頭の組のない日だけ、ダッシュボードの集計の文（組があるときは代わりに使わない）
    const body = t ? esc(t).replace(/『([^』]+)』/g, (_, n) => `<b class="nb">『${n}』</b>`) : (!LD ? `${esc(G.summary.head[A.lang])} ${esc(G.summary.lede[A.lang])}` : "");
    el.innerHTML = `<div class="g-kick"><b>${tr("今日の兆し", "Today's signal")}</b><span class="g-day">${esc(G.label[A.lang])}</span>
      <button type="button" class="lede-more" aria-controls="sp-dg" aria-expanded="false" hidden>${tr("続きを読む", "Read more")}</button></div><p class="dg-t clamp3" id="sp-dg"${ss && ss.length ? ` data-sents="${esc(JSON.stringify(ss))}"` : ""}>${body}</p>`
      + (ss ? A.cites(((LD.cites || {})[A.lang]) || []) : "");
    const p = $("sp-dg"), b = el.querySelector(".lede-more"), fit = () => { if (b.getAttribute("aria-expanded") !== "true") b.hidden = !(p.scrollHeight > p.clientHeight + 2); };
    fit(); if (document.fonts) document.fonts.ready.then(fit); window.addEventListener("resize", fit);
    b.addEventListener("click", () => { const open = b.getAttribute("aria-expanded") !== "true"; b.setAttribute("aria-expanded", String(open)); p.classList.toggle("open", open); b.textContent = open ? tr("閉じる", "Close") : tr("続きを読む", "Read more"); }); }

  /* ---------- 今日の広がり ---------- */
  if (hero) { const a = hero.added[0], firstEver = hero.first[a] === day;
    $("sp-lead").innerHTML = `
    <div class="g-kick"><b>${tr("今日の広がり", "Today's spread")}</b><span class="g-day">${tr("今日の兆しの具体例", "An example from today")}</span></div>
    <div class="hero3">${link(hero)}
      <div class="h-im">${art(hero)}</div>
      <div class="h-t">
        <h1>${tr(`${esc(nm(hero.name))}が、<span style="color:${lcol(a)}">${esc(ln(a))}</span>でも話題に`, `${esc(nm(hero.name))} is now talked about in <span style="color:${lcol(a)}">${esc(ln(a))}</span> too`)}</h1>
        <div class="h-chg"><span class="h-was">${(hero.prev || []).map(l => chip(l)).join("")}<small>${tr("前日まで", "Until yesterday")}</small></span>
          <span class="h-now"><span class="ar">→</span>${chip(a, { add: true, n: hero.n[a], src: SL(hero, a) })}<small>${firstEver ? tr(`${esc(ln(a))}では初めて`, `first time in ${esc(ln(a))}`) : tr(`${md(hero.first[a])}以来`, `first since ${md(hero.first[a])}`)}</small></span></div>
        ${hero.air && hero.air.start === day ? `<p class="h-note">${tr("この日は、放送が始まった日でした。", "This was the day it premiered.")}</p>` : ""}
        <a class="more" href="lang.html?l=${encodeURIComponent(a)}">${tr(`${esc(ln(a))}で話題になったほかの作品を見る →`, `More titles talked about in ${esc(ln(a))} →`)}</a>
      </div>
      <div class="h-tl"><span class="tl-h">${tr("言語ごとに話題になった日", "When each language started")}</span>${timeline(hero, true)}</div>
    </div>`;
  } else {
    $("sp-lead").innerHTML = `<div class="g-kick"><b>${tr("今日の広がり", "Today's spread")}</b></div>
      <p class="dg-t">${tr(`${md(day)}に、前日になかった言語にも広がった作品はありませんでした。${W.length}作品が2つ以上の言語で話題になっています。`,
        `On ${md(day)}, no title spread to a language it did not have the day before. ${W.length} title(s) were talked about in two or more languages.`)}</p>`;
  }

  // 今日の広がりは、今日の兆しの具体例。今日の兆しの領域の中に入れる（注目は 1 つ。2026-10-12）
  { const dg = $("sp-digest"), ld = $("sp-lead"); if (dg && ld && !dg.hidden) { ld.classList.add("in-digest"); dg.appendChild(ld); } }

  /* ---------- 帯 ---------- */
  $("sp-bar").innerHTML = `<span class="all">${tr(`<b>${W.length}作品</b>が2つ以上の言語で話題に`, `<b>${W.length}</b> titles in two or more languages`)}</span>
    <a href="#sp-grew">${tr("新しい言語への広がり", "Spread to new languages")} <b>${grew.length}</b></a><a href="#sp-new">${tr("初めて複数の言語", "First time in several")} <b>${nw.length}</b></a><a href="#sp-cont">${tr("前から複数の言語", "Already in several")} <b>${cont.length}</b></a>
    <a class="dash" href="index.html#world">${tr("ダッシュボードの地図 →", "Map on the dashboard →")}</a>`;

  /* ---------- 前日になかった言語にも広がった作品 ---------- */
  // 加わった言語はすべて書く。前日に話題の言語がない作品は「前日は話題なし」と書く（「〜に加えて」を空にしない）
  const grewHead = w => { const add = w.added.map(a => `<b style="color:${lcol(a)}">${esc(ln(a))}</b>`), was = (w.prev || []).map(l => esc(ln(l)));
    return was.length ? tr(`${was.join("・")}に加えて、${add.join("・")}でも話題に`, `Besides ${was.join(", ")}, now in ${add.join(", ")}`)
      : tr(`前日はどの言語でも話題になっていなかった作品が、${add.join("・")}で話題に`, `Not talked about the day before; now in ${add.join(", ")}`); };
  const grCard = w => { const a = w.added[0], firstEver = w.first[a] === day;
      return `<article class="gr3">${link(w)}${art(w)}
        <div class="gr-t">${wn(w.name, 2, "h3")}
          <p class="gr-h">${grewHead(w)}</p>
          <p class="gr-s">${tr(`${esc(ln(a))}で話題にした人 ${w.n[a]}人${SLT(w, a)} ・ ${firstEver ? `${esc(ln(a))}では初めて` : `${md(w.first[a])}にも話題（前日はなし）`}`,
            `${w.n[a]} in ${esc(ln(a))}${SLT(w, a)} · ${firstEver ? "first time" : `also on ${md(w.first[a])} (not the day before)`}`)}</p></div>
        <div class="gr-tl">${timeline(w, false)}</div></article>`; };
  const grRows = [...(hero ? [`<a class="gr-ref" href="#sp-lead">${art(hero)}${wn(hero.name, 1, "span")}<span class="gr-h">${grewHead(hero)}</span><span class="to">${tr("↑ 今日の広がりで紹介", "↑ Shown above")}</span></a>`] : []), ...grew.filter(w => w !== hero).map(grCard)];   // 代表の作品への印を先頭に
  $("sp-grew").innerHTML = grew.length ? `
    <div class="sec-h"><h2>${tr("前日になかった言語にも広がった作品", "Titles reaching a language they did not have yesterday")}<small class="cnt">${A.works(grew.length)}</small></h2>
      <p class="tl-key"><span class="k add"><i></i>${tr("新しく", "new")}</span>${tr("その言語で話題になったのは、この日が初めて", "first time talked about in that language")}<span class="k again"><i></i>${tr("再び", "again")}</span>${tr("以前にも話題になったことがあり、前日はなかった", "talked about before, but not the day before")}</p></div>
    <div class="gr-list" id="gr-list"></div>
    <p class="note">${tr("点と線は、観測した順番を表します。ある言語から別の言語へ話題が移ったという意味ではありません。", "Dots show the order we observed; they do not mean buzz moved from one language to another.")}</p>` : (G.ui_next ? `<div class="sec-h"><h2>${tr("前日になかった言語にも広がった作品", "Titles reaching a language they did not have yesterday")}<small class="cnt">${A.works(0)}</small></h2><p>${tr(`${md(day)}は、前日になかった言語にも広がった作品はありませんでした。`, "No title reached a new language on this day.")}</p></div>` : "");

  /* ---------- 初めて複数の言語で話題になった作品（● = 1 人・◆ = 10 人・★ = 100 人） ---------- */
  const dots = (l, k) => `<span class="dots" style="--lc:${lcol(l)}">${"<i></i>".repeat(k)}</span>`;
  // 記号の合計は人数と必ず同じ: ✪ = 1000 人・★ = 100 人・◆ = 10 人・● = 1 人を、人数の桁ごとに並べる（159 人 = ★◆◆◆◆◆●●●●●●●●●）。
  // 位の高い記号ほど目立つ形にする（★ が ◆ より下に見えた: ユーザーの指摘 2026-10-24）。
  // 記号を打ち切らない（#36: 10 個で打ち切って、159 人が 55 人分にしか見えなかった）。1 つの単位は 9 個まで
  const UNITS = [[1000, "<u class=\"m3\">✪</u>"], [100, "<s>★</s>"], [10, "<u class=\"m1\">◆</u>"], [1, "<i></i>"]];
  const amount = (l, k) => { let r = k;
    return `<span class="dots" style="--lc:${lcol(l)}">${UNITS.map(([u, m]) => { const c = u === 1000 ? Math.floor(r / u) : Math.floor(r / u) % 10; r -= c * u; return m.repeat(c); }).join("")}</span>`; };
  // 2 番目以降に登録した Source で数えた言語の出典の説明は、行に入れず、行の下に 1 回だけ（説明ごとに言語をまとめる。#36: 毎行の説明で格子の列がずれた）
  const srcNote = w => { const by = new Map();
    w.langs.filter(l => SL(w, l)).forEach(l => { const k = tr(...SL(w, l)); by.set(k, [...(by.get(k) || []), ln(l)]); });
    return [...by].map(([k, ls]) => `<span class="nwt-src">※ ${esc(ls.join(tr("・", ", ")))}: ${esc(k)}</span>`).join(""); };
  const was = w => (w.prior_ones && w.prior_ones.length)
    ? w.prior_ones.map(([l, d]) => `<span class="ug">${dots(l, 1)}<span class="ul">${tr(`${esc(ln(l))} 1人`, `${esc(ln(l))} 1`)}</span><span class="ud">${md(d)}</span></span>`).join("")
    : `<span class="none"><i></i>${tr("観測なし", "None seen")}</span>`;
  // 言語ごとの人数は初めの card_langs_first 言語だけを見せ、残りは「ほか N 言語を表示」でその場に開く（#58: 言語の数に比例してカードが縦に伸びた。全言語はページに持ち、隠すだけ）
  const LF = (G.display || {}).card_langs_first || 4;
  const fold = w => w.langs.length > LF + 1;   // 隠すのは 2 言語以上残るときだけ（1 言語のためにボタンを出さない）
  const nwRow = w => `<div class="nwt-r" role="row">${link(w)}${art(w)}
        <div class="nwt-n" role="cell">${wn(w.name, 2, "h3")}${airTag(w)}</div>
        <div class="nwt-was" role="cell">${was(w)}</div><span class="ar">→</span>
        <div class="nwt-now" role="cell">${w.langs.map((l, i) => `<span class="ug"${fold(w) && i >= LF ? " hidden" : ""}><span class="ul" style="color:${lcol(l)}">${esc(ln(l))}${SL(w, l) ? "<sup>※</sup>" : ""}</span>${amount(l, w.n[l])}<b>${esc(A.ppl(w.n[l]))}</b></span>`).join("")}${fold(w) ? `<button type="button" class="nwt-more" aria-expanded="false" data-n="${w.langs.length - LF}">${tr(`ほか${w.langs.length - LF}言語を表示`, `Show ${w.langs.length - LF} more languages`)}</button>` : ""}${srcNote(w)}</div></div>`;
  $("sp-new").innerHTML = nw.length ? `
    <div class="sec-h"><h2>${tr("この日、初めて複数の言語で話題になった作品", "Titles talked about in several languages for the first time")}<small class="cnt">${A.works(nw.length)}</small></h2><p>${tr("それまでほとんど観測されていなかった作品が、この日、いくつもの言語で同時に話題になりました。", "Titles barely seen before were talked about in several languages on this day.")}</p></div>
    <p class="unit-key">${tr("人数の見方", "Scale")}<span class="dots" style="--lc:var(--accent)"><i></i></span>${tr("1人", "1 person")}<span class="dots" style="--lc:var(--accent)"><u class="m1">◆</u></span>${tr("10人", "10 people")}<span class="dots" style="--lc:var(--accent)"><s>★</s></span>${tr("100人", "100 people")}${nw.some(w => w.langs.some(l => w.n[l] >= 1000)) ? `<span class="dots" style="--lc:var(--accent)"><u class="m3">✪</u></span>${tr("1000人", "1,000 people")}` : ""}</p>
    <div class="nwt" role="table">
      <div class="nwt-h" role="row"><span role="columnheader">${tr("作品", "Title")}</span><span role="columnheader">${tr("これまで", "Before")}</span><span></span><span role="columnheader">${tr(`${md(day)} に話題にした人`, `People on ${md(day)}`)}</span></div>
      <div class="more-box" id="nwt-rows"></div>
    </div>` : (G.ui_next ? `<div class="sec-h"><h2>${tr("この日、初めて複数の言語で話題になった作品", "Titles talked about in several languages for the first time")}<small class="cnt">${A.works(0)}</small></h2><p>${tr(`${md(day)}は、初めて複数の言語で話題になった作品はありませんでした。`, "No title was talked about in several languages for the first time on this day.")}</p></div>` : "");

  /* ---------- 前から複数の言語で話題の作品 ---------- */
  // 出典の説明は札の中に入れず、印（※1・※2…）だけを付けて段の下にまとめる（説明ごとに 1 つの印。#36: 札が長くなり 2 段に折り返した）
  const marks = new Map(), mark = (w, l) => { if (!SL(w, l)) return ""; const k = tr(...SL(w, l)); if (!marks.has(k)) marks.set(k, `※${marks.size + 1}`); return marks.get(k); };
  const ctRows = cont.map(w => { const since = w.langs.map(l => w.first[l]).sort().at(-1);
      return `<li>${link(w)}${art(w)}${wn(w.name, 1, "span")}<div class="lcs">${w.langs.map(l => chip(l, { n: w.n[l], mark: mark(w, l) })).join("")}</div><span class="since">${tr(`${md(since)}から`, `since ${md(since)}`)}</span></li>`; });   // 札の印（※）は行を作るときに決まるので、出典の説明より先に全部の行を作る
  $("sp-cont").innerHTML = cont.length ? `
    <div class="sec-h"><h2>${tr("前から複数の言語で話題の作品", "Titles already talked about in several languages")}<small class="cnt">${A.works(cont.length)}</small></h2><p>${tr("この日も、2つ以上の言語で話題が続いた作品です（今日新しく起きた変化ではありません）。", "Still talked about in two or more languages on this day (not a new change).")}</p></div>
    <div class="ct-h"><span>${tr("作品", "Title")}</span><span>${tr("この日に話題にした人", "People on this day")}</span><span>${tr("複数の言語で話題になった日", "In several languages since")}</span></div>
    <ul class="ct-list" id="ct-list"></ul>
    ${marks.size ? `<p class="ct-src">${[...marks].map(([k, m]) => `${m} ${esc(k)}`).join(tr("　", " · "))}</p>` : ""}` : (G.ui_next ? `<div class="sec-h"><h2>${tr("前から複数の言語で話題の作品", "Titles already talked about in several languages")}<small class="cnt">${A.works(0)}</small></h2><p>${tr(`${md(day)}は、前から複数の言語で話題の作品はありませんでした。`, "No title was already talked about in several languages on this day.")}</p></div>` : "");
  // 長い一覧は初めの数件だけを描き、残りは「もっと見る」（common.js の moreList。件数は config/pages.toml [display]。#55）
  const DP = G.display || {};
  if (grRows.length && $("gr-list")) A.moreList($("gr-list"), grRows, DP.moves_first, DP.rows_step);
  if (nw.length && $("nwt-rows")) A.moreList($("nwt-rows"), [...nw].sort((a, b) => sumN(b) - sumN(a)).map(nwRow), DP.rows_first, DP.rows_step);
  if (ctRows.length && $("ct-list")) A.moreList($("ct-list"), ctRows, DP.rows_first, DP.rows_step);
  $("sp-new").addEventListener("click", e => { const b = e.target.closest(".nwt-more"); if (!b) return;
    const open = b.getAttribute("aria-expanded") !== "true";
    [...b.parentNode.querySelectorAll(".ug")].forEach((g, i) => { if (i >= LF) g.hidden = !open; });
    b.setAttribute("aria-expanded", String(open));
    b.textContent = open ? tr("閉じる", "Show less") : tr(`ほか${b.dataset.n}言語を表示`, `Show ${b.dataset.n} more languages`); });
})();
