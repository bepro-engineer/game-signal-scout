// 言語圏の広がり（langspread.html）。data/pages.json の language_spread（事前計算: 本番の judge_language_spread のまま。並びも本番の API の既定）だけを使う。
// 構成: この期間の広がり（文章）→ 帯 → ほかの言語圏から広がった作品（カードと言語×日の表）→ 新しく話題になり始めた作品（1 行 1 作品）。
// どちらの一覧も初めの数件だけを描き、残りは「もっと見る」で足す（common.js の moreList。件数は config/pages.toml [display]。Issue #16）。
// 「ほかの言語圏から」= それまでに話題だった言語圏（prior）がある作品。「新しく話題に」= ない作品（同じ定義の中の分け方で、判定は変えない）。
// 判定の基準の数字は書かない。言語圏は国ではない。言語圏ごとの人数を比べる棒を出さない。作品名は省略しない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, wn, art, ln, lcol, chip, AIR } = A, P = A.P, $ = id => document.getElementById(id);
  const D = P.days, first = D[0], day = P.as_of, obs = P.observed;
  const ST = { continuing: [tr("その後も続いている", "Still going"), "on"], faded: [tr("落ち着いた", "Faded"), "off"], unknown: [tr("その後はこれから", "Too early to tell"), "tbd"] };
  const link = w => `<a class="cardlink" href="${A.workUrl(w.id)}" aria-label="${esc(nm(w.name))}"></a>`;
  const items = P.language_spread.items.map(w => { const e = w.ev, fi = D.indexOf(e.first_day);
    return { ...w, e, fi, top: e.new_langs[0], after: fi >= 0 ? D.slice(fi + 1).filter((_, k) => obs[fi + 1 + k] !== "n").length : 0, priorL: Object.keys(e.prior_langs).slice(0, 3) }; });
  const grew = items.filter(w => w.priorL.length), fresh = items.filter(w => !w.priorL.length);
  const cnt = s => items.filter(w => w.e.status === s).length;
  const contText = w => w.e.status === "unknown" ? "" : tr(`その後${w.after}日のうち<b>${w.top.cont_days}日</b>で話題に`, `talked about on <b>${w.top.cont_days}</b> of the next ${w.after} day(s)`);
  const stChip = s => `<em class="st ${(ST[s] || ST.unknown)[1]}">${(ST[s] || ST.unknown)[0]}</em>`;

  /* ---------- この期間の広がり ---------- */
  const lead = grew.find(w => w.e.status === "continuing") || grew[0];
  $("ls-sum").innerHTML = `<div class="g-kick"><b>${tr("今日の兆し", "Today's signal")}</b><span class="g-day">${tr("この期間の広がり", "Spread in this period")}・${md(first)}〜${md(day)}</span></div>
    <p class="dg-t">${tr(`${md(first)}から${md(day)}までに、${items.length}作品が新しい言語圏で話題になり始めました。そのうち${grew.length}作品は、ほかの言語圏で話題だった作品がさらに広がったものです。`,
      `From ${md(first)} to ${md(day)}, ${items.length} title(s) started being talked about in a new language area; ${grew.length} of them had already been talked about in another language area.`)}
    ${lead ? tr(`<b class="nb">『${esc(nm(lead.name))}』</b>は${lead.priorL.map(ln).join("・")}に加えて、${md(lead.e.first_day)}から<b class="nb">${esc(ln(lead.top.code))}圏</b>でも話題になっています。`,
      ` <b>${esc(nm(lead.name))}</b> was talked about in ${lead.priorL.map(ln).join(", ")}, and since ${md(lead.e.first_day)} also in <b>${esc(ln(lead.top.code))}</b>.`) : ""}
    ${tr(`${md(day)}の時点で、話題が続いているのは${cnt("continuing")}作品、落ち着いたのは${cnt("faded")}作品です。`, ` As of ${md(day)}, ${cnt("continuing")} are still going and ${cnt("faded")} have faded.`)}</p>`;

  /* ---------- 帯 ---------- */
  $("ls-bar").innerHTML = `<span class="all">${md(first)}〜${md(day)}</span>
    <a href="#ls-grew">${tr("ほかの言語圏から広がった作品", "Spread from other areas")} <b>${grew.length}</b></a><a href="#ls-new">${tr("新しく話題になり始めた作品", "Newly talked about")} <b>${fresh.length}</b></a>
    <a class="dash" href="spread.html">${tr("その日の広がりは「世界で広がる」へ →", "See the day's spread on Worldwide →")}</a>`;

  /* ---------- 言語×日の表 ----------
     記号の意味（判定のデータそのまま。段の先頭の「表の見方」で読者に示す）: 枠の列 = その作品が新しい言語圏で話題になり始めた日（ev.first_day。全行に付く。カードの文の日付と同じ）。
     数字と濃さ = その言語で話題にした人の数。灰色の空欄 = 観測はできていて 0 人。斜線 = 一部の時間だけ観測できた日（人数が少なめ）。「—」 = 観測できなかった日（0 人ではない）。 */
  const cell = (n, i, l, fi) => `<span class="c${i === fi ? " on" : ""}${obs[i] === "p" ? " pt" : ""}${obs[i] === "n" ? " na" : n ? "" : " z"}" style="--lc:${lcol(l)};--a:${n ? Math.min(.22 + n / 12, 1) : 0}">${obs[i] === "n" ? "—" : n || ""}</span>`;
  // 表の窓: 話題になり始めた日（fi）の GR.before 日前から GR.days 日分。今日を越える分は前にずらす（config/pages.toml [language_spread] grid_*）
  const GR = P.language_spread.grid || { days: D.length, before: 0 };
  const span = w => { const n = Math.min(GR.days, D.length), fi = Math.max(w.fi, 0); let s = Math.max(0, fi - GR.before); s = Math.max(0, Math.min(s, D.length - n)); return [s, s + n]; };
  const grid = w => {
    const rows = [...w.priorL.map(l => [l, false]), ...w.e.new_langs.map(x => [x.code, true])];
    const [s, e] = span(w), idx = D.map((_, i) => i).slice(s, e);
    // 日付の見出し: 窓の最初・枠の列・窓の最後。枠の列と 2 列以内に近い端の日付は出さない（重なって読めなかった）
    const lab = i => i === w.fi || ((i === s || i === e - 1) && Math.abs(i - w.fi) > 2);
    const head = idx.map(i => `<span class="${i === w.fi ? "hd on" : "hd"}">${lab(i) ? md(D[i]) : ""}</span>`).join("");
    // 表のすぐ下に、枠の列の意味を 1 行（段の先頭の見方と同じ言い方。日付はこの作品のもの。どの言語圏かは行の「新しく」で分かるので繰り返さない）
    const cap = w.fi >= 0 ? tr(`枠の列 = ${md(w.e.first_day)}、新しい言語圏で話題になり始めた日`, `Framed column = ${md(w.e.first_day)}, first talked about in a new language area`) : "";
    return `<div class="lsg" style="--n:${idx.length}" role="img" aria-label="${esc(nm(w.name))}"><span class="lab"></span>${head}
      ${rows.map(([l, add]) => `<span class="lab${add ? " add" : ""}" style="color:${lcol(l)}">${esc(ln(l))}${add ? `<small>${tr("新しく", "new")}</small>` : ""}</span>` +
        idx.map(i => cell((w.per[l] || [])[i] || 0, i, l, w.fi)).join("")).join("")}</div>${cap ? `<p class="lsg-cap">${cap}</p>` : ""}`; };
  // 表の見方（段の先頭に 1 回。見本は表と同じ部品で描く。斜線・— は、表示している期間にその日があるときだけ）
  const sample = (cls, n, l = "ja") => `<span class="c ${cls}" style="--lc:${lcol(l)};--a:${n ? Math.min(.22 + n / 12, 1) : 0}">${n || (cls === "na" ? "—" : "")}</span>`;
  const KEY = `<div class="ls-key" role="note" aria-label="${tr("表の見方", "How to read the table")}"><span><i class="k">${sample("on", 5)}</i>${tr("枠の列 = 新しい言語圏で話題になり始めた日", "Framed column = day it was first talked about in a new language area")}</span>
    <span><i class="k">${sample("", 3)}${sample("", 9)}</i>${tr("数字 = その言語で話題にした人数（濃いほど多い）", "Number = people talking in that language (darker = more)")}</span>
    <span><i class="k">${sample("z", 0)}</i>${tr("空欄 = 観測はできて 0 人", "Blank = observed, nobody")}</span>
    ${obs.includes("p") ? `<span><i class="k">${sample("pt", 2)}</i>${tr("斜線 = 一部の時間だけ観測（少なめ）", "Hatched = partly observed (may be low)")}</span>` : ""}
    ${obs.includes("n") ? `<span><i class="k">${sample("na", 0)}</i>${tr("— = 観測できなかった日", "— = not observed")}</span>` : ""}</div>`;

  /* ---------- ほかの言語圏から広がった作品 ---------- */
  const DP = P.display;
  const card = w => `<article class="lsc" data-id="${esc(w.id)}">${link(w)}${art(w)}
      <div class="lsc-t">${wn(w.name, 2, "h3")}<span class="rv-air">${esc(AIR[w.rs] || "")}</span>${A.srcNote(w)}
        <div class="lsc-chg">${w.priorL.map(l => chip(l)).join("")}<span class="ar">→</span>${w.e.new_langs.map(x => chip(x.code, { add: true })).join("")}</div>
        <p class="lsc-d">${tr(`<b>${md(w.e.first_day)}</b>に${w.e.new_langs.map(x => `${esc(ln(x.code))}圏で<b>${x.authors}人</b>`).join("・")}が新しく話題に`, `On <b>${md(w.e.first_day)}</b>: ${w.e.new_langs.map(x => `<b>${x.authors}</b> new in ${esc(ln(x.code))}`).join(", ")}`)}</p>
        <p class="lsc-s">${stChip(w.e.status)}<span>${contText(w)}</span></p>
        ${w.e.signal_recorded ? `<p class="lsc-r">${tr("その日の「世界で広がる」にも載りました", "Also shown on Worldwide that day")}</p>` : ""}</div>
      <div class="lsc-g">${grid(w)}</div></article>`;
  // 今日の兆しが取り上げている代表の 1 作品（lead）は、一覧の中では 1 行の参照（重複させない。並び・件数は変えない。世界で広がると同じ）
  const leadRef = w => `<a class="gr-ref ls-ref" href="#ls-sum">${art(w)}${wn(w.name, 1, "span")}<span class="to">${tr("↑ 今日の兆しで紹介", "↑ Shown above")}</span></a>`;
  $("ls-grew").innerHTML = `<div class="sec-h"><h2>${tr("ほかの言語圏から広がった作品", "Titles spreading from other language areas")}<small class="cnt">${A.works(grew.length)}</small></h2><p>${tr("すでにほかの言語圏で話題だった作品が、それまでほとんど話題のなかった言語圏でも話題になり始めたものです。新しく話題にした人が多い順です。",
      "Titles already talked about in one language area that started being talked about in an area with little buzz before. Most new people first.")}</p></div>
    ${grew.length ? `${KEY}<div class="lsc-list"><div class="more-box"></div></div>`
      : `<div class="rv-empty"><div><b>${tr("該当する作品はありません", "None in this period")}</b></div></div>`}`;
  if (grew.length) A.moreList(document.querySelector("#ls-grew .more-box"), grew.map(w => (lead && w.id === lead.id ? leadRef(w) : card(w))), DP.cards_first, DP.cards_step);

  /* ---------- 新しく話題になり始めた作品 ---------- */
  const frow = w => `<div class="rv-r" role="row">${link(w)}${art(w)}
        <div class="rv-n" role="cell">${wn(w.name, 2, "h3")}<span class="rv-air">${esc(AIR[w.rs] || "")}</span>${A.srcNote(w)}</div>
        <div class="rv-last" role="cell"><span><b>${md(w.e.first_day)}</b>${tr("に", " ")}${w.e.new_langs.map(x => chip(x.code, { add: true })).join("")}</span><span class="pa-d">${w.e.new_langs.map(x => tr(`${esc(ln(x.code))}圏で${x.authors}人`, `${x.authors} in ${esc(ln(x.code))}`)).join(tr("・", ", "))}${tr("が話題に", "")}</span></div>
        <span class="ar" aria-hidden="true">→</span>
        <div class="rv-q pa-q" role="cell">${stChip(w.e.status)}<span class="pa-d">${contText(w).replace(/<\/?b>/g, "")}</span></div></div>`;
  $("ls-new").innerHTML = `<div class="sec-h"><h2>${tr("新しく話題になり始めた作品", "Titles newly talked about")}<small class="cnt">${A.works(fresh.length)}</small></h2><p>${tr("それまでどの言語圏でもほとんど話題がなかった作品が、ある言語圏でまとまって話題になり始めたものです。",
      "Titles with little buzz in any language area that started being talked about in one.")}</p></div>
    ${fresh.length ? `<div class="rv-t pa-t ls-t" role="table">
      <div class="rv-h" role="row"><span>${tr("作品", "Title")}</span><span>${tr("話題になり始めた日", "Started")}</span><span></span><span>${tr("その後", "After")}</span></div>
      <div class="more-box"></div>
    </div>` : `<div class="rv-empty"><div><b>${tr("該当する作品はありません", "None in this period")}</b></div></div>`}`;
  if (fresh.length) A.moreList(document.querySelector("#ls-new .more-box"), fresh.map(frow), DP.rows_first, DP.rows_step);
  // 今日の兆しの文章が取り上げている代表の 1 作品（lead）のカードを、具体例として今日の兆しの中に置く（data から組む。一覧の中は 1 行の参照）
  { const dg = $("ls-sum"); if (dg && lead) dg.insertAdjacentHTML("beforeend", `<div class="ls-ex in-digest">${card(lead)}</div>`); }
})();
