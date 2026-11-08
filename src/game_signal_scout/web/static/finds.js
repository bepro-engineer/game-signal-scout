// プレイヤーの発見（#2。「世界で広がる作品」の置き換え）: 作品ごとに、世界のプレイヤーが実際に遊んで「何をして、何が起きたか」と、
// 同じことを書いた独立した投稿者の数・前の週との比較。数は集計（services/insight）が数えたもの。原文は出さない（要約と数だけ）。
(() => {
  const A = window.ASS, { tr, esc, nm, art, wn, num, ln, lcol } = A, P = A.P, ALL = (P.finds || {}).items || [];
  // 遊ぶ目的で絞る（トップの入口から ?intent=）: その目的に当てはまる面白い・賛否の体験を書いた人の多い作品から。注意（不満）は一緒に出す
  const INTENT = (() => { try { return new URLSearchParams(location.search).get("intent") || ""; } catch (e) { return ""; } })();
  const IT = A.INTENTS.find(x => x[0] === INTENT);
  const fits = w => w.finds.filter(f => f.intent === INTENT && f.verdict !== "frustration");
  // いま変わったこと（#2: 「再燃」の置き換え）: 前の週になかった・増えた体験だけ。なぜ遊ぶ意味が変わったかを、体験と人数で示す
  const VIEW = (() => { try { return new URLSearchParams(location.search).get("view") || ""; } catch (e) { return ""; } })();
  const changed = w => w.finds.filter(f => f.trend === "new" || f.trend === "up");
  const F = VIEW === "changed" ? ALL.filter(w => changed(w).length).map(w => ({ ...w, finds: changed(w) })).sort((a, b) => b.finds[0].people - a.finds[0].people)
    : IT ? ALL.filter(w => fits(w).length).sort((a, b) => fits(b)[0].people - fits(a)[0].people)
    .map(w => ({ ...w, finds: [...fits(w), ...w.finds.filter(f => !fits(w).includes(f) && (f.verdict === "frustration" || f.caution))] })) : ALL;
  const CAUTION = { time: ["時間がかかる", "Time-consuming"], price: ["価格・課金", "Price / monetization"], performance: ["動作が重い", "Performance"],
    bugs: ["不具合", "Bugs"], difficulty: ["難しさ", "Difficulty"], online: ["接続・対戦相手", "Online issues"] };
  const $ = id => document.getElementById(id);
  const VERDICT = { fun: ["面白い", "Fun"], frustration: ["不満", "Frustrating"], mixed: ["賛否", "Mixed"] };
  const TREND = { new: ["今週はじめて", "New this week"], up: ["増えている", "Growing"], same: ["続いている", "Ongoing"], down: ["減っている", "Fading"] };
  const ppl = n => tr(`${num(n)}人`, `${num(n)} ${n === 1 ? "player" : "players"}`);
  const langs = f => f.langs.slice(0, 4).map(l => `<span class="fd-lg"><i style="background:${lcol(l)}"></i>${esc(ln(l))}</span>`).join("") +
    (f.langs.length > 4 ? `<span class="fd-lg more">${tr(`ほか${f.langs.length - 4}`, `+${f.langs.length - 4}`)}</span>` : "");
  const find = (f, w) => `<li class="fd-f fd-${esc(f.verdict)}">
      <p class="fd-h"><span class="fd-v">${esc(tr(...VERDICT[f.verdict]))}</span>${f.caution ? `<span class="fd-c">${tr("注意: ", "Note: ")}${esc(tr(...CAUTION[f.caution]))}</span>` : ""}<b>${esc(f.title)}</b></p>
      <p class="fd-n"><span class="fd-p">${tr(`${ppl(f.people)}が同じことを書いています`, `${ppl(f.people)} wrote the same`)}</span>
        <span class="fd-t fd-t-${esc(f.trend)}">${esc(tr(...TREND[f.trend]))}${f.trend !== "new" ? tr(`（前の週 ${num(f.prev)}人）`, ` (prev. week ${num(f.prev)})`) : ""}</span>
        ${f.verdict === "mixed" ? `<span class="fd-mix">${tr(`面白い ${num(f.fun)}・不満 ${num(f.frustration)}・どちらも ${num(f.mixed)}`, `fun ${num(f.fun)} · frustrating ${num(f.frustration)} · both ${num(f.mixed)}`)}</span>` : ""}</p>
      <p class="fd-l">${langs(f)}</p>
      ${f.examples && f.examples.length ? `<ul class="fd-ex">${f.examples.map(e => `<li>${esc(e.did)} <span aria-hidden="true">→</span> ${esc(e.happened)}</li>`).join("")}</ul>` : ""}
    </li>`;
  const card = w => `<article class="fd-w"><a class="fd-a" href="${A.workUrl(w.id)}">${art(w)}</a>
      <div class="fd-b"><h3><a href="${A.workUrl(w.id)}">${wn(w.name, 2, "span")}</a></h3>
        <p class="fd-meta">${A.jpTag(w)} ${A.devLine(w)}</p>
        <ol class="fd-fs">${w.finds.map(f => find(f, w)).join("")}</ol>
        <p class="fd-src">${tr(`${esc(w.since)}からの 7 日に、この作品について書いた ${num(w.read_people || 0)}人の発言を AI が読み、具体的な体験を書いた ${num(w.experiences || 0)}件をまとめました。`,
          `AI read posts by ${num(w.read_people || 0)} players over 7 days from ${esc(w.since)} and grouped ${num(w.experiences || 0)} concrete experiences.`)}</p></div></article>`;
  const tabs = `<nav class="fd-tabs">${[["", "すべて", "All"], ...A.INTENTS].map(([k, ja, en]) => `<a href="finds.html${k ? `?intent=${k}` : ""}"${k === INTENT && VIEW !== "changed" ? ' class="on" aria-current="page"' : ""}>${tr(ja, en)}</a>`).join("")}
    <a href="finds.html?view=changed"${VIEW === "changed" ? ' class="on" aria-current="page"' : ""}>${tr("いま変わったこと", "What changed")}</a></nav>`;
  $("fd-note").innerHTML = tabs + `<p>${tr("人数は、同じ具体的な体験を書いた別々の人の数です（同じ人の複数の投稿は 1 人）。AI は発言を読んでまとめるだけで、数は数えていません。発言の原文は載せていません。",
    "Counts are distinct players who wrote the same concrete experience (several posts by one player count once). AI only reads and groups; counting is done separately. Original posts are not shown.")}</p>`;
  $("fd-list").innerHTML = F.length ? F.map(card).join("")
    : `<div class="rv-empty"><div><b>${IT ? tr(`「${IT[1]}」に当てはまる発見はまだありません`, `No discoveries for “${IT[2]}” yet`) : tr("まだ発見はありません", "No discoveries yet")}</b><p>${tr("同じ体験を 3 人以上のプレイヤーが書いた作品だけを出します。根拠のない作品は並べません。", "We only list titles where 3 or more players wrote about the same experience.")}</p></div></div>`;
})();
