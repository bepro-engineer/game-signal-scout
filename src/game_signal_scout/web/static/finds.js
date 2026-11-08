// プレイヤーの発見（#2）: 世界のプレイヤーが実際に遊んで「何をして、何が起きたか」。作品ごとに、複数の人が書いた体験（発見）と、
// まだほかの人と重ならない「ひとりの体験」をそう明記して出す。人数は確からしさの目安で、面白さの保証ではない。反対の声も添える。
// 観点（ひとりで・協力・対戦・コントローラー・日本語・面白い／不満・いま変わったこと）は固定の分類ではなく、組み合わせて絞れる条件（#2 6723386003）。
// 数は集計（services/insight）が数えたもの。原文は出さない（要約と数だけ）。
(() => {
  const A = window.ASS, { tr, esc, art, wn, num, ln, lcol } = A, P = A.P, ALL = (P.finds || {}).items || [];
  const Q = (() => { try { return new URLSearchParams(location.search); } catch (e) { return new URLSearchParams(""); } })();
  const st = { f: Q.get("f") || "", v: Q.get("v") || "", jp: Q.get("jp") || "", view: Q.get("view") || "" };
  const $ = id => document.getElementById(id);
  const VERDICT = { fun: ["面白い", "Fun"], frustration: ["不満", "Frustrating"], mixed: ["賛否", "Mixed"] };
  const CAUTION = { time: ["時間がかかる", "Time-consuming"], price: ["価格・課金", "Price / monetization"], performance: ["動作が重い", "Performance"],
    bugs: ["不具合", "Bugs"], difficulty: ["難しさ", "Difficulty"], online: ["接続・対戦相手", "Online issues"] };
  const TREND = { new: ["今週はじめて", "New this week"], up: ["増えている", "Growing"], same: ["続いている", "Ongoing"], down: ["減っている", "Fading"] };
  const ppl = n => tr(`${num(n)}人`, `${num(n)} ${n === 1 ? "player" : "players"}`);
  const jpOk = w => ["ui", "sub", "voice"].includes(A.jpLevel(w));
  // 条件に合う体験か（観点・面白い／不満・いま変わったこと）。作品の条件（日本語）は作品で見る
  const hit = (f, single) => A.facetHit(f, st.f) && (!st.v || f.verdict === st.v) && (st.view !== "changed" || (!single && (f.trend === "new" || f.trend === "up")));
  const wOk = w => !st.jp || jpOk(w);
  const view = w => ({ ...w, F: w.finds.filter(f => hit(f)), S: w.singles.filter(e => hit(e, true)) });
  const F = ALL.filter(wOk).map(view).filter(w => w.F.length || w.S.length)
    .sort((a, b) => (b.F.length ? b.F[0].people : 1) - (a.F.length ? a.F[0].people : 1) || b.F.length - a.F.length);
  // 条件を変える札（件数つき。0 件の観点も消さずに「まだなし」と出す）
  const count = patch => { const s0 = { ...st }; Object.assign(st, patch); const n = ALL.filter(wOk).map(view).reduce((t, w) => t + w.F.length + w.S.length, 0); Object.assign(st, s0); return n; };
  const url = patch => { const s = { ...st, ...patch }, u = new URLSearchParams(); Object.entries(s).forEach(([k, v]) => v && u.set(k, v)); const q = u.toString(); return `finds.html${q ? `?${q}` : ""}`; };
  const chip = (key, val, label) => { const on = st[key] === val, n = on ? null : count({ [key]: val });
    return `<a href="${url({ [key]: on ? "" : val })}" class="${on ? "on" : n === 0 ? "zero" : ""}"${on ? ' aria-current="true"' : ""}>${esc(label)}${on ? " ×" : n === 0 ? tr("（まだなし）", " (none yet)") : `<small>${num(n)}</small>`}</a>`; };
  const bar = `<div class="fd-bar">
      <div class="fd-row"><span class="fd-k">${tr("遊び方", "How they played")}</span>${A.FACETS.map(([k, ja, en]) => chip("f", k, tr(ja, en))).join("")}</div>
      <div class="fd-row"><span class="fd-k">${tr("感じたこと", "Verdict")}</span>${chip("v", "fun", tr("面白かった", "Fun"))}${chip("v", "frustration", tr("不満だった", "Frustrating"))}
        <span class="fd-k">${tr("作品", "Title")}</span>${chip("jp", "any", tr("日本語で遊べる", "Playable in Japanese"))}${chip("view", "changed", tr("いま変わったこと", "What changed"))}</div></div>`;
  const facetOf = f => A.FACETS.filter(x => x[5](f)).map(x => `<span class="fd-fc">${esc(tr(x[1], x[2]))}</span>`).join("");
  const langs = f => f.langs.slice(0, 4).map(l => `<span class="fd-lg"><i style="background:${lcol(l)}"></i>${esc(ln(l))}</span>`).join("") +
    (f.langs.length > 4 ? `<span class="fd-lg more">${tr(`ほか${f.langs.length - 4}`, `+${f.langs.length - 4}`)}</span>` : "");
  // 反対の声（面白い ↔ 不満）と、少数の声であること（確からしさ）
  const against = f => { const n = f.verdict === "fun" ? f.frustration : f.verdict === "frustration" ? f.fun : 0;
    return n ? `<span class="fd-ag">${tr(`反対の声 ${ppl(n)}`, `${ppl(n)} disagreed`)}</span>` : ""; };
  const find = f => `<li class="fd-f fd-${esc(f.verdict)}">
      <p class="fd-h"><span class="fd-v">${esc(tr(...VERDICT[f.verdict]))}</span>${f.caution ? `<span class="fd-c">${tr("注意: ", "Note: ")}${esc(tr(...CAUTION[f.caution]))}</span>` : ""}${facetOf(f)}<b>${esc(f.title)}</b></p>
      ${f.fits ? `<p class="fd-fit">${tr("向いている人: ", "Suits: ")}${esc(f.fits)}</p>` : ""}
      <p class="fd-n"><span class="fd-p">${tr(`${ppl(f.people)}が同じ体験を書いています`, `${ppl(f.people)} wrote the same`)}</span>
        ${f.people < 3 ? `<span class="fd-few">${tr("まだ少数の声", "Still only a few")}</span>` : ""}${against(f)}
        <span class="fd-t fd-t-${esc(f.trend)}">${esc(tr(...TREND[f.trend]))}${f.trend !== "new" ? tr(`（前の週 ${num(f.prev)}人）`, ` (prev. week ${num(f.prev)})`) : ""}</span></p>
      <p class="fd-l">${langs(f)}</p>
      ${f.examples && f.examples.length ? `<ul class="fd-ex">${f.examples.map(e => `<li>${esc(e.did)} <span aria-hidden="true">→</span> ${esc(e.happened)}</li>`).join("")}</ul>` : ""}
    </li>`;
  const single = e => `<li class="fd-s fd-${esc(e.verdict)}"><span class="fd-v">${esc(tr(...VERDICT[e.verdict]))}</span>${e.caution ? `<span class="fd-c">${tr("注意: ", "Note: ")}${esc(tr(...CAUTION[e.caution]))}</span>` : ""}${facetOf(e)}
      ${esc(e.did)} <span aria-hidden="true">→</span> ${esc(e.happened)}${e.lang ? ` <span class="fd-lg"><i style="background:${lcol(e.lang)}"></i>${esc(ln(e.lang))}</span>` : ""}</li>`;
  const card = w => `<article class="fd-w"><a class="fd-a" href="${A.workUrl(w.id)}">${art(w)}</a>
      <div class="fd-b"><h3><a href="${A.workUrl(w.id)}">${wn(w.name, 2, "span")}</a></h3>
        <p class="fd-meta">${A.jpTag(w)} ${A.devLine(w)}</p>
        ${w.F.length ? `<ol class="fd-fs">${w.F.map(find).join("")}</ol>` : ""}
        ${w.S.length ? `<div class="fd-one"><p class="fd-one-h">${tr("ひとりの体験（まだほかの人の声と重なっていません）", "Single players' experiences (not yet echoed by others)")}</p><ul>${w.S.map(single).join("")}</ul></div>` : ""}
        <p class="fd-src">${tr(`${esc(w.since)}からの 7 日に、この作品について書いた ${num(w.read_people || 0)}人の発言を AI が読み、具体的な体験を書いた ${num(w.experiences || 0)}件を取り出しました。`,
          `AI read posts by ${num(w.read_people || 0)} players over 7 days from ${esc(w.since)} and found ${num(w.experiences || 0)} concrete experiences.`)}
          <a href="${A.workUrl(w.id)}">${tr("作品の詳細で、日本語・機種・注意を確かめる →", "Check language, platforms and cautions →")}</a></p></div></article>`;
  $("fd-note").innerHTML = bar + `<p>${tr("「発見」は、別々のプレイヤーが同じ具体的な体験を書いたものです。人数は確からしさの目安で、多いほど面白いという意味ではありません。ひとりだけの体験も、そう書いて載せています。AI は発言を読んでまとめるだけで、数はこちらで数えています。原文は載せていません。",
    "A discovery is the same concrete experience written by different players. The count is a hint of how reliable it is, not of how fun it is. Single players' experiences are labeled as such. AI only reads and groups; counting is done separately. Original posts are not shown.")}</p>`;
  // 0 件のとき: 理由（どの段で 0 になったか）と、ほかに体験のある観点への道を出す
  const why = () => { const t = ALL.reduce((a, w) => { const s = w.stages || {}; a.st += s.statements_recent || 0; a.ex += s.experiences_recent || 0; return a; }, { st: 0, ex: 0 });
    const alt = A.FACETS.map(([k, ja, en]) => [k, tr(ja, en), count({ f: k, v: "", jp: "", view: "" })]).filter(x => x[2] > 0);
    return `<div class="rv-empty"><div><b>${tr("この条件に当てはまる体験は、まだありません", "No experiences match these conditions yet")}</b>
      <p>${ALL.length ? tr(`読んだ ${num(ALL.length)}作品の直近の発言 ${num(t.st)}件のうち、具体的な体験が書かれていたのは ${num(t.ex)}件でした。この条件に当てはまる体験はその中にありませんでした。条件を外すか、ほかの遊び方を見てください。`,
        `Of ${num(t.st)} recent posts on ${num(ALL.length)} titles, ${num(t.ex)} described a concrete experience; none match these conditions.`) : tr("まだ発言を読んだ作品がありません。", "No titles have been read yet.")}</p>
      ${alt.length ? `<p class="fd-alt">${alt.map(([k, l, n]) => `<a href="finds.html?f=${k}">${esc(l)}（${num(n)}）</a>`).join("")}</p>` : ""}</div></div>`; };
  $("fd-list").innerHTML = F.length ? F.map(card).join("") : why();
})();
