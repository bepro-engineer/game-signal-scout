// 賛否が分かれる作品（#2 2026-11-11 オーナーの左メニュー「ゲームを知る」。実データで成立を確かめて採用）: 同じ作品で、面白いと書いた人と
// 不満を書いた人がどちらも 2 人以上いる作品。カードは「面白いと書いた側（人数・体験）」と「不満を書いた側（人数・体験）」を左右に並べ、
// どこで分かれるかを読者が自分に当てはめて判断できるようにする。人数はこちらで数えた体験の人数（services/intents.divided）。原文は出さない。
(() => {
  const A = window.ASS, { tr, esc, num, nm, tx } = A, D = (A.P || {}).divided || {};
  const $ = id => document.getElementById(id);
  const CJ = { time: ["時間がかかる", "Takes time"], price: ["価格・課金", "Price"], performance: ["動作が重い", "Performance"], bugs: ["不具合", "Bugs"], difficulty: ["難しい", "Difficult"], online: ["接続・対戦相手", "Online"] };
  const lv = w => !w.jp ? "unknown" : w.jp.voice ? "voice" : w.jp.sub ? "sub" : w.jp.ui ? "ui" : "none";
  const JPL = { voice: ["日本語音声", "Japanese audio"], sub: ["日本語字幕", "Japanese subtitles"], ui: ["日本語UI", "Japanese UI"], none: ["日本語非対応", "No Japanese"], unknown: ["日本語未確認", "Japanese unknown"] };
  const jp = k => `<span class="fj fj-${k}">${esc(tr(...JPL[k]))}</span>`;
  const pp = n => n > 1 ? tr(`${num(n)}人`, `${num(n)} players`) : tr("1人", "1 player");
  const line = (x, warn) => `${warn && x.caution && CJ[x.caution] ? `<em>${esc(tr(...CJ[x.caution]))}</em>` : ""}${esc(x.appeal ? tx(x, "appeal") : `${tx(x, "act")} → ${tx(x, "result")}`)}<small>${pp(x.people)}</small>`;
  const items = D.items || [];
  const card = w => `<a class="dv-c" href="${A.workUrl(w.id)}">
      <span class="dv-t">${w.cover ? `<img src="${esc(w.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}<span><b>${esc(nm(w.name))}</b><span class="dv-m">${jp(lv(w))}${A.priceTag(w)}</span></span></span>
      <span class="dv-bar" role="img" aria-label="${esc(tr(`面白い ${w.fun}人・不満 ${w.against}人`, `${w.fun} enjoyed, ${w.against} frustrated`))}"><i style="flex:${w.fun}"></i><i style="flex:${w.against}"></i></span>
      <span class="dv-s"><span class="dv-g"><span class="dv-h">${tr(`面白いと書いた人 ${num(w.fun)}人`, `${num(w.fun)} enjoyed it`)}</span><ul>${w.fun_xs.map(x => `<li>${line(x)}</li>`).join("")}</ul></span>
        <span class="dv-b"><span class="dv-h">${tr(`不満を書いた人 ${num(w.against)}人`, `${num(w.against)} were frustrated`)}</span><ul>${w.against_xs.map(x => `<li>${line(x, true)}</li>`).join("")}</ul></span></span></a>`;
  $("dv-body").innerHTML = (items.length
    ? `<div class="dv-list">${items.map(card).join("")}</div>`
    : `<div class="rv-empty"><div><b>${tr("いま、賛否が分かれている作品は見つかっていません", "No title currently has divided opinions")}</b></div></div>`)
    + `<p class="fsrc">${tr(`世界のプレイヤーが直近 7 日に書いた発言を、作品ごとに AI が読み、具体的な体験を取り出しました（読み取りのある作品 ${num(D.read_works || 0)}作品）。面白いと書いた人と不満を書いた人がどちらも ${num(D.min || 2)}人以上の作品だけを載せています。人数はこちらで数えています（同じ人の複数の発言は 1 人）。原文は載せていません。`,
      `AI read each title's posts from the last 7 days and extracted concrete experiences (${num(D.read_works || 0)} titles read). Only titles where at least ${num(D.min || 2)} players enjoyed it and at least ${num(D.min || 2)} were frustrated. Counts are done separately. Original posts are not shown.`)}</p>`;
})();
