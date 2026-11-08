// プレイヤーの発見（#2。「世界で広がる作品」の置き換え）: 作品ごとに、世界のプレイヤーが実際に遊んで「何をして、何が起きたか」と、
// 同じことを書いた独立した投稿者の数・前の週との比較。数は集計（services/insight）が数えたもの。原文は出さない（要約と数だけ）。
(() => {
  const A = window.ASS, { tr, esc, nm, art, wn, num, ln, lcol } = A, P = A.P, F = (P.finds || {}).items || [];
  const $ = id => document.getElementById(id);
  const VERDICT = { fun: ["面白い", "Fun"], frustration: ["不満", "Frustrating"], mixed: ["賛否", "Mixed"] };
  const TREND = { new: ["今週はじめて", "New this week"], up: ["増えている", "Growing"], same: ["続いている", "Ongoing"], down: ["減っている", "Fading"] };
  const ppl = n => tr(`${num(n)}人`, `${num(n)} ${n === 1 ? "player" : "players"}`);
  const langs = f => f.langs.slice(0, 4).map(l => `<span class="fd-lg"><i style="background:${lcol(l)}"></i>${esc(ln(l))}</span>`).join("") +
    (f.langs.length > 4 ? `<span class="fd-lg more">${tr(`ほか${f.langs.length - 4}`, `+${f.langs.length - 4}`)}</span>` : "");
  const find = (f, w) => `<li class="fd-f fd-${esc(f.verdict)}">
      <p class="fd-h"><span class="fd-v">${esc(tr(...VERDICT[f.verdict]))}</span><b>${esc(f.title)}</b></p>
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
  $("fd-note").innerHTML = `<p>${tr("人数は、同じ具体的な体験を書いた別々の人の数です（同じ人の複数の投稿は 1 人）。AI は発言を読んでまとめるだけで、数は数えていません。発言の原文は載せていません。",
    "Counts are distinct players who wrote the same concrete experience (several posts by one player count once). AI only reads and groups; counting is done separately. Original posts are not shown.")}</p>`;
  $("fd-list").innerHTML = F.length ? F.map(card).join("")
    : `<div class="rv-empty"><div><b>${tr("まだ発見はありません", "No discoveries yet")}</b><p>${tr("同じ体験を 3 人以上が書いた作品が見つかると、ここに出ます。", "Titles appear here when 3 or more players write about the same experience.")}</p></div></div>`;
})();
