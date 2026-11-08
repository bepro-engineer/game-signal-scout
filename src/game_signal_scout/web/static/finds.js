// 見つけた面白さ（#2。2026-11-09 オーナーが見本で決めた形）: 世界のプレイヤーが実際に遊んで書いた「何をして → 何が起きて → 何が面白かったか」。
// 並び: 面白さの種類の札（体験のある種類だけ・件数つき。押すと絞る）→ 日本語の凡例 → カード（場面の絵 → 作品の表紙と作品名 → 面白さの一文 → したこと → 起きたこと → 人数・反対の声・日本語）
// → 買う前に知っておきたいこと（不満・注意のある体験だけ）。カードは日本語の対応の高い順（音声 → 字幕 → UI）、同じ段階の中は書いた人数の多い順。
// 人数はこちら（services/insight）で数えたもの。1 人の体験はそう書く。原文は出さない。
(() => {
  const A = window.ASS, { tr, esc, num, nm } = A, FI = ((A.P || {}).finds || {}).items || [];
  const $ = id => document.getElementById(id);
  const K = (() => { try { return new URLSearchParams(location.search).get("k") || ""; } catch (e) { return ""; } })();
  const KIND = { conquer: ["強敵を自力で乗り越える手応え", "Overcoming tough challenges"], explore: ["探して、見つける喜び", "The joy of exploring"],
    story: ["物語と世界に浸る", "Getting lost in the story"], grow: ["育てて、作り上げる楽しさ", "Building and growing"], team: ["仲間と作戦が決まる快感", "Teamwork that clicks"],
    versus: ["相手との読み合い・駆け引き", "Outplaying opponents"], feel: ["思いどおりに動かす気持ちよさ", "How good it feels to play"], surprise: ["予想外が起きる面白さ", "Surprises"] };
  const CJ = { time: ["時間がかかる", "Takes time"], price: ["価格・課金", "Price"], performance: ["動作が重い", "Performance"], bugs: ["不具合", "Bugs"], difficulty: ["難しい", "Difficult"], online: ["接続・対戦相手", "Online"] };
  const lv = w => !w.jp ? "unknown" : w.jp.voice ? "voice" : w.jp.sub ? "sub" : w.jp.ui ? "ui" : "none";
  const JR = { voice: 0, sub: 1, ui: 2, none: 3, unknown: 4 };
  const JPL = { voice: ["日本語音声", "Japanese audio"], sub: ["日本語字幕", "Japanese subtitles"], ui: ["日本語UI", "Japanese UI"], none: ["日本語非対応", "No Japanese"], unknown: ["日本語未確認", "Japanese unknown"] };
  const jp = k => `<span class="fj fj-${k}">${esc(tr(...JPL[k]))}</span>`;
  // カードの絵: 作品の場面の画像を、同じ作品のカードごとに別の 1 枚に（なければ横長の帯 → ヘッダー → 表紙）
  const nth = {};
  const img = w => { const xs = w.shots || []; const i = nth[w.id] = (nth[w.id] || 0) + 1; return xs.length ? xs[(i - 1) % xs.length] : (w.banner || w.header || w.cover || ""); };
  const good = [], warn = [];
  FI.forEach(w => {
    w.finds.forEach(f => { const ev = (f.examples || [])[0] || {}, x = { w, appeal: f.appeal, kind: f.appeal_kind, verdict: f.verdict, act: ev.act, result: ev.result, people: f.people,
      against: f.verdict === "fun" ? f.frustration || 0 : 0, caution: f.caution };
      if (f.appeal && f.verdict !== "frustration") good.push(x); if (f.verdict === "frustration" || f.caution) warn.push(x); });
    w.singles.forEach(e => { const x = { w, appeal: e.appeal, kind: e.appeal_kind, verdict: e.verdict, act: e.act, result: e.result, people: 1, against: 0, caution: e.caution };
      if (e.appeal && e.verdict !== "frustration") good.push(x); if (e.verdict === "frustration" || e.caution) warn.push(x); });
  });
  const order = (a, b) => JR[lv(a.w)] - JR[lv(b.w)] || b.people - a.people;
  good.sort(order); warn.sort(order);
  // 1 作品 1 カード（2026-11-09 オーナー）: 見出しはその作品でいちばん多くの人が書いた面白さ（種類で絞ったときはその種類のもの）。ほかの面白さは 2 つまで添える
  const byWork = new Map();
  good.forEach(x => { if (!byWork.has(x.w.id)) byWork.set(x.w.id, []); byWork.get(x.w.id).push(x); });
  const cardsOf = [...byWork.values()].map(xs => { const hit = xs.filter(x => !K || x.kind === K); return hit.length ? { top: hit[0], rest: xs.filter(x => x !== hit[0]) } : null; })
    .filter(Boolean).sort((a, b) => order(a.top, b.top));
  const kinds = Object.keys(KIND).map(k => [k, [...byWork.values()].filter(xs => xs.some(x => x.kind === k)).length]).filter(([, n]) => n);
  const ppl = n => n > 1 ? tr(`${num(n)}人が同じことを書いた`, `${num(n)} players wrote the same`) : tr("1人の体験", "1 player");
  $("fd-note").innerHTML = good.length ? `<div class="fk"><a href="finds.html"${!K ? ' class="on" aria-current="true"' : ""}>${tr("すべての面白さ", "All")}<small>${tr(`${num(byWork.size)}作品`, `${num(byWork.size)}`)}</small></a>
      ${kinds.map(([k, n]) => `<a href="finds.html?k=${k}"${K === k ? ' class="on" aria-current="true"' : ""}>${esc(tr(...KIND[k]))}<small>${tr(`${num(n)}作品`, `${num(n)}`)}</small></a>`).join("")}</div>
    <div class="flg"><b>${tr("凡例", "Legend")}</b><span>${jp("voice")} ${tr("声・字幕・UI が日本語", "audio, subtitles and UI")}</span><span>${jp("sub")} ${tr("字幕・UI が日本語（声は外国語）", "subtitles and UI")}</span>
      <span>${jp("ui")} ${tr("メニュー等のみ日本語", "menus only")}</span><span>${jp("none")}</span><small>${tr("出典: 販売元のストアの対応言語", "Source: publisher's store listing")}</small></div>` : "";
  const card = ({ top: x, rest }) => `<a class="fc" href="${A.workUrl(x.w.id)}"><img class="fc-i" src="${esc(img(x.w))}" alt="" referrerpolicy="no-referrer" loading="lazy">
      <div><span class="fc-t">${x.w.cover ? `<img src="${esc(x.w.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}${esc(nm(x.w.name))}</span><b>${esc(x.appeal)}</b>
        <span class="fc-e">${esc(x.act)} → ${esc(x.result)}</span>
        ${rest.length ? `<ul class="fc-r">${rest.slice(0, 2).map(r => `<li>${esc(r.appeal)}<small>${r.people > 1 ? tr(`${num(r.people)}人`, `${num(r.people)}`) : tr("1人", "1")}</small></li>`).join("")}</ul>` : ""}
        <small><span>${ppl(x.people)}</span>${x.against ? `<span class="fc-w">${tr(`反対の声 ${num(x.against)}人`, `${num(x.against)} disagreed`)}</span>` : ""}${rest.length > 2 ? `<span>${tr(`ほかに${num(rest.length - 2)}件の面白さ`, `+${num(rest.length - 2)} more`)}</span>` : ""}${jp(lv(x.w))}</small></div></a>`;
  $("fd-list").innerHTML = !good.length
    ? `<div class="rv-empty"><div><b>${tr("まだプレイヤーの発言を読んだ作品がありません", "No titles have been read yet")}</b></div></div>`
    : `<div class="fcs" data-n="${cardsOf.length}" style="--n:${Math.min(3, cardsOf.length)}">${cardsOf.map(card).join("")}</div>
      ${warn.length ? `<h2 class="fh">${tr("買う前に知っておきたいこと", "Good to know before buying")}</h2><p class="fp">${tr("プレイヤーが書いた不満と注意です。", "Complaints and cautions players wrote.")}</p>
        <ul class="fw">${warn.slice(0, 12).map(x => `<li><a href="${A.workUrl(x.w.id)}"><b>${esc(nm(x.w.name))}</b></a>${x.caution ? ` <span class="fc-w">${esc(tr(...CJ[x.caution]))}</span>` : ""}　${esc(x.act)} → ${esc(x.result)}<small>${ppl(x.people)}</small></li>`).join("")}</ul>` : ""}
      <p class="fsrc">${tr("世界のプレイヤーが直近 7 日に書いた発言を、作品ごとに AI が読み、具体的な体験を取り出しました。人数はこちらで数えています（同じ人の複数の発言は 1 人）。原文は載せていません。",
        "AI read each title's posts from the last 7 days and extracted concrete experiences. Counts are done separately. Original posts are not shown.")}</p>`;
})();
