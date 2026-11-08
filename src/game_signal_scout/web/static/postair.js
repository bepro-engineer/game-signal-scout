// 放送後も熱い作品（postair.html）。data/pages.json の post_air（事前計算）だけを使う。
// ended = 放送を終えた作品の 1 つの一覧（#26）。作品ごとの state は本番の judge_post_air の結果（hot = 判定に通った・thin = 保っているが少人数・
// faded = 落ち着いた・early = 終了から日が浅い・low_before = 終了前から話題が少なかった・no_before = 終了前の観測が足りない）。並びは build（hot が先頭）。
// 構成: この日の放送後（文章）→ 帯 → 放送を終えた作品（話題が続いている作品はカード、ほかは状態ごとの行）→ これから放送を終える作品。
// 公開する画面に判定の基準（何日・何人・何割）を書かない。基準と比べていない作品を「熱い」と呼ばない。観測が足りないことを話題が減ったと書かない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, wn, art, FMT } = A, P = A.P, X = P.post_air, $ = id => document.getElementById(id);
  const D = P.days, day = P.as_of, obs = P.observed, C = X.counts, DP = P.display;
  const ENDW = w => (w.fmt === "movie" ? tr("公開", "released") : tr("放送終了", "ended"));
  const num1 = v => v == null ? "" : (Math.round(v * 10) / 10).toString();
  const link = w => `<a class="cardlink" href="${A.workUrl(w.id)}" aria-label="${esc(nm(w.name))}"></a>`;
  const ended = X.ended, hot = ended.filter(w => w.state === "hot");
  const soon = X.soon.map(w => ({ ...w, last7: [...Array(Math.min(7, D.length)).keys()].map(k => D.length - Math.min(7, D.length) + k) })).sort((a, b) => a.end < b.end ? -1 : 1);
  const daysTo = s => Math.round((new Date(s) - new Date(day)) / 864e5);
  // 状態の名前と、比べられない作品に足りないもの（判定の理由に対応。基準の数は書かない）
  const ST = { hot: [tr("話題が続いている", "Still talked about")], thin: [tr("保っているが少人数", "Holding, but few people"), tr("終了前の水準を保っていますが、話題にした人はまだ少数です。", "Holding its level from before the end, but still only a few people.")],
    faded: [tr("話題が落ち着いた", "Settled down"), tr("終了前と比べて、話題にする人が減りました。", "Fewer people talk about it than before the end.")],
    early: [tr("終了から日が浅い", "Just ended"), tr("終了から日が浅く、まだ比べられません。", "Too soon after the end to compare.")],
    low_before: [tr("終了前から話題が少なかった", "Little talk before the end"), tr("終了前から話題にする人が少なく、終了前後を比べられません。", "Few people talked about it before the end, so before and after cannot be compared.")],
    no_before: [tr("終了前の観測が足りない", "Not observed before the end"), tr("終了前を十分に観測できておらず、比べられません。", "We did not observe enough before the end to compare.")] };

  /* ---------- この日の放送後 ---------- */
  const breakdown = ["thin", "faded", "early", "low_before", "no_before"].filter(k => C[k]).map(k => tr(`${ST[k][0]}${C[k]}作品`, `${ST[k][0].toLowerCase()} ${C[k]}`)).join(tr("・", ", "));
  $("pa-sum").innerHTML = `<div class="g-kick"><b>${tr("今日の兆し", "Today's signal")}</b><span class="g-day">${tr("この日の放送後", "After the finale")}・${esc(P.label[A.lang])}</span></div>
    <p class="dg-t">${hot.length ? tr(`${md(day)}の時点で、放送を終えたあとも話題が続いている作品は${hot.length}作品です。先頭の<b class="nb">『${esc(nm(hot[0].name))}』</b>は、終了前の1日${num1(hot[0].ev.baseline)}人に対して、終了後も1日${num1(hot[0].ev.after_median)}人が話題にしています。`,
        `As of ${md(day)}, ${hot.length} title(s) are still talked about after their run ended. <b>${esc(nm(hot[0].name))}</b> drew ${num1(hot[0].ev.baseline)} a day before the end and ${num1(hot[0].ev.after_median)} a day since.`)
      : ended.length ? tr(`${md(day)}の時点で、放送を終えたあとも話題が続いている作品はありません。`, `As of ${md(day)}, no title is still talked about after its run ended.`) : tr(`${md(day)}の時点で、最近放送を終えた作品はありません。`, `As of ${md(day)}, no title ended recently.`)}
    ${breakdown ? tr(`最近放送を終えた${ended.length}作品の内訳は、${breakdown}です。`, ` Of ${ended.length} recently ended titles: ${breakdown}.`) : ""}
    ${soon.length ? tr(`次に放送を終えるのは、${md(soon[0].end)}の<b class="nb">『${esc(nm(soon[0].name))}』</b>です。`, ` Next to end is <b>${esc(nm(soon[0].name))}</b> on ${md(soon[0].end)}.`) : ""}</p>`;

  /* ---------- 帯 ---------- */
  $("pa-bar").innerHTML = `<span class="all">${tr(`${md(day)}の放送後`, `After the finale · ${md(day)}`)}</span>
    <a href="#pa-ended">${tr("話題が続いている作品", "Still talked about")} <b>${hot.length}</b></a><a href="#pa-ended">${tr("放送を終えた作品", "Recently ended")} <b>${ended.length}</b></a><a href="#pa-soon">${tr("これから放送を終える作品", "Ending soon")} <b>${soon.length}</b></a>`;

  /* ---------- 放送を終えた作品（1 つの一覧）: 話題が続いている作品はカード（4 つの段階と日ごとの人数）、ほかは状態ごとの行 ---------- */
  const wari = r => r >= 1.15 ? tr("放送終了前より多い", "more than before the end") : r >= 0.95 ? tr("放送終了前と同じくらい", "about the same as before the end") : tr(`放送終了前の${Math.floor(r * 10)}割`, `${Math.round(r * 100)}% of before the end`);
  const hotCard = w => { const e = w.ev, mx = Math.max(1, ...w.series);
    return `<article class="rvx">${link(w)}${art(w)}
      <div class="rvx-t">${wn(w.name, 2, "h3")}<span class="rv-air">${esc(FMT[w.fmt] || "")}</span>${A.srcNote(w)}
        <ol class="rvx-steps">
          <li class="b"><span>${tr("放送終了前", "Before the end")}</span><span class="v">${tr(`ふだん1日 <b>${num1(e.baseline)}人</b>`, `usually <b>${num1(e.baseline)}</b>/day`)}</span></li>
          <li class="e"><span>${tr("放送終了", "Final day")}</span><span class="v"><b>${md(e.end)}</b></span></li>
          <li class="a"><span>${tr("その後", "After")}</span><span class="v">${tr(`1日 <b>${num1(e.after_median)}人</b>`, `<b>${num1(e.after_median)}</b>/day`)}<small>${wari(e.ratio)}</small></span></li>
          <li class="n"><span>${tr("いま", "Now")}</span><span class="v"><em class="st ${e.status === "continuing" ? "on" : "off"}">${e.status === "continuing" ? tr(`話題が続いている（${e.cont_days}日）`, `Still going (${e.cont_days} days)`) : tr("続いたが落ち着いてきた", "Held up, now settling")}</em></span></li>
        </ol></div>
      <div class="rvx-g"><div class="wk-ch" style="--n:${D.length}">${w.series.map((n, i) => `<div class="c${obs[i] === "p" ? " pt" : ""}${D[i] === e.end ? " ev" : ""}"><span class="tag">${D[i] === e.end ? tr("終了", "End") : ""}</span><span class="bar"><i style="height:${n / mx * 100}%"></i></span><b>${n}</b><small>${i === 0 || i === D.length - 1 || D[i] === e.end || i % 7 === 0 ? md(D[i]) : "&nbsp;"}</small></div>`).join("")}</div></div></article>`; };   // 日付は最初・終了・最後・7 日ごと（並べると重なる）
  // 行: 終了日 → 終了前と終了後の 1 日の人数（分かる分だけ）と、比べられない理由
  const endCell = w => `<span>${tr(`<b>${md(w.end)}</b>に${ENDW(w)}`, `${w.fmt === "movie" ? "Released" : "Ended"} <b>${md(w.end)}</b>`)}</span><span class="pa-d">${tr(`${w.ev.days_since_end}日前`, `${w.ev.days_since_end} days ago`)}</span>`;
  const nums = w => { const e = w.ev, b = e.baseline != null ? tr(`終了前 1日<b class="pa-n">${num1(e.baseline)}人</b>`, `Before: <b class="pa-n">${num1(e.baseline)}</b>/day`) : "";
    const a = e.after_median != null ? tr(`終了後 1日<b class="pa-n now">${num1(e.after_median)}人</b>`, `After: <b class="pa-n now">${num1(e.after_median)}</b>/day`) : tr("終了後の観測はこれから", "Too early after the end");
    return `<span class="pa-d">${[b, a].filter(Boolean).join(" → ")}</span>`; };
  const row = w => `<div class="rv-r" role="row">${link(w)}${art(w)}
    <div class="rv-n" role="cell">${wn(w.name, 2, "h3")}<span class="rv-air">${esc(FMT[w.fmt] || "")}</span>${A.srcNote(w)}</div>
    <div class="rv-last" role="cell">${endCell(w)}</div><span class="ar" aria-hidden="true">→</span><div class="rv-q pa-q" role="cell">${nums(w)}</div></div>`;
  const groups = ["thin", "faded", "early", "low_before", "no_before"].filter(k => C[k]);
  $("pa-ended").innerHTML = `<div class="sec-h"><h2>${tr("放送を終えた作品", "Recently ended titles")}<small class="cnt">${A.works(ended.length)}</small></h2><p>${tr("放送が終わったあとも話題が続いているかを、作品ごとに終わる前と比べています。話題が続いている作品が先頭です。比べられない作品は、その理由を書いています。",
      "Whether each title is still talked about after its end, compared with before it. Titles still talked about come first; for others we note why they cannot be compared.")}</p></div>
    ${hot.length ? `<div class="rvx-list" id="pa-hot"></div>` : ended.length ? `<p class="pa-none">${tr("いまは、放送を終えたあとも話題が続いている作品はありません。", "No recently ended title is still talked about right now.")}</p>` : ""}
    ${groups.length ? `<div class="rv-t pa-t" role="table">
      <div class="rv-h" role="row"><span>${tr("作品", "Title")}</span><span>${tr("放送終了", "End")}</span><span></span><span>${tr("終了前と終了後", "Before and after")}</span></div>
      ${groups.map(k => `<div class="rv-g" role="row"><span>${esc(ST[k][0])}</span><small>${A.works(C[k])}</small></div><p class="pa-gnote">${esc(ST[k][1])}</p><div class="more-box" data-g="${k}"></div>`).join("")}
    </div>` : ""}
    ${ended.length ? "" : `<div class="rv-empty"><div><b>${tr("最近放送を終えた作品はありません", "No title ended recently")}</b></div></div>`}`;
  if (hot.length) A.moreList(document.getElementById("pa-hot"), hot.map(hotCard), DP.cards_first, DP.cards_step);   // 長い一覧は初めの数件（#55）
  groups.forEach(k => A.moreList(document.querySelector(`#pa-ended .more-box[data-g="${k}"]`), ended.filter(w => w.state === k).map(row), DP.rows_first, DP.rows_step));

  /* ---------- これから放送を終える作品 ---------- */
  const lastCell = w => { const v = w.last7.map(i => w.series[i]); return `<span class="pa-d">${tr("この1週間", "Past week")}</span><b class="pa-n">${tr(`1日 ${Math.min(...v)}〜${Math.max(...v)}人`, `${Math.min(...v)}–${Math.max(...v)}/day`)}</b>`; };
  const soonRow = w => `<div class="rv-r" role="row">${link(w)}${art(w)}
        <div class="rv-n" role="cell">${wn(w.name, 2, "h3")}<span class="rv-air">${esc(FMT[w.fmt] || "")}${tr("・放送中", " · Airing")}</span></div>
        <div class="rv-last" role="cell"><span>${tr(`<b>${md(w.end)}</b>に放送終了予定`, `Ends <b>${md(w.end)}</b>`)}</span><span class="pa-d">${tr(`あと${daysTo(w.end)}日`, `in ${daysTo(w.end)} days`)}</span></div><span class="ar" aria-hidden="true">→</span>
        <div class="rv-q pa-q" role="cell">${lastCell(w)}</div></div>`;
  $("pa-soon").innerHTML = `<div class="sec-h"><h2>${tr("これから放送を終える作品", "Ending soon")}<small class="cnt">${A.works(soon.length)}</small></h2><p>${tr("放送が終わる前から反応を観測している作品です。放送が終わると、終わる前と後を比べられるようになります。", "Titles we have observed since before their end. Once they end, before and after can be compared.")}</p></div>
    ${soon.length ? `<div class="rv-t pa-t ls-t" role="table">
      <div class="rv-h" role="row"><span>${tr("作品", "Title")}</span><span>${tr("放送終了の予定", "Scheduled end")}</span><span></span><span>${tr("いまの反応", "Now")}</span></div>
      <div class="more-box" id="pa-soon-rows"></div>
    </div>` : `<div class="rv-empty"><div><b>${tr("近く放送を終える作品はありません", "No title is ending soon")}</b></div></div>`}`;
  if (soon.length) A.moreList(document.getElementById("pa-soon-rows"), soon.map(soonRow), DP.rows_first, DP.rows_step);   // #55
})();
