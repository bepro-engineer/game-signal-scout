// 賛否が分かれる作品（#2 2026-11-11 オーナー: 同じ論点で評価が割れた作品だけ）: 同じ対象（場面・仕組み・要素）について、面白かった人と
// 不満だった人がいる作品。カードの主見出しは「何について意見が分かれたか」（論点）。その同じ論点の「良かった」と「不満だった」を左右に比べる。
// 論点に入らない不満は比べる枠に混ぜず、下に「ほかの注意」として小さく出す。人数はこちらで数えた人数（同じ人は 1 人。services/insight.divide）。原文は出さない。
(() => {
  const A = window.ASS, { tr, esc, num, nm, tx } = A, D = (A.P || {}).divided || {};
  const $ = id => document.getElementById(id);
  const L = A.lang;
  const t = o => (o && (L === "en" && o.en ? o.en : o.ja)) || "";
  const lv = w => !w.jp ? "unknown" : w.jp.voice ? "voice" : w.jp.sub ? "sub" : w.jp.ui ? "ui" : "none";
  const JPL = { voice: ["日本語音声", "Japanese audio"], sub: ["日本語字幕", "Japanese subtitles"], ui: ["日本語UI", "Japanese UI"], none: ["日本語非対応", "No Japanese"], unknown: ["日本語未確認", "Japanese unknown"] };
  const jp = k => `<span class="fj fj-${k}">${esc(tr(...JPL[k]))}</span>`;
  const pp = n => n > 1 ? tr(`${num(n)}人`, `${num(n)} players`) : tr("1人", "1 player");
  const ev = x => `<li>${esc(t(x.act))} → ${esc(t(x.result))}</li>`;
  const point = d => `<div class="dv-p"><p class="dv-q">${tr(`「${esc(t(d.point))}」で意見が分かれた`, `Opinions split on: ${esc(t(d.point))}`)}</p>
      <span class="dv-bar" role="img" aria-label="${esc(tr(`良かった ${d.pro_people}人・不満だった ${d.con_people}人`, `${d.pro_people} liked it, ${d.con_people} did not`))}"><i style="flex:${d.pro_people}"></i><i style="flex:${d.con_people}"></i></span>
      <span class="dv-s"><span class="dv-g"><span class="dv-h">${tr(`良かった ${pp(d.pro_people)}`, `Liked it: ${pp(d.pro_people)}`)}</span><ul>${d.pro.map(ev).join("")}</ul></span>
        <span class="dv-b"><span class="dv-h">${tr(`不満だった ${pp(d.con_people)}`, `Did not: ${pp(d.con_people)}`)}</span><ul>${d.con.map(ev).join("")}</ul></span></span></div>`;
  const items = D.items || [];
  const card = w => `<a class="dv-c" href="${A.workUrl(w.id)}">
      <span class="dv-t">${w.cover ? `<img src="${esc(w.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}<span><b>${esc(nm(w.name))}</b><span class="dv-m">${jp(lv(w))}${A.priceTag(w)}</span></span></span>
      ${w.points.map(point).join("")}
      ${(w.other_warn || []).length ? `<span class="dv-o"><em>${tr("ほかの注意（上の論点とは別）", "Other cautions (separate from the above)")}</em>${w.other_warn.map(x => `${esc(tx(x, "act"))} → ${esc(tx(x, "result"))}`).join(tr("／", " / "))}</span>` : ""}</a>`;
  $("dv-body").innerHTML = (items.length
    ? `<div class="dv-list">${items.map(card).join("")}</div>`
    : `<div class="rv-empty"><div><b>${tr("いま、同じ点で意見が分かれている作品は見つかっていません", "No title currently has opinions split on the same point")}</b></div></div>`)
    + `<p class="fsrc">${tr(`同じ場面・仕組み・要素について、面白かった人と不満だった人がどちらもいる作品だけを載せています（違う点の良い声と不満は組にしません）。世界のプレイヤーが直近 7 日に書いた発言を AI が読み、同じ点かどうかを確かめた組だけです（読み取りのある作品 ${num(D.read_works || 0)}作品）。人数はこちらで数えています（同じ人の複数の発言は 1 人）。原文は載せていません。`,
      `Only titles where some players liked and others disliked the same scene, mechanic or element (different points are never paired). AI read posts from the last 7 days and kept only pairs confirmed to be about the same point (${num(D.read_works || 0)} titles read). Counts are done separately. Original posts are not shown.`)}</p>`;
})();
