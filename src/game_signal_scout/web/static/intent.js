// 遊びたい体験の入口（#2 2026-11-11 オーナー確定）: じっくり没頭したい（deep）・短時間で楽しみたい（short）・新しい体験がしたい（novel）・友達と遊びたい（friends）。
// 作品はプレイヤーの体験の読み取り（services/intents）で選んだもの。ジャンルやストアの表示で決めていない。カードは
// 「この体験に合う根拠（実際に遊んだ人の体験と人数）→ 何をして何が起きたか → 向いている人 → 合わないかもしれない点（不満の体験・注意の人数）」。
// 並びは注目の作品と同じく日本語で遊べる作品を先、その中は根拠の体験を書いた人の多い順。根拠のない入口は、そう書いて作品で埋めない。
(() => {
  const A = window.ASS, { tr, esc, num, nm, tx } = A, I = (A.P || {}).intents || {};
  const $ = id => document.getElementById(id);
  const PAGE = document.documentElement.dataset.page;
  const META = {
    deep: { why: ["探索・物語・育成ややり込みを、プレイヤーが面白さとして書いた作品です。", "Titles where players wrote that exploring, the story, or building and growing was the fun."] },
    short: { why: ["1 回が短くても満足できたと、プレイヤーが書いた作品です。", "Titles where players wrote that short sessions were satisfying."] },
    novel: { why: ["予想外の展開や意外な遊び方を、プレイヤーが面白さとして書いた作品です。", "Titles where players wrote that surprises or unexpected ways to play were the fun."] },
    friends: { why: ["仲間との連携や相手との駆け引き、協力・対戦で遊んだ体験を、プレイヤーが書いた作品です。", "Titles where players wrote about teamwork, outplaying others, or playing co-op or versus."] },
  };
  const NAMES = Object.fromEntries((A.INTENTS || []).map(([k, ja, en]) => [k, [ja, en]]));
  const CJ = { time: ["時間がかかる", "Takes time"], price: ["価格・課金", "Price"], performance: ["動作が重い", "Performance"], bugs: ["不具合", "Bugs"], difficulty: ["難しい", "Difficult"], online: ["接続・対戦相手", "Online"] };
  const HOW = [["オンラインで協力", "Online co-op"], ["同じ画面で協力", "Same-screen co-op"], ["LANで協力", "LAN co-op"], ["オンラインで対戦", "Online versus"], ["同じ画面で対戦", "Same-screen versus"], ["LANで対戦", "LAN versus"]];
  const lv = w => !w.jp ? "unknown" : w.jp.voice ? "voice" : w.jp.sub ? "sub" : w.jp.ui ? "ui" : "none";
  const JPL = { voice: ["日本語音声", "Japanese audio"], sub: ["日本語字幕", "Japanese subtitles"], ui: ["日本語UI", "Japanese UI"], none: ["日本語非対応", "No Japanese"], unknown: ["日本語未確認", "Japanese unknown"] };
  const jp = k => `<span class="fj fj-${k}">${esc(tr(...JPL[k]))}</span>`;
  const playable = w => ["voice", "sub", "ui"].includes(lv(w)) ? 0 : 1;
  const pp = n => n > 1 ? tr(`${num(n)}人`, `${num(n)} players`) : tr("1人", "1 player");
  // 英語の画面: 訳のない文は日本語のまま出す（注目の作品と同じ）。向いている人は訳があるときだけ
  const line = x => `${esc(tx(x, "act"))} → ${esc(tx(x, "result"))}`;
  const img = w => (w.shots || [])[0] || w.banner || w.header || w.cover || "";

  // 入口の切り替え（4 つの入口。作品の数つき）
  const tabs = `<nav class="it-tabs" aria-label="${tr("遊びたい体験", "What you want to play")}">${["deep", "short", "novel", "friends"].map(k => `<a href="${k}.html"${k === PAGE ? ' class="on" aria-current="page"' : ""}><span>${esc(tr(...(NAMES[k] || [k, k])))}</span><small>${tr(`${num(((I[k] || {}).items || []).length)}作品`, `${num(((I[k] || {}).items || []).length)} titles`)}</small></a>`).join("")}</nav>`;
  const items = [...(((I[PAGE] || {}).items) || [])].sort((a, b) => playable(a) - playable(b) || b.why_people - a.why_people);
  const basis = I.basis || {};

  const card = w => {
    const top = w.why[0] || {}, rest = w.why.slice(1);
    const fits = L => (A.lang === "en" ? w.fits_en : w.fits) || "";
    const how = PAGE === "friends" ? HOW.filter(([ja]) => (w.modes || []).includes(ja)) : [];
    const cs = Object.entries(w.cautions || {}).filter(([k]) => CJ[k]);
    return `<a class="fc it-c" href="${A.workUrl(w.id)}"><img class="fc-i" src="${esc(img(w))}" alt="" referrerpolicy="no-referrer" loading="lazy">
      <div><span class="fc-t">${w.cover ? `<img src="${esc(w.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}${esc(nm(w.name))}</span>
        <span class="it-h">${tr("この体験に合う根拠", "Why it fits")}</span>
        ${top.appeal ? `<b>${esc(tx(top, "appeal"))}</b>` : ""}
        <span class="fc-e">${line(top)}<small class="it-p">${pp(top.people)}</small></span>
        ${rest.length ? `<ul class="fc-r">${rest.map(r => `<li>${esc(r.appeal ? tx(r, "appeal") : `${tx(r, "act")} → ${tx(r, "result")}`)}<small>${pp(r.people)}</small></li>`).join("")}</ul>` : ""}
        ${fits() ? `<span class="it-f"><em>${tr("向いている人", "Suits")}</em>${esc(fits())}</span>` : ""}
        ${how.length ? `<span class="it-how"><em>${tr("ストアの表示", "Store listing")}</em>${how.map(([ja, en]) => `<span class="hw">${esc(tr(ja, en))}</span>`).join("")}</span>` : ""}
        ${w.warn.length || cs.length || (PAGE === "short" && w.long) ? `<div class="fc-n"><span>${tr("合わないかもしれない点", "Might not suit you if")}</span><ul>
          ${w.warn.slice(0, 1).map(r => `<li>${r.caution && CJ[r.caution] ? `<em>${esc(tr(...CJ[r.caution]))}</em>` : ""}${line(r)}<small>${pp(r.people)}</small></li>`).join("")}
          ${PAGE === "short" && w.long ? `<li><em>${tr("時間", "Time")}</em>${tr(`1 回に時間がかかる・長いと書いた人もいます`, "Some players wrote that sessions run long")}<small>${pp(w.long)}</small></li>` : ""}
          ${cs.length ? `<li class="it-cs">${tr("注意の声", "Cautions")}: ${cs.map(([k, n]) => `${esc(tr(...CJ[k]))} ${pp(n)}`).join(tr("・", ", "))}</li>` : ""}</ul></div>` : ""}
        <small><span>${tr(`この体験を書いた人 ${num(w.why_people)}人`, `${num(w.why_people)} players wrote about this`)}</span>${jp(lv(w))}${A.priceTag(w)}</small></div></a>`;
  };

  const intro = `<p class="it-why">${esc(tr(...META[PAGE].why))}${tr(" 選んだ根拠は、実際に遊んだ人の体験だけです（ジャンルやストアの分類では選んでいません）。", " Picked only from what players actually experienced, not from genres or store categories.")}</p>`;
  let body;
  if (items.length) {
    body = `<div class="fcs" data-n="${items.length}" style="--n:${Math.min(3, items.length)}">${items.map(card).join("")}</div>`;
  } else if (PAGE === "short") {
    // 根拠不足（#2 2026-11-11: 偽らない）: 1 回に遊ぶ時間は 2026-11-11 から読み取りを始めた。それまでの読み取りにはない
    const lg = (I.short || {}).long || [];
    body = `<div class="rv-empty it-empty"><div><b>${tr("まだ、短時間で楽しめたと書いた体験が見つかっていません", "No player has yet written that short sessions were satisfying")}</b>
        <p>${tr(`1 回に遊ぶ時間（短い・長い）は、${esc(basis.session_since || "")} から発言の読み取りで取り出し始めました。それまでに読んだ発言にはこの項目がないため、根拠のある作品はまだありません。ジャンルやストアの表示から「短時間向き」と推測して並べることはしていません。新しい発言を読むたびに増えます。`,
          `We started extracting session length from posts on ${esc(basis.session_since || "")}. Earlier reads do not include it, so there is no evidence yet. We do not guess from genres or store listings. It grows as new posts are read.`)}</p></div></div>
      ${lg.length ? `<h3 class="it-sub">${tr("先に知っておきたいこと: 1 回に時間がかかると書かれた作品", "Good to know: titles where players wrote that sessions take a long time")}</h3>
      <ul class="it-long">${lg.map(w => `<li><a href="${A.workUrl(w.id)}">${w.cover ? `<img src="${esc(w.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}<span><b>${esc(nm(w.name))}</b>${w.voices.map(v => `<span>${line(v)}<small>${pp(v.people)}</small></span>`).join("")}</span></a></li>`).join("")}</ul>` : ""}`;
  } else {
    body = `<div class="rv-empty"><div><b>${tr("この体験を書いたプレイヤーの声は、まだ見つかっていません", "No player has written about this yet")}</b></div></div>`;
  }
  const more = PAGE === "friends" ? `<p class="it-more">${tr("ストアの表示で協力・対戦できる作品をすべて見る:", "All titles the store lists as co-op or versus:")} <a href="coop.html">${tr("協力プレイで遊べる", "Co-op")}</a> ・ <a href="versus.html">${tr("対戦プレイで遊べる", "Versus")}</a></p>` : "";
  $("it-body").innerHTML = `${tabs}${intro}${body}${more}
    <p class="fsrc">${tr(`世界のプレイヤーが直近 7 日に書いた発言を、作品ごとに AI が読み、具体的な体験を取り出しました（読み取りのある作品 ${num(basis.read_works || 0)}作品）。人数はこちらで数えています（同じ人の複数の発言は 1 人）。原文は載せていません。`,
      `AI read each title's posts from the last 7 days and extracted concrete experiences (${num(basis.read_works || 0)} titles read). Counts are done separately. Original posts are not shown.`)}</p>`;
})();
