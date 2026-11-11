// 注目の作品（#2。2026-11-09 オーナーが見本で決めた形。旧「見つけた面白さ」）: 世界のプレイヤーが実際に遊んで書いた「何をして → 何が起きて → 何が面白かったか」。
// 並び: 面白さの種類の札（体験のある種類だけ・件数つき。押すと絞る）→ 日本語の凡例 → カード（場面の絵 → 作品の表紙と作品名 → 面白さの一文 → したこと → 起きたこと → 人数・反対の声・日本語）
// → その作品の買う前に知っておきたいこと（AI が不満と判断した体験だけ。賛否の体験の注意の印は良い体験にも付くので使わない。カードの中に）。カードは日本語で遊べる作品を先、その中は話題（直近 7 日の発言）の多い順。
// 人数はこちら（services/insight）で数えたもの。1 人の体験はそう書く。原文は出さない。
(() => {
  const A = window.ASS, { tr, esc, num, nm, tx } = A, FI = ((A.P || {}).finds || {}).items || [];
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
    w.finds.forEach(f => { const ev = (f.examples || [])[0] || {}, x = { w, appeal: tx(f, "appeal"), kind: f.appeal_kind, verdict: f.verdict, act: tx(ev, "act"), result: tx(ev, "result"), people: f.people,
      against: f.verdict === "fun" ? f.frustration || 0 : 0, caution: f.caution };
      if (f.appeal && f.verdict !== "frustration") good.push(x); if (f.verdict === "frustration") warn.push(x); });
    w.singles.forEach(e => { const x = { w, appeal: tx(e, "appeal"), kind: e.appeal_kind, verdict: e.verdict, act: tx(e, "act"), result: tx(e, "result"), people: 1, against: 0, caution: e.caution };
      if (e.appeal && e.verdict !== "frustration") good.push(x); if (e.verdict === "frustration") warn.push(x); });
  });
  // 並び（2026-11-09 オーナー）: 日本語で遊べる作品（UI 以上）を先、その中は話題（直近 7 日の発言）の多い順。同じ作品の中は書いた人の多い順
  const playable = w => ["voice", "sub", "ui"].includes(lv(w)) ? 0 : 1;
  const order = (a, b) => playable(a.w) - playable(b.w) || (b.w.talk || 0) - (a.w.talk || 0) || b.people - a.people;
  good.sort(order); warn.sort(order);
  // 1 作品 1 カード（2026-11-09 オーナー）: 見出しはその作品でいちばん多くの人が書いた面白さ（種類で絞ったときはその種類のもの）。ほかの面白さは 2 つまで添える
  const WB = new Map();   // 作品ごとの 買う前に知っておきたいこと（不満・注意）
  warn.forEach(x => { if (!WB.has(x.w.id)) WB.set(x.w.id, []); WB.get(x.w.id).push(x); });
  const byWork = new Map();
  good.forEach(x => { if (!byWork.has(x.w.id)) byWork.set(x.w.id, []); byWork.get(x.w.id).push(x); });
  const cardsOf = [...byWork.values()].map(xs => { const hit = xs.filter(x => !K || x.kind === K); return hit.length ? { top: hit[0], rest: xs.filter(x => x !== hit[0]) } : null; })
    .filter(Boolean).sort((a, b) => order(a.top, b.top));
  const kinds = Object.keys(KIND).map(k => [k, [...byWork.values()].filter(xs => xs.some(x => x.kind === k)).length]).filter(([, n]) => n);
  const ppl = n => n > 1 ? tr(`${num(n)}人が同じことを書いた`, `${num(n)} players wrote the same`) : tr("1人の体験", "1 player");
  // 絞り込み（#7-A）: 見出しと補助文 → 「すべて」と件数 → 体験の種類（体験のある種類だけ・実際の作品数。段がそろう列数）→ いま表示している結果と解除。
  // 日本語の印の凡例は絞り込みと混ぜず、カードの一覧の説明として下に置く。分類・件数・押したときの動きは変えない
  const nK = kinds.length, cols = nK <= 4 ? nK : [4, 3].sort((x, y) => (Math.ceil(nK / x) * x - nK) - (Math.ceil(nK / y) * y - nK) || y - x)[0];
  const shown = cardsOf.length;
  $("fd-note").innerHTML = good.length ? `<div class="fk-box"><div class="fk-h"><div><h3>${tr("どんな体験を探す？", "What kind of fun are you looking for?")}</h3>
        <p>${tr(`プレイヤーが実際に書いた面白さの種類を選ぶと、その作品だけを表示します（${num(byWork.size)}作品から）。選んだ種類をもう一度押すと解除します。`, `Pick a kind of fun players wrote about to show only those titles (from ${num(byWork.size)}). Press it again to clear.`)}</p></div></div>
      <div class="fk" style="--c:${cols}" data-n="${nK}">${kinds.map(([k, n]) => `<a href="${K === k ? "finds.html" : `finds.html?k=${k}`}"${K === k ? ' class="on" aria-current="true"' : ""}><span>${esc(tr(...KIND[k]))}</span><small>${tr(`${num(n)}作品`, `${num(n)} titles`)}</small></a>`).join("")}</div>
      ${K && KIND[K] ? `<p class="fk-now" role="status">${tr(`「${KIND[K][0]}」を書いた作品 ${num(shown)}作品を表示しています`, `Showing ${num(shown)} titles where players wrote about “${KIND[K][1]}”`)}<a href="finds.html">${tr("選択を解除してすべて表示", "Clear and show all")} ×</a></p>` : ""}</div>
    <div class="flg"><b>${tr("カードの日本語の印", "Japanese support on cards")}</b><span>${jp("voice")} ${tr("声・字幕・UI が日本語", "audio, subtitles and UI")}</span><span>${jp("sub")} ${tr("字幕・UI が日本語（声は外国語）", "subtitles and UI")}</span>
      <span>${jp("ui")} ${tr("メニュー等のみ日本語", "menus only")}</span><span>${jp("none")}</span><small>${tr("出典: 販売元のストアの対応言語", "Source: publisher's store listing")}</small>
      <small>${tr("価格は日本のストアの価格（円）。確かめた日はカードの価格に触れると表示。割引中は通常価格に線", "Prices are Japan store prices in yen; hover for the date checked. Discounts show the regular price struck through")}</small></div>` : "";
  const card = ({ top: x, rest }) => `<a class="fc" href="${A.workUrl(x.w.id)}"><img class="fc-i" src="${esc(img(x.w))}" alt="" referrerpolicy="no-referrer" loading="lazy">
      <div><span class="fc-t">${x.w.cover ? `<img src="${esc(x.w.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}${esc(nm(x.w.name))}</span><b>${esc(x.appeal)}</b>
        <span class="fc-e">${esc(x.act)} → ${esc(x.result)}</span>
        ${rest.length ? `<ul class="fc-r">${rest.slice(0, 2).map(r => `<li>${esc(r.appeal)}<small>${r.people > 1 ? tr(`${num(r.people)}人`, `${num(r.people)} players`) : tr("1人", "1 player")}</small></li>`).join("")}</ul>` : ""}
        ${(WB.get(x.w.id) || []).length ? `<div class="fc-n"><span>${tr("買う前に知っておきたいこと", "Good to know before buying")}</span><ul>${WB.get(x.w.id).slice(0, 2).map(r => `<li>${r.caution ? `<em>${esc(tr(...CJ[r.caution]))}</em>` : ""}${esc(r.act)} → ${esc(r.result)}<small>${r.people > 1 ? tr(`${num(r.people)}人`, `${num(r.people)} players`) : tr("1人", "1 player")}</small></li>`).join("")}</ul></div>` : ""}
        <small><span>${ppl(x.people)}</span>${x.against ? `<span class="fc-w">${tr(`反対の声 ${num(x.against)}人`, `${num(x.against)} disagreed`)}</span>` : ""}${rest.length > 2 ? `<span>${tr(`ほかに${num(rest.length - 2)}件の面白さ`, `+${num(rest.length - 2)} more`)}</span>` : ""}${jp(lv(x.w))}${A.priceTag(x.w)}</small></div></a>`;
  $("fd-list").innerHTML = !good.length
    ? `<div class="rv-empty"><div><b>${tr("まだプレイヤーの発言を読んだ作品がありません", "No titles have been read yet")}</b></div></div>`
    : `<div class="fcs" data-n="${cardsOf.length}" style="--n:${Math.min(3, cardsOf.length)}">${cardsOf.map(card).join("")}</div>
      <p class="fsrc">${tr("世界のプレイヤーが直近 7 日に書いた発言を、作品ごとに AI が読み、具体的な体験を取り出しました。人数はこちらで数えています（同じ人の複数の発言は 1 人）。原文は載せていません。",
        "AI read each title's posts from the last 7 days and extracted concrete experiences. Counts are done separately. Original posts are not shown.")}</p>`;
})();
