// ダッシュボード（index.html）。data/day/<日>.json の dashboard（事前計算）だけを使う。
// 構成（視線の順）: 紹介 → 表示している日 → 今日の兆し（見出し・説明・作品の列・補足）→ 言語ごとの作品数（地図）→ 今チェックしておきたい作品 → ゲームの動きをもっと見る（いつもより話題が増えた作品・上位の作品）。
// 今日の兆し: AI の解説がその言語にある日はそれを説明に使い、ない日は数から組み立てた事実の文（summary）。この段は消さない。
// 色は言語にだけ使う。並びは人気の順位ではない。作品名は省略しない。判定の基準の数字は書かない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, num, wn, art, ln, lcol } = A, $ = id => document.getElementById(id);
  const G = A.D.dashboard, S = G.summary, L = A.lang, day = G.day, today = G.label;
  const link = w => w && w.id ? `<a class="cardlink" href="${A.workUrl(w.id)}" aria-label="${esc(nm(w.name))}"></a>` : "";
  // グラフの色は CSS の変数から（配色をそろえる。なければ以前の色）
  const cv = (k, d) => (getComputedStyle(document.documentElement).getPropertyValue(k).trim() || d);
  const INK2 = cv("--ink-2", "#3c3958"), INK3 = cv("--ink-3", "#57536f"), TODAY = cv("--today", "#5246c9"), OTHER = cv("--other", "#c9c5dc"),
    NEWC = cv("--today-new", "#9a90e6"), LEFT = cv("--line", "#ebe9f2"), ZERO = cv("--strong", "#9590b0");
  const T = (x, y, s, o = {}) => `<text x="${x}" y="${y}" font-size="${o.size || 14}" fill="${o.fill || INK2}" text-anchor="${o.anchor || "middle"}" font-weight="${o.bold ? 700 : 400}">${s}</text>`;
  const widthOf = el => Math.floor(el.getBoundingClientRect().width);

  /* ---------- 紹介・表示している日 ---------- */
  $("intro").innerHTML = `<div><h2>${tr("世界のゲームのプレイヤーの声から、まだ目立っていない変化を見つける。", "Spot changes not yet in the spotlight, from the voices of game players worldwide.")}</h2>
    <p>${tr("プレイヤーの反応を毎日観測し、作品への関心の高まりや言語圏を越えた広がりをお届けします。", "We observe player reactions every day and show rising interest and spread across language areas.")}</p></div>`;
  A.dayBar($("intro"), "afterend");   // 表示している日は紹介のブロックの下に右寄せ（2026-10-15 のユーザーの指示）

  /* ---------- 今日の兆し ---------- */
  // 先頭の組（G.lead。ADR 0052）: 見出し・本文・引用と作品の列の先頭は、サーバーが 1 つの発見から作った組だけを使う（言語ごとに別の文を選ばない）。
  // kind = finding（今日の兆しの発見の文章）/ aggregate（集計の見出し: 作品自身の普段と比べた変化）。組のない日は集計の要約の文
  const LD = G.lead && G.lead[L] ? G.lead[L] : null;
  const ss = LD && G.lead.kind === "finding" && LD.body.length ? LD.body : null;
  const head = LD ? LD.head : S.head[L];
  const body = LD ? LD.body.join(L === "ja" ? "" : " ") : null;
  const lede = body ? `<span class="lede-t" id="lede-t">${esc(body).replace(/『([^』]+)』/g, (_, n) => `<b class="nb">『${n}』</b>`)}</span>`
    : `${esc(S.lede[L])}${S.basis === "movement" ? "" : tr("たとえば、こんな作品です。", " For example:")}`;
  $("lead").innerHTML = `
    <div class="g-kick"><b>${tr("今日の兆し", "Today's signal")}</b><span class="g-day">${esc(today[L])}</span>
      ${body ? `<button type="button" class="lede-more" aria-controls="lede-t" aria-expanded="false" hidden>${tr("続きを読む", "Read more")}</button>` : ""}</div>
    <h1>${esc(head)}</h1>
    <p class="lede"${ss ? ` data-sents="${esc(JSON.stringify(ss))}"` : ""}>${lede}</p>
    ${LD ? A.cites(LD.cites) : ""}
    <ul class="g-row">${G.featured.map(w => `<li>${link(w)}${art(w)}${wn(w.name, 2)}</li>`).join("")}</ul>
    <div class="g-foot"><span>${tr(`話題になった${G.works_today}作品から${G.featured.length}作品（人数の順ではありません）。`, `${G.featured.length} of the ${G.works_today} titles talked about (not in order of people). `)}${G.movement ? tr(`作品それぞれの普段と比べて目立って動いた作品は${G.movement.q1.changes}作品でした。`, `${G.movement.q1.changes} titles moved notably from their usual level.`) : ""}</span>
      <a href="#trend">${tr("「いつもより話題が増えた作品」で確かめる ↓", "See “Titles talked about more than usual” ↓")}</a></div>`;

  { const t = $("lede-t"), b = document.querySelector(".lede-more");
    if (t && b) { const fit = () => { if (b.getAttribute("aria-expanded") === "true") return; b.hidden = !(t.scrollHeight > t.clientHeight + 2); };
      fit(); if (document.fonts) document.fonts.ready.then(fit); window.addEventListener("resize", fit);
      b.addEventListener("click", () => { const open = b.getAttribute("aria-expanded") !== "true"; b.setAttribute("aria-expanded", String(open)); t.classList.toggle("open", open); b.textContent = open ? tr("閉じる", "Close") : tr("続きを読む", "Read more"); }); } }

  /* ---------- 言語ごとの作品数（地図） ---------- */
  { const O = G.lang_obs, CN = O.countries || {};
    // 作品数の多い順。同じ数のときは言語コードの順（日英で同じ並び。毎回同じ）
    const langs = [...O.langs].sort((a, b) => b.n - a.n || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0));
    // 国・地域 → 話題の作品のある言語圏と役割（p = 主要な社会言語 / s = 共通語・第二言語。ADR 0049）。役割がなければ主要として扱う（従来の対応表）
    const RO = O.country_roles || {}, WHY = O.country_why || {};
    const cmap = {};
    langs.filter(l => l.n > 0).forEach(l => (CN[l.code] || []).forEach(cc => (cmap[cc] = cmap[cc] || []).push({ code: l.code, role: (RO[l.code] || {})[cc] || "p" })));
    const hasShared = Object.values(cmap).some(v => v.some(x => x.role === "s")), hasMulti = Object.values(cmap).some(v => v.filter(x => x.role === "p").length > 1);
    const dd = l => !O.comparable || l.cmp === false ? "—" : l.n === l.prev ? "±0" : (l.n > l.prev ? "＋" : "−") + Math.abs(l.n - l.prev);
    $("world").innerHTML = `
      <div class="sec-h"><h2>${tr("言語ごとに、話題になった作品の数", "Titles talked about, by language")}</h2>
        <p>${tr(`${md(day)} に、それぞれの言語で話題になった作品の数です。右の一覧の行を押すと、その言語の作品一覧が開きます。`, `Titles talked about in each language on ${md(day)}. Click a row to see the list.`)}</p></div>
      <div class="lo">
        <div class="lo-left"><div class="lo-map">${window.WORLD_SVG || ""}</div>
          <div class="lo-legend">
            <span><i class="lo-sw-solid" aria-hidden="true"></i>${tr("その言語が主に使われる国・地域", "Main language of the country")}</span>
            ${hasShared ? `<span><i class="lo-sw-thin" aria-hidden="true"></i>${tr("共通語・第二言語として広く使われる国・地域", "Widely used as a common or second language")}</span>` : ""}
            ${hasMulti ? `<span><i class="lo-sw-multi" aria-hidden="true"></i>${tr("主な言語が複数ある国・地域", "Several main languages")}</span>` : ""}
            ${(O.incomplete || []).length ? `<span><i class="lo-sw-pend" aria-hidden="true"></i>${tr("集計中の言語圏", "Language area still being tallied")}</span>` : ""}
            ${(O.thin || []).length ? `<span><i class="lo-sw-thinobs" aria-hidden="true"></i>${tr("観測が届いていない言語圏", "Language area not yet well observed")}</span>` : ""}
          </div>
          <details class="lo-more"><summary>${tr("地図の見方: 色は投稿の言語が使われる国・地域で、投稿者の所在地ではありません", "How to read the map: colors show where the posts' language is spoken, not where the posters live")}</summary>
            <p class="lo-note">${tr("世界の各言語圏で話題になっているゲームを表示しています。地域の色は投稿言語の広がりを示し、投稿者の所在地を示すものではありません。",
              "Games talked about in each language area of the world. Colors show where the language of the posts is spoken, not where the posters live.")}</p>
            <p class="lo-note">${tr("色のない地域は、観測した言語との対応がない・観測が届いていない地域です。ゲームが遊ばれていないという意味ではありません。押すと言語圏の作品とプレイヤーの声へ進めます。",
              "Uncolored areas have no match with the observed languages or are not yet observed; it does not mean the game is not played there. Tap to see titles and player voices.")}</p>
            ${langs.map(A.scopeNote).filter(Boolean).map(t => `<p class="lo-scope">${tr("観測の範囲", "Observation scope")}: ${esc(t)}</p>`).join("")}</details></div>
        <div class="lo-side">
          <div class="lo-head"><span>${tr("言語", "Language")}</span><span class="r">${tr("作品", "Titles")}</span><span class="r">${tr("前日比", "vs. prev.")}</span><span></span></div>
          <ul class="lo-list"></ul>
        </div>
      </div>`;
    // 一覧: 初めの langs_first 行を描き、残りの言語と「ほかに観測した言語」「集計中の言語」は「もっと見る」で開く（common.js の moreList）。
    // 一覧の長さで段が伸び、地図の下に空白が残らないように（#27）。行ごとの言語の数はボタンの文言（残りの言語の数）に使う
    const rows = langs.map(l => [1, `<li><a class="lo-row" href="lang.html?l=${encodeURIComponent(l.code)}" data-code="${esc(l.code)}" style="--lc:${lcol(l.code)}">
            <span class="lo-name"><i class="sw"></i>${esc(ln(l.code))}</span><span class="lo-n"><b>${l.n}</b></span>
            <span class="lo-d${O.comparable && l.cmp !== false && l.n > l.prev ? " up" : O.comparable && l.cmp !== false && l.n < l.prev ? " down" : ""}">${dd(l)}</span><span class="lo-go" aria-hidden="true">›</span></a></li>`]);
    if (O.zero.length) rows.push([O.zero.length, `<li class="lo-zero"><span class="lo-name"><i class="sw"></i>${tr(`ほかに観測した${O.zero.length}言語`, `${O.zero.length} more language(s) observed`)}</span><span class="lo-zn">${tr("話題になった作品はなし", "No title talked about")}（${O.zero.map(z => esc(ln(z.code))).join(tr("・", ", "))}）</span></li>`]);
    if ((O.incomplete || []).length) rows.push([O.incomplete.length, `<li class="lo-zero lo-pend"><span class="lo-name"><i class="sw"></i>${tr(`集計中の${O.incomplete.length}言語`, `${O.incomplete.length} language(s) still being tallied`)}</span><span class="lo-zn">${tr("この日の集計がまだ終わっていません", "Not finished for this day yet")}（${O.incomplete.map(z => esc(ln(z.code))).join(tr("・", ", "))}）</span></li>`]);
    const first = Math.min(rows.length, (G.display || {}).langs_first ?? rows.length);
    A.moreList(document.querySelector(".lo-list"), rows.map(r => r[1]), first, rows.length, rest => {
      const k = rows.slice(rows.length - rest).reduce((s, r) => s + r[0], 0);
      return tr(`もっと見る（ほか${num(k)}言語）`, `Show ${num(k)} more language(s)`); });
    const svg = document.querySelector(".lo-map svg"), mapEl = document.querySelector(".lo-map"), side = document.querySelector(".lo-side");
    if (svg) {
      const byCode = Object.fromEntries(langs.map(l => [l.code, l]));
      // 国・地域 → この日に話題の作品のある言語圏（多対多。ADR 0049）。1 つなら単色、複数なら縞。国で数は足さない
      const defs = svg.querySelector("defs") || svg.insertBefore(document.createElementNS("http://www.w3.org/2000/svg", "defs"), svg.firstChild);
      const NEUTRAL = "#f1f0f7";
      const pattern = (prim, shar) => {   // 主要な言語（塗り・複数なら太い縞）の上に、共通語の細い斜線を重ねる
        const id = `lo-p-${prim.join("_") || "none"}-${shar.join("_")}`;
        if (!svg.getElementById(id)) {
          const u = 8, w = u * Math.max(prim.length, shar.length, 1);
          const base = prim.length ? prim.map((c, i) => `<rect x="${i * w / prim.length}" y="0" width="${w / prim.length}" height="${w}" fill="${lcol(c)}"/>`).join("")
            : `<rect x="0" y="0" width="${w}" height="${w}" fill="${NEUTRAL}"/>`;
          const thin = shar.length ? Array.from({ length: w / u }, (_, i) => `<rect x="${i * u + u / 2 - 1.3}" y="0" width="2.6" height="${w}" fill="${lcol(shar[i % shar.length])}"/>`).join("") : "";
          defs.insertAdjacentHTML("beforeend", `<pattern id="${id}" patternUnits="userSpaceOnUse" width="${w}" height="${w}" patternTransform="rotate(45)">${base}${thin}</pattern>`);
        }
        return `url(#${id})`;
      };
      // 集計中の言語圏（収集・同定・判定が終わっていない）: その言語が主に使われる国・地域を点の模様で示す（0 作品・観測なしと見せない。ADR 0048）
      const PEND = (O.incomplete || []).map(z => z.code);
      if (PEND.length && !svg.getElementById("lo-pend")) defs.insertAdjacentHTML("beforeend", `<pattern id="lo-pend" patternUnits="userSpaceOnUse" width="7" height="7"><rect width="7" height="7" fill="${NEUTRAL}"/><circle cx="3.5" cy="3.5" r="1.3" fill="#a7a3bd"/></pattern>`);
      PEND.forEach(code => Object.entries(RO[code] || {}).forEach(([cc, role]) => { if (role !== "p" || cmap[cc]) return;
        svg.querySelectorAll(`#${cc}, #${cc} path`).forEach(n => { n.style.fill = "url(#lo-pend)"; n.dataset.pend = code; n.dataset.cc = cc; n.classList.add("lo-c", "lo-pc"); }); }));
      // 観測が届いていない言語圏（観測源でその言語の投稿がまだ少ない）: 主要な社会言語の国をごく薄い斜線で示す（人気・関心の低さではない）
      const THIN = O.thin || [];
      if (THIN.length && !svg.getElementById("lo-thin")) defs.insertAdjacentHTML("beforeend", `<pattern id="lo-thin" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)"><rect width="6" height="6" fill="#ecebf2"/><rect x="0" y="0" width="1.8" height="6" fill="#b4aecb"/></pattern>`);
      THIN.forEach(t => Object.entries(RO[t.code] || {}).forEach(([cc, role]) => { if (role !== "p" || cmap[cc] || PEND.some(c => (RO[c] || {})[cc] === "p")) return;
        svg.querySelectorAll(`#${cc}, #${cc} path`).forEach(n => { if (n.dataset.thin) return; n.style.fill = "url(#lo-thin)"; n.dataset.thin = t.code; n.dataset.cc = cc; n.classList.add("lo-c", "lo-tc"); }); }));
      const thinBy = Object.fromEntries(THIN.map(t => [t.code, t]));
      Object.entries(cmap).forEach(([cc, xs]) => {
        const prim = xs.filter(x => x.role === "p").map(x => x.code), shar = xs.filter(x => x.role === "s").map(x => x.code);
        const fill = prim.length === 1 && !shar.length ? lcol(prim[0]) : pattern(prim, shar);
        const codes = xs.map(x => x.code);
        svg.querySelectorAll(`#${cc}, #${cc} path`).forEach(n => { n.style.fill = fill; n.dataset.lc = codes[0]; n.dataset.lcs = codes.join(","); n.dataset.cc = cc; n.classList.add("lo-c"); });
      });
      const tip = document.createElement("div"); tip.className = "lo-tip"; mapEl.appendChild(tip);
      const diffText = l => !O.comparable ? tr("比較データなし", "No comparison") : l.n === l.prev ? tr("前日比 ±0", "±0 vs. prev.") : tr(`前日比 ${dd(l)}作品`, `${dd(l)} vs. prev.`);
      const one = l => { const ex = l.works.slice(0, 3).map(w => esc(nm(w.name)));
        return `<b style="--lc:${lcol(l.code)}"><i></i>${esc(ln(l.code))}</b><span class="tn"><em>${l.n}</em>${tr("作品", " titles")}・${diffText(l)}</span>${ex.length ? `<span class="te">${tr("例: ", "e.g. ")}${ex.join(tr("、", ", "))}</span>` : ""}`; };
      const roleLabel = (code, cc) => (RO[code] || {})[cc] === "s" ? tr("共通語・第二言語として", "as a common or second language") : tr("主に使われる言語", "main language");
      const why = (code, cc) => cc && (WHY[code] || {})[cc] ? `<span class="twhy">${esc(WHY[code][cc])}</span>` : "";
      const on = (code, ev, codes, cc) => {
        codes = codes || (code ? [code] : []);
        mapEl.classList.toggle("focus", !!code);
        svg.querySelectorAll(".lo-c").forEach(n => n.classList.toggle("hit", codes.some(c => (n.dataset.lcs || "").split(",").includes(c))));
        side.querySelectorAll(".lo-row").forEach(r => r.classList.toggle("hit", codes.includes(r.dataset.code)));
        const ls = codes.map(c => byCode[c]).filter(Boolean); if (!ls.length) { tip.style.display = "none"; return; }
        const per = l => one(l) + (cc ? `<span class="trole">${tr(`この国・地域では${roleLabel(l.code, cc)}`, `Here: ${roleLabel(l.code, cc)}`)}</span>${L === "ja" ? why(l.code, cc) : ""}` : "");
        tip.innerHTML = ls.length === 1 ? per(ls[0]) + `<span class="tgo">${tr("押すと作品一覧へ", "Click for the list")}</span>`
          : `<span class="tmulti">${tr(`この国・地域は${ls.length}つの言語圏に属しています`, `This country belongs to ${ls.length} language areas`)}</span>` + ls.map(per).join("") + `<span class="tgo">${tr("押すと言語を選べます", "Click to choose a language")}</span>`;
        tip.style.display = "block";
        const r = mapEl.getBoundingClientRect(); let x, y;
        if (ev && ev.clientX) { x = ev.clientX - r.left + 14; y = ev.clientY - r.top + 14; }
        else { const bb = [...svg.querySelectorAll(".lo-c.hit")].map(n => n.getBoundingClientRect()).sort((a, b) => b.width * b.height - a.width * a.height)[0]; const tw = tip.offsetWidth; x = bb ? (bb.left - r.left - tw - 12 >= 8 ? bb.left - r.left - tw - 12 : bb.right - r.left + 12) : 20; y = bb ? bb.top - r.top : 20; }
        tip.style.left = Math.max(4, Math.min(x, r.width - tip.offsetWidth - 8)) + "px"; tip.style.top = Math.max(4, Math.min(y, r.height - tip.offsetHeight - 8)) + "px";
      };
      const pick = document.createElement("div"); pick.className = "lo-pick"; pick.setAttribute("role", "dialog"); mapEl.appendChild(pick);
      const closePick = () => { pick.style.display = "none"; };
      const pendTip = (n, e) => { mapEl.classList.remove("focus");
        tip.innerHTML = `<b style="--lc:#a7a3bd"><i></i>${esc(ln(n.dataset.pend))}</b><span class="trole">${tr("この日の集計がまだ終わっていません（観測していないわけではありません）", "Still being tallied for this day (not unobserved)")}</span>`;
        tip.style.display = "block"; const r = mapEl.getBoundingClientRect();
        tip.style.left = Math.max(4, Math.min(e.clientX - r.left + 14, r.width - tip.offsetWidth - 8)) + "px"; tip.style.top = Math.max(4, Math.min(e.clientY - r.top + 14, r.height - tip.offsetHeight - 8)) + "px"; };
      svg.addEventListener("mousemove", e => { if (pick.style.display === "block") return; const n = e.target.closest(".lo-c");
        if (n && n.dataset.pend) return pendTip(n, e);
        if (n && n.dataset.thin) { mapEl.classList.remove("focus");
          const tn = A.thinNote(thinBy[n.dataset.thin]);
          tip.innerHTML = `<b style="--lc:#b9b4cf"><i></i>${esc(ln(n.dataset.thin))}</b><span class="trole">${tr("まだ十分に観測できていない言語圏です（ゲームが遊ばれていないという意味ではありません）", "Not yet well observed (this does not mean the game is not played here)")}</span>${tn ? `<span class="twhy">${esc(tn.stage)}。${esc(tn.counts)}</span>` : ""}`;
          tip.style.display = "block"; const r = mapEl.getBoundingClientRect();
          tip.style.left = Math.max(4, Math.min(e.clientX - r.left + 14, r.width - tip.offsetWidth - 8)) + "px"; tip.style.top = Math.max(4, Math.min(e.clientY - r.top + 14, r.height - tip.offsetHeight - 8)) + "px"; return; }
        on(n ? n.dataset.lc : null, e, n ? n.dataset.lcs.split(",") : null, n ? n.dataset.cc : null); });
      svg.addEventListener("mouseleave", () => { if (pick.style.display !== "block") on(null); });
      svg.addEventListener("click", e => {
        const n = e.target.closest(".lo-c"); if (!n) { closePick(); on(null); return; }
        if (n.dataset.pend) { location.href = `lang.html?l=${encodeURIComponent(n.dataset.pend)}`; return; }   // 集計中の説明の言語ページへ
        if (n.dataset.thin) { location.href = `lang.html?l=${encodeURIComponent(n.dataset.thin)}`; return; }   // 観測が届いていない説明の言語ページへ
        const codes = n.dataset.lcs.split(",");
        if (codes.length === 1) { location.href = `lang.html?l=${encodeURIComponent(codes[0])}`; return; }
        // 複数の言語圏: 言語を選ばせる（スマートフォンでも押して選べる）。選んだ言語の作品とプレイヤーの声のページへ
        tip.style.display = "none";
        pick.innerHTML = `<p>${tr("どの言語圏の作品を見ますか", "Which language area?")}</p>` + codes.map(c => byCode[c]).filter(Boolean).map(l =>
          `<a href="lang.html?l=${encodeURIComponent(l.code)}" style="--lc:${lcol(l.code)}"><i></i>${esc(ln(l.code))}<b>${l.n}${tr("作品", " titles")}</b></a>`).join("") +
          `<button type="button" class="lo-pick-x">${tr("閉じる", "Close")}</button>`;
        pick.style.display = "block";
        const r = mapEl.getBoundingClientRect();
        pick.style.left = Math.max(4, Math.min(e.clientX - r.left + 8, r.width - pick.offsetWidth - 8)) + "px";
        pick.style.top = Math.max(4, Math.min(e.clientY - r.top + 8, r.height - pick.offsetHeight - 8)) + "px";
        pick.querySelector(".lo-pick-x").addEventListener("click", ev => { ev.stopPropagation(); closePick(); on(null); });
        on(codes[0], null, codes);
        tip.style.display = "none";   // 選ぶ枠だけを出す（説明の枠と重ねない）
      });
      // 一覧の行 → 地図の言語圏を強調（一覧の枠で受ける。「もっと見る」で後から足した行も同じ）
      const rowCode = e => (e.target.closest(".lo-row") || {}).dataset?.code || null;
      side.addEventListener("mouseover", e => on(rowCode(e))); side.addEventListener("mouseleave", () => on(null));
      side.addEventListener("focusin", e => on(rowCode(e))); side.addEventListener("focusout", () => on(null));
    }
  }

  /* ---------- 今チェックしておきたい作品（本番のその日のカード。並びも本番のまま。順位ではない） ---------- */
  { const CK = G.checks;
    const first = c => String((c.first || {})[L] || "").replace(/\s*\d+〜\d+時/, "").replace(/,\s*\d+–\d+h/, "");
    const grow = c => c.grow && c.grow[0] != null && c.grow[1] != null ? tr(`${c.grow[0]}人→${c.grow[1]}人`, `${c.grow[0]}→${c.grow[1]} people`) : "";
    const nl = c => (c.new_langs || []).map(x => x[L]).join(tr("・", ", "));
    const meta = c => [`${tr("初検知", "First seen")} ${first(c)}${grow(c) ? `・${grow(c)}` : ""}`, `${tr("その後", "After")}: ${(c.after || {})[L] || ""}`,
      ...(nl(c) ? [`${tr("新しい言語圏", "New language areas")}: ${nl(c)}`] : [])].join(" ・ ");
    const small = c => `<li class="ck2" data-cls="${esc(c.cls || "")}">${link(c)}${art(c)}<div class="ck2-t">${wn(c.name, 1)}<span class="ck2-l"><i>${esc((c.label || {})[L] || "")}</i>${esc((c.line || {})[L] || "")}</span><span class="ck2-m" title="${esc(meta(c))}">${esc(meta(c))}</span></div></li>`;
    if (!CK.length) {
      $("others").innerHTML = `<h2 class="g-h">${tr("今チェックしておきたい作品", "Worth a look now")}</h2><div class="rv-empty"><div><b>${tr("この日に動き始めた作品は見つかりませんでした", "No title started moving on this day")}</b></div></div>`;
    } else {
      const top = CK[0], rest = CK.slice(4);
      $("others").innerHTML = `
      <h2 class="g-h">${tr("今チェックしておきたい作品", "Worth a look now")}<small>${tr(`それまで静かだった作品が、いま動き始めた（順位ではありません）。この日に見つかった${CK.length}作品から。`, `Titles that were quiet and just started moving (not a ranking). From ${CK.length} found on this day.`)}</small></h2>
      <div class="ckg">
        <article class="ck1" data-cls="${esc(top.cls || "")}">${link(top)}<div class="ck1-bg">${art(top)}</div>
          <div class="ck1-t">
            <div class="ck1-k"><span class="pick">${tr("今日の注目", "Today's pick")}</span><span class="lab">${esc((top.label || {})[L] || "")}</span></div>
            ${wn(top.name, 2, "h3")}
            <p class="ck1-line">${esc((top.line || {})[L] || "")}</p>
            <div class="ck1-chips"><span><em>${tr("その後", "After")}</em>${esc((top.after || {})[L] || "")}</span><span><em>${tr("広がり", "Spread")}</em>${esc((top.spread || {})[L] || "—")}</span><span><em>${tr("初検知", "First seen")}</em>${esc(first(top))}${grow(top) ? `・${esc(grow(top))}` : ""}</span></div>
          </div>
          <div class="ck1-im">${art(top)}</div>
        </article>
        <ul class="ck-side">${CK.slice(1, 4).map(small).join("")}</ul>
      </div>
      ${rest.length ? `<div class="ck-more"><h3 class="ck-rh"><span>${tr(`ほかに動き始めた${rest.length}作品`, `${rest.length} more title(s) starting to move`)}</span>
        <span class="ck-key" aria-hidden="true">${[["surge", "急増・新規", "Jump / new"], ["cont", "継続", "Keeps going"], ["re", "再浮上", "Back again"], ["overseas", "言語圏の広がり", "New languages"]]
          .filter(([k]) => CK.some(c => c.cls === k || (k === "surge" && c.cls === "new"))).map(([k, ja, en]) => `<span data-cls="${k}">${tr(ja, en)}</span>`).join("")}</span></h3><ul class="ck-rest" id="ckrest"></ul></div>` : ""}`;
      if (rest.length) A.moreList($("ckrest"), rest.map(small), (G.display || {}).moves_first, (G.display || {}).moves_first);   // 2 列・3 列で段に穴を空けない数ずつ（#55）
    }
  }

  /* ---------- ゲームの動きをもっと見る（いつもより話題が増えた作品。web/movement.py の分析。全 Source 共通の系列と Signal 発見） ---------- */
  // 数を並べる段ではなく、作品それぞれの普段と比べて何が変わったかを伝える段（2026-10-16 のユーザーの指示）。分析の結果に応じて文と項目の数を変える
  const MV = G.movement, TOP = G.top;
  const OS = G.obs_status || (G.complete ? "complete" : "partial");
  const obsNote = OS === "complete" || OS === "recovered" ? "" : `<p class="mv-partial">${tr(`${md(day)} は一部の時間に観測が途切れたため、人数が実際より少ない可能性があります。`, `${md(day)} was only partly observed, so counts may be low.`)}</p>`;
  // 作品自身の直近 14 日の人数（観測していない日は空き）。今日を強調し、普段（中央値）を線で示す。変化の理解に役立つときだけ置く
  const spark = (sp, base) => { if (!sp) return ""; const W = 120, H = 34, xs = sp.n, mx = Math.max(1, base || 0, ...xs.filter(v => v != null)), bw = W / xs.length;
    let g = xs.map((v, i) => v == null ? "" : `<rect x="${i * bw + 1}" y="${H - (v / mx) * (H - 2)}" width="${bw - 2}" height="${(v / mx) * (H - 2)}" fill="${i === xs.length - 1 ? "var(--accent)" : "var(--line-strong, #c9c2e6)"}"/>`).join("");
    if (base != null) g += `<line x1="0" x2="${W}" y1="${H - (base / mx) * (H - 2)}" y2="${H - (base / mx) * (H - 2)}" stroke="var(--ink-3)" stroke-dasharray="3 3"/>`;
    return `<svg class="mv-sp" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${tr("直近14日の人数（点線は普段）", "Last 14 days (dashed: usual level)")}">${g}</svg>`; };
  // いつもより話題が増えた作品のカード（#28。2026-10-25 のユーザーの指示で Q1・Q2 を 1 つのブロックにした）:
  // 画像 → 作品名 → 何が起きたかの 1 文（主役）→ 人数・普段との差（脇役）と、直近 14 日の人数のグラフ（データのある作品）。分類の札・言語・人数の内訳は初めの表示に出さない
  // 主役の文 = その日の出来事（publication/work_events が行の人数と同じ投稿から作り、原文で確かめた文）。出来事がなくプレイヤー自身の感想だけなら「プレイヤーの声：」と書く
  // （ニュース・告知と感想を取り違えない）。どちらもない作品は文を出さない（推測で埋めない・分析の側の事情を読者に見せない）。文のある作品を先に並べる
  const main = x => { const w = x.what || {};
    if (w.event) return tr(w.event.ja, w.event.en);
    if (w.reaction) return tr(`プレイヤーの声：${w.reaction.ja}`, `Fans: ${w.reaction.en}`);
    return ""; };
  const told = xs => [...xs.filter(x => main(x)), ...xs.filter(x => !main(x))];
  // 補足: 人数ではない短い言葉だけ（カードの人数は 1 つの取得元の数で、下の一覧の全取得元の合計と食い違って見えるので出さない。2026-10-25 のユーザーの指示）。推移はグラフで見せる
  const subQ1 = x => x.kind === "new_language" ? tr(`${(x.new_langs || []).map(c => ln(c)).join("・")}でも話題に`, `also in ${(x.new_langs || []).map(c => ln(c)).join(", ")}`)
    : x.kind === "continuing" ? tr(`増えて${x.streak}日目`, `day ${x.streak} of the rise`)
    : x.kind === "emergence" ? tr("初めて話題に", "first time") : tr("普段より増えた", "above its usual level");
  // 作品カード: 画像 | 作品名 → 何が起きたかの 1 文 → 補足と出典 → 直近 14 日のグラフ（下端に横幅いっぱい）
  const card = (x, sub) => { const w = x.what || {}, url = (w.event || w.reaction || {}).post_url;
    const meta = [esc(sub), url ? `<a class="mv-src" href="${esc(url)}" target="_blank" rel="noopener">${tr("元の投稿", "post")}</a>` : "", A.srcNote(x)].filter(Boolean).join("");
    return `<li class="mv-card">${link(x)}${art(x)}<div class="mv-c">${wn(x.name, 2, "b")}
      ${main(x) ? `<p class="mv-main">${esc(main(x))}</p>` : ""}<p class="mv-sub">${meta}</p>${spark(x.spark, x.base)}</div></li>`; };
  const DPm = G.display || {};
  const listOf = (id, rows, first) => { const el = document.getElementById(id); if (el && rows.length) A.moreList(el, rows, first == null ? rows.length : first, DPm.rows_step || rows.length); };
  let q1 = "";
  if (!MV) {
    q1 = `<p class="mv-a">${tr("この日の分析はありません。", "No analysis for this day.")}</p>`;
  } else {
    // ブロックは見出しで何の一覧かが分かるので、前置きの文は置かない（2026-10-25 のユーザーの指示: 読者に長い文を読ませない）。ないときだけ 1 行で言う
    const a = MV.q1;
    q1 = `${obsNote}${a.featured.length ? `<ul class="mv-cards" id="mv-q1"></ul>` : `<p class="mv-a">${tr("この日は、いつもより話題が増えた作品はありませんでした。", "No title rose above its usual level on this day.")}</p>`}`;
  }
  $("more").innerHTML = `
    <div class="sec-h"><h2>${tr("ゲームの動きをもっと見る", "More on today's movement")}</h2><p>${tr("作品それぞれの普段と比べて、この日に何が変わったかを確かめられます。", "See what changed on this day compared with each title's usual level.")}</p></div>
    <div class="mv">
      <article class="mv-q" id="trend">
        <h3>${tr("いつもより話題が増えた作品", "Titles talked about more than usual")}</h3>${q1}</article>
    </div>
    <section class="mv-list" id="rank"><h3 class="mv-lh">${tr(`${md(day)} に話題が多かった${TOP.length}作品`, `${TOP.length} most talked-about titles on ${md(day)}`)}<small>${tr("人数の順", "by people")}</small></h3>
      <ul class="rank">${TOP.map(t => `<li class="${t.first ? "first" : ""}">${link(t)}${art(t)}<div class="rk">${wn(t.name, 1, "span")}${t.first ? `<span class="tagfirst">${tr("初めて話題に", "First seen")}</span>` : ""}<div class="bar"><span style="width:${t.n / (TOP[0] || t).n * 100}%"></span></div></div><em>${esc(A.ppl(t.n))}</em></li>`).join("")}</ul>
      <p class="mv-note">${tr("人気の順位ではなく、この日の観測の人数です。「初めて話題に」は、このサイトで初めて話題になった作品です（新作という意味ではありません）。", "Not a popularity ranking: people observed on this day. “First seen” means first talked about on this site, not a new release.")}</p></section>`;
  document.addEventListener("click", e => { if (!e.target.closest('a[href="#trend"]')) return;
    const q = $("trend"); q.classList.remove("flash"); void q.offsetWidth; q.classList.add("flash"); });
  if (MV) {   // いつもより話題が増えた作品の一覧: 初めの数件を描き、残りは「もっと見る」で開く（件数は config/pages.toml [display]。全件はデータにある。#24）
    listOf("mv-q1", told(MV.q1.featured).map(x => card(x, subQ1(x))), DPm.moves_first);
  }
  if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) setTimeout(() => t.scrollIntoView(), 0); }
})();
