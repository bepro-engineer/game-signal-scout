// 再燃している作品（revival.html）。data/pages.json の revival（事前計算: 本番の judge_revival の作品と、話題が落ち着いている作品）だけを使う。
// 構成: この日の再燃（文章）→ 帯 → 再燃した作品（本番の定義のまま。0 件のときは短い空の表示）→ 話題が落ち着いている作品（1 行 1 作品。最近落ち着いた作品だけ。
// 再燃の候補は初めの rows_step 件〔#55〕、最近静かになった作品は区分ごと畳む。Issue #16・#22）。再燃した作品も初めの数件（#55）。
// 公開する画面に判定の基準（何日・何人）を書かない。落ち着いている作品を「再燃しそう」などと予測の言葉で呼ばない。作品名は省略しない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, wn, art, AIR } = A, P = A.P, R = P.revival, $ = id => document.getElementById(id);
  const W = R.watch, rev = R.items, day = P.as_of, DP = P.display, maxQ = W.length ? Math.max(...W.map(w => w.quiet)) : 0;
  const link = w => `<a class="cardlink" href="${A.workUrl(w.id)}" aria-label="${esc(nm(w.name))}"></a>`;

  /* ---------- この日の再燃 ---------- */
  $("rv-sum").innerHTML = `<div class="g-kick"><b>${tr("今日の兆し", "Today's signal")}</b><span class="g-day">${tr("この日の再燃", "Heating up again")}・${esc(P.label[A.lang])}</span></div>
    <p class="dg-t">${rev.length ? tr(`${md(day)}の時点で、${rev.length}作品が再び話題になっています。`, `As of ${md(day)}, ${rev.length} title(s) are being talked about again.`)
      : tr(`${md(day)}の時点で、再燃した作品はありません。長く静かだった作品が再び話題になった例は、まだ見つかっていません。`, `As of ${md(day)}, no title has heated up again. We have not yet seen a long-quiet title come back.`)}
      ${W.length ? tr(`以前に話題になり、その後反応が落ち着いている作品は${W.length}作品です。そのうち${W.filter(w => w.candidate).length}作品は、再び話題になれば再燃となる候補です。静かな日を確認できた期間は、いちばん長い作品で${maxQ}日です。`,
        `${W.length} title(s) were talked about before and have been quiet since; ${W.filter(w => w.candidate).length} of them would count as heating up again if talked about again. The longest quiet stretch we could confirm is ${maxQ} day(s).`) : ""}</p>`;

  /* ---------- 帯 ---------- */
  $("rv-bar").innerHTML = `<span class="all">${tr(`${md(day)}の再燃`, `Heating up again · ${md(day)}`)}</span>
    <a href="#rv-revived">${tr("再燃した作品", "Heating up again")} <b>${rev.length}</b></a><a href="#rv-watch">${tr("話題が落ち着いている作品", "Quiet titles")} <b>${W.length}</b></a>`;

  /* ---------- 再燃した作品: 4 つの段階と、1 本の時間軸（以前の盛り上がり → 静かな期間 → 再び話題に → その後） ---------- */
  const ST = { continuing: [tr("その後も続いている", "Still going"), "on"], faded: [tr("すぐ落ち着いた", "Faded quickly"), "off"], unknown: [tr("その後はこれから", "Too early to tell"), "tbd"] };
  const days = P.days;
  const chart = w => {
    const e = w.ev, s = w.series, N = s.length, W0 = 600, H = 176, top = 38, base = 134, bw = W0 / N, mx = Math.max(1, ...s);
    const at = d => days.indexOf(d), x = i => i * bw, y = n => base - (n / mx) * (base - top);
    const q0 = at(e.quiet_from), q1 = at(e.quiet_to), rv = at(e.revived_day), pk = at(e.before_day);
    const ph = i => i === pk ? "pk" : i === rv ? "rv" : i > rv && rv >= 0 ? "aft" : q0 >= 0 && i >= q0 && i <= q1 ? "qt" : "pre";
    const bars = s.map((n, i) => P.observed[i] === "n" ? `<rect class="na" x="${x(i) + 3}" y="${top}" width="${bw - 6}" height="${base - top}" rx="3"/>`
      : `<rect class="${ph(i)}" x="${x(i) + 3}" y="${Math.min(y(n), base - 2)}" width="${bw - 6}" height="${Math.max(base - y(n), 2)}" rx="3"/>`).join("");
    const band = q0 >= 0 && q1 >= 0 ? `<rect class="band-q" x="${x(q0)}" y="${top - 20}" width="${x(q1 + 1) - x(q0)}" height="${base - top + 20}" rx="6"/><text class="bl q" x="${(x(q0) + x(q1 + 1)) / 2}" y="${top - 6}" text-anchor="middle">${tr(`静かな期間 ${e.quiet_days}日`, `Quiet ${e.quiet_days} days`)}</text>` : "";
    return `<svg class="rvx-ch" viewBox="0 0 ${W0} ${H}" role="img" aria-label="${esc(nm(w.name))}">${band}${bars}<line class="axis" x1="0" x2="${W0}" y1="${base + .5}" y2="${base + .5}"/>
      <text class="dt" x="14" y="${base + 24}">${md(days[0])}</text>${rv >= 0 ? `<text class="dt rv" x="${x(rv) + bw / 2}" y="${base + 24}" text-anchor="middle">${md(days[rv])}</text>` : ""}<text class="dt" x="${W0}" y="${base + 24}" text-anchor="end">${md(days.at(-1))}</text></svg>`; };
  const revCard = w => { const e = w.ev; return `<article class="rvx">${link(w)}${art(w)}
      <div class="rvx-t">${wn(w.name, 2, "h3")}<span class="rv-air">${esc(AIR[w.rs] || "")}</span>${A.srcNote(w)}
        <ol class="rvx-steps">
          <li class="pk"><span>${tr("以前の盛り上がり", "Earlier peak")}</span><span class="v"><b>${md(e.before_day)}</b> ${esc(A.ppl(e.before_peak))}</span></li>
          <li class="qt"><span>${tr("静かな期間", "Quiet period")}</span><span class="v"><b>${tr(`${e.quiet_days}日`, `${e.quiet_days} days`)}</b> ${md(e.quiet_from)}〜${md(e.quiet_to)}</span></li>
          <li class="rv"><span>${tr("再び話題に", "Back again")}</span><span class="v"><b>${md(e.revived_day)}</b> ${esc(A.ppl(e.revive_authors))}</span></li>
          <li class="aft"><span>${tr("その後", "After")}</span><span class="v"><em class="st ${(ST[e.status] || ST.unknown)[1]}">${(ST[e.status] || ST.unknown)[0]}${e.status === "continuing" ? tr(`（${e.cont_days}日）`, ` (${e.cont_days} days)`) : ""}</em></span></li>
        </ol></div>
      <div class="rvx-g">${chart(w)}</div></article>`; ; };
  $("rv-revived").innerHTML = `<div class="sec-h"><h2>${tr("再燃した作品", "Titles heating up again")}<small class="cnt">${A.works(rev.length)}</small></h2><p>${tr("しばらく静かだった作品が、再び話題になったものです。", "Titles that had been quiet and are being talked about again.")}${rev.length > 1 ? tr("再び話題になった日の人数が多い順です。", " Most people on the day they came back first.") : ""}</p></div>
    ${rev.length ? `<div class="rvx-list" id="rvx-list"></div>`
      : `<div class="rv-empty"><span class="ic"><svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4"/></svg></span>
      <div><b>${tr("この日に再燃した作品はありません", "No title heated up again on this day")}</b><p>${tr("静かな期間のあとに再び話題になった作品が見つかると、ここに表示します。", "When a title comes back after a quiet period, it will be shown here.")}</p></div></div>`}`;

  /* ---------- 話題が落ち着いている作品: 1 行 1 作品。「○/○に○人が話題に」→「静かな日を○日確認」 ----------
     再燃の候補（静かな期間が再燃の判定の条件に届いた作品。data の candidate）は初めの rows_step 件を見せ、残りは「もっと見る」（#55。以前は全部）。次に話題になれば再燃になるので、このページで先に見る作品。
     最近静かになった作品（まだ候補でない。放送の合間のことが多い）は区分ごと畳む（Issue #22: 規則の見えない先頭 4 件だけを見せる折りたたみをやめた）。
     どちらも以前に話題にした人（最後に話題になった日の人数。行に出る数）の多い順（data の並び） */
  const pq = w => w.partial_quiet ? `<sup class="pq" tabindex="0" title="${esc(tr(`ほかに一部だけ観測した日が${w.partial_quiet}日あります（静かな日には数えていません）`, `${w.partial_quiet} more partly observed day(s), not counted as quiet`))}">＊</sup>` : "";
  const row = w => `<div class="rv-r" role="row">${link(w)}${art(w)}
        <div class="rv-n" role="cell">${wn(w.name, 2, "h3")}<span class="rv-air">${esc(AIR[w.rs] || "")}</span>${A.srcNote(w)}</div>
        <div class="rv-last" role="cell">${tr(`<b>${md(w.last)}</b>に<b>${w.last_n}人</b>が話題に`, `<b>${w.last_n}</b> people on <b>${md(w.last)}</b>`)}</div><span class="ar" aria-hidden="true">→</span>
        <div class="rv-q" role="cell">${tr(`静かな日を<b>${w.quiet}日</b>確認`, `<b>${w.quiet}</b> quiet day(s) confirmed`)}${pq(w)}</div></div>`;
  const C = W.filter(w => w.candidate), Rn = W.filter(w => !w.candidate);
  $("rv-watch").innerHTML = `<div class="sec-h"><h2>${tr("話題が落ち着いている作品", "Titles that have gone quiet")}<small class="cnt">${A.works(W.length)}</small></h2><p>${tr("以前に話題になり、その後反応が落ち着いた作品です。「再燃の候補」は静かな期間が十分に続いた作品で、再び話題になれば再燃した作品として上に載ります。どちらも、最後に話題になった日の人数が多い順です。",
      "Titles that were talked about before and have gone quiet. \"Candidates\" have been quiet long enough: if they are talked about again, they move up as titles heating up again. Both lists put the most people on the last day they were talked about first.")}</p></div>
    ${W.length ? `<div class="rv-t" role="table">
      <div class="rv-h" role="row"><span>${tr("作品", "Title")}</span><span>${tr("最後に話題になった日", "Last talked about")}</span><span></span><span>${tr("その後の観測", "Since then")}</span></div>
      ${C.length ? `<div class="rv-g" role="row"><span>${tr("再燃の候補", "Candidates")}</span><small>${A.works(C.length)}</small></div><div class="more-box" data-g="cand"></div>` : ""}
      ${Rn.length ? `<div class="rv-g" role="row"><span>${tr("最近静かになった作品", "Recently quiet")}</span><small>${A.works(Rn.length)}</small><em class="rv-gn">${tr("放送の合間で反応が少ないだけのことも多い作品です", "Often just between episodes")}</em></div><div class="more-box" data-g="recent"></div>` : ""}
    </div>
    <p class="note">${tr("静かな日は、一日を通して観測できた日だけを数えています。＊ の作品には、一部の時間しか観測できなかった日もあり、その日は数えていません。", "Quiet days count only fully observed days. ＊ marks titles with partly observed days, which are not counted.")}</p>`
      : `<div class="rv-empty"><div><b>${tr("話題が落ち着いている作品はありません", "No quiet titles right now")}</b></div></div>`}`;
  // 長い一覧は初めの数件だけを描き、残りは「もっと見る」（common.js の moreList。件数は config/pages.toml [display]。#55: 件数が増えても縦に伸び続けない）
  if (rev.length) A.moreList($("rvx-list"), rev.map(revCard), DP.cards_first, DP.cards_step);
  if (C.length) A.moreList(document.querySelector('#rv-watch .more-box[data-g="cand"]'), C.map(row), DP.rows_step, DP.rows_step);
  if (Rn.length) A.moreList(document.querySelector('#rv-watch .more-box[data-g="recent"]'), Rn.map(row), 0, Rn.length,
    rest => tr(`最近静かになった作品を表示（${rest}作品）`, `Show recently quiet titles (${rest})`));
  // 再燃した作品は今日の兆しの一部。今日の兆しの領域の中に入れる（注目は 1 つ。世界で広がると同じ）
  { const dg = $("rv-sum"), rv = $("rv-revived"); if (dg && rv) { rv.classList.add("in-digest"); dg.appendChild(rv); } }
})();
