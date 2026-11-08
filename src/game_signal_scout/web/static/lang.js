// 言語別の作品一覧（lang.html?l=<言語コード>）。ダッシュボードの地図と同じ data/day/<日>.json の dashboard.lang_obs だけから作るので、件数は必ず一致する。
// 言語は投稿の言語で、投稿者の所在地ではない。作品名は省略しない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, wn, art, ln, lcol } = A, $ = id => document.getElementById(id);
  const G = A.D.dashboard, O = G.lang_obs, day = G.day;
  const code = (() => { try { return new URLSearchParams(location.search).get("l") || ""; } catch (e) { return ""; } })();
  const l = O.langs.find(x => x.code === code), zero = (O.zero || []).find(x => x.code === code), pend = (O.incomplete || []).find(x => x.code === code),
    thin = (O.thin || []).find(x => x.code === code);
  // 前日: 画面に出す日（観測を始めた日から）の前の日は一覧にないので、日付から求める（Game）
  const prevDay = A.days.days[A.days.days.indexOf(day) - 1] || new Date(Date.parse(day + "T00:00:00Z") - 86400000).toISOString().slice(0, 10);
  if (!l) {
    $("lw").innerHTML = thin && !pend   // 観測が届いていない言語圏（観測源でこの言語の投稿がまだ少ない。人気・関心の低さではない）
      ? `<div class="sec-h"><h2>${tr(`${esc(ln(code))}で話題になった作品`, `Titles talked about in ${esc(ln(code))}`)}</h2></div>
         <p class="lw-empty">${tr(`${esc(ln(code))}は、まだ十分に観測できていない言語圏です。${esc(A.thinNote(thin).stage)}。話題になった作品がない、ゲームが遊ばれていない、という意味ではありません。`,
           `${esc(ln(code))} is not yet well observed. ${esc(A.thinNote(thin).stage)}. This does not mean no title is talked about or that the game is not played.`)}</p>
         <p class="lw-note">${esc(A.thinNote(thin).counts)}</p>`
      : pend   // 集計中（収集・集計・判定が終わっていない）: 0 作品とは書かない（ADR 0048）
      ? `<div class="sec-h"><h2>${tr(`${esc(ln(code))}で話題になった作品`, `Titles talked about in ${esc(ln(code))}`)}</h2></div>
         <p class="lw-empty">${tr(`${esc(G.label.ja)}の${esc(ln(code))}は、まだ集計が終わっていません。話題になった作品がなかったという意味ではありません。`,
           `${esc(ln(code))} for ${esc(G.label.en)} is still being tallied. This does not mean no title was talked about.`)}</p>`
      : zero
      ? `<div class="sec-h"><h2>${tr(`${esc(ln(code))}で話題になった作品`, `Titles talked about in ${esc(ln(code))}`)}</h2></div>
         <p class="lw-empty">${tr(`${esc(G.label.ja)}、${esc(ln(code))}で話題になった作品はありませんでした。見つからないことは、関心がないことではありません。`,
           `On ${esc(G.label.en)}, no title was talked about in ${esc(ln(code))}. Not finding one does not mean there is no interest.`)}</p>`
      : `<div class="sec-h"><h2>${tr("言語別の作品一覧", "Titles by language")}</h2></div><p>${tr("この日、この言語の観測はありません。", "No observations in this language on this day.")} <a href="index.html#world">${tr("言語マップへ戻る", "Back to the language map")}</a></p>`;
    return;
  }
  // 前日と比べられるか: 一日を通して観測できた日どうしで、この言語の Source がすべて前日も観測できたとき（ADR 0047 決定 4）
  const CMP = O.comparable && l.cmp !== false, wc = w => CMP && !(w.by_source && w.by_source[0].cmp === false);
  // 出典（D1: 主要な表には出さず、作品の行の開閉でだけ確かめられる）。人数は出典ごとの別の値で、足さない
  // 出典の表記は config/map_sources.toml の label（データの by_source[].label）。投稿の取得元のサービスの名前は画面に出さない（2026-10-12 のユーザーの指示）
  const src = w => w.by_source ? `<details class="lw-src"><summary>${tr("出典", "Source")}</summary><ul>${w.by_source.map(b => `<li>${esc(tr(...(b.label || ["—", "—"])))}: ${b.n}${tr("人", " people")}</li>`).join("")}</ul></details>` : "";
  const name = esc(ln(l.code)), d = l.n - l.prev, newly = l.works.filter(w => w.prev < 2).length;
  document.title = tr(`${ln(l.code)}の作品一覧`, `Titles in ${ln(l.code)}`) + " | Game Signal Scout";
  const tag = w => !wc(w) ? "" : w.prev < 2 ? `<span class="tg new">${tr("前日はなし", "New")}</span>` : w.n > w.prev ? `<span class="tg up">${tr("増えた", "Up")}</span>`
    : w.n < w.prev ? `<span class="tg down">${tr("減った", "Down")}</span>` : `<span class="tg">${tr("同じ", "Same")}</span>`;
  $("lw").innerHTML = `
    <div class="sec-h"><h2><i class="lw-sw" style="background:${lcol(l.code)}"></i>${tr(`${name}で話題になった作品`, `Titles talked about in ${name}`)}</h2><p>${tr(`${esc(G.label.ja)}。${name}の投稿で話題になった作品です。`, `${esc(G.label.en)}. Titles talked about in ${name} posts.`)}</p></div>
    <div class="lw-sum">
      <div><span>${tr("作品の数", "Titles")}</span><b>${l.n}<small>${tr("作品", "")}</small></b></div>
      <div><span>${tr(`前日（${md(prevDay)}）`, `Day before (${md(prevDay)})`)}</span><b>${CMP ? l.prev : "—"}<small>${CMP ? tr("作品", "") : ""}</small></b>${CMP ? `<em>${d === 0 ? "±0" : (d > 0 ? "＋" : "−") + Math.abs(d) + tr("作品", "")}</em>` : ""}</div>
      <div><span>${tr(`前日は${name}で話題になっていなかった作品`, `Not talked about in ${name} the day before`)}</span><b>${CMP ? newly : "—"}<small>${CMP ? tr("作品", "") : ""}</small></b></div>
    </div>
    ${CMP ? "" : `<p class="lw-note">${!O.comparable ? tr("前日は一部の時間しか観測できなかったため、前日との比較は出していません。", "The day before was only partly observed, so we do not compare with it.")
      : tr("この言語は前日と同じ条件で観測できていないため、前日との比較は出していません。", "This language was not observed under the same conditions the day before, so we do not compare with it.")}</p>`}
    <p class="lw-note">${tr("投稿言語別の観測結果です。投稿者の所在地を示すものではありません。", "Grouped by the language of the post, not where the poster lives.")}</p>
    ${l.partial ? `<p class="lw-note">${tr("この言語の観測の一部は、まだ集計が終わっていません。作品の数は少なめに出ていることがあり、前日との比較は出していません。",
      "Part of the observation for this language is still being tallied. The number of titles may be low, and we do not compare with the day before.")}</p>` : ""}
    ${A.scopeNote(l) ? `<p class="lw-note lw-scope">${tr("観測の範囲", "Observation scope")}: ${esc(A.scopeNote(l))}</p>` : ""}
    <table class="lw-t">
      <thead><tr><th></th><th>${tr("作品", "Title")}</th><th class="r">${tr(`話題にした人（${name}）`, `People (${name})`)}</th>${CMP ? `<th class="r">${tr("前日", "Day before")}</th><th>${tr("変化", "Change")}</th>` : ""}</tr></thead>
      <tbody>${l.works.map(w => `<tr>
        <td class="im"><a href="${A.workUrl(w.id)}" tabindex="-1" aria-hidden="true">${art(w)}</a></td>
        <td><a class="lw-n" href="${A.workUrl(w.id)}">${wn(w.name, 2, "b")}</a></td>
        <td class="r"><b>${w.n}</b>${tr("人", "")}${src(w)}</td>${CMP ? `<td class="r">${wc(w) ? w.prev + tr("人", "") : "—"}</td><td>${tag(w)}</td>` : ""}</tr>`).join("")}</tbody>
    </table>`;
})();
