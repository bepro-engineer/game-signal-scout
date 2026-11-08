// プレイヤーの発見（#2）: 世界のプレイヤーが実際に遊んで書いた「何をして → 何が起きて → 何が面白かったか（醍醐味）」。
// 並び: 面白さの種類で絞る札（実際に体験のある種類だけ・件数つき）→ 日本語の凡例 → 醍醐味のカード → 買う前に知っておきたいこと（不満・注意）。
// 人数は確からしさの目安（多い＝面白い、ではない）。ひとりの体験はそう書く。原文は出さない。数は集計（services/insight）が数えたもの。
(() => {
  const A = window.ASS, { tr, esc, num, nm } = A, P = A.P, FI = (P.finds || {}).items || [], DS = A.discover;
  const Q = (() => { try { return new URLSearchParams(location.search); } catch (e) { return new URLSearchParams(""); } })();
  const st = { k: Q.get("k") || "", jp: Q.get("jp") || "" };
  const $ = id => document.getElementById(id);
  const jpOk = w => ["ui", "sub", "voice"].includes(A.jpLevel(w));
  const ALL = DS.items(FI.filter(w => !st.jp || jpOk(w)));
  const IT = ALL.filter(x => !st.k || x.kind === st.k);
  const url = patch => { const s = { ...st, ...patch }, u = new URLSearchParams(); Object.entries(s).forEach(([k, v]) => v && u.set(k, v)); const q = u.toString(); return `finds.html${q ? `?${q}` : ""}`; };
  const kinds = Object.keys(A.APPEAL).map(k => [k, ALL.filter(x => x.kind === k).length]).filter(([, n]) => n);
  const chips = `<div class="fd-row"><a href="${url({ k: "" })}"${!st.k ? ' class="on" aria-current="true"' : ""}>${tr("すべての面白さ", "All")}<small>${num(ALL.length)}</small></a>
      ${kinds.map(([k, n]) => `<a href="${url({ k: st.k === k ? "" : k })}"${st.k === k ? ' class="on" aria-current="true"' : ""}>${esc(tr(...A.APPEAL[k]))}<small>${num(n)}</small></a>`).join("")}
      <a href="${url({ jp: st.jp ? "" : "any" })}"${st.jp ? ' class="on" aria-current="true"' : ""}>${tr("日本語で遊べる作品だけ", "Playable in Japanese only")}${st.jp ? " ×" : ""}</a></div>`;
  // 買う前に知っておきたいこと: 不満・注意の体験（作品ごと。醍醐味のないものも含む）
  const warns = FI.filter(w => !st.jp || jpOk(w)).flatMap(w => [...w.finds.filter(f => f.verdict === "frustration" || f.caution).map(f => ({ w, f, ev: (f.examples || [])[0] || {}, people: f.people })),
    ...w.singles.filter(e => e.verdict === "frustration" || e.caution).map(e => ({ w, f: e, ev: e, people: 1 }))]).sort((a, b) => b.people - a.people).slice(0, 12);
  const warn = x => `<li><a href="${A.workUrl(x.w.id)}"><b>${esc(nm(x.w.name))}</b></a>${x.f.caution ? `<span class="dc-w">${esc(tr(...DS.CJ[x.f.caution]))}</span>` : ""}
      <span>${DS.evLine(x.ev)}</span><small>${DS.pplWrote(x.people)}</small></li>`;
  $("fd-note").innerHTML = chips;
  $("fd-list").innerHTML = (IT.length ? `${A.jpLegend()}<div class="dcs">${IT.map(DS.card).join("")}</div>`
    : `<div class="rv-empty"><div><b>${tr("この条件に当てはまる体験は、まだありません", "No experiences match yet")}</b>
        <p>${FI.length ? tr(`読んだ ${num(FI.length)}作品の発言のうち、この面白さを書いた体験はまだありませんでした。`, `None of the posts on ${num(FI.length)} titles described this yet.`)
          : tr("まだプレイヤーの発言を読んだ作品がありません。", "No titles have been read yet.")}</p></div></div>`)
    + (warns.length ? `<div class="dsec"><h2>${tr("買う前に知っておきたいこと", "Good to know before buying")}</h2><p class="dl">${tr("プレイヤーが書いた不満と注意です。", "Complaints and cautions players wrote.")}</p><ul class="fd-warn">${warns.map(warn).join("")}</ul></div>` : "")
    + `<details class="fd-how"><summary>${tr("この情報の出どころ", "Where this comes from")}</summary><p>${tr("世界のプレイヤーがこの 7 日に書いた発言を AI が読み、「何をして、何が起きて、何が面白かったか」を取り出しました。人数はこちらで数えています（同じ人の複数の発言は 1 人）。人数は確からしさの目安で、多いほど面白いという意味ではありません。原文は載せていません。",
      "AI read posts from the last 7 days and extracted what players did, what happened and what was fun. Counts are done separately; one player counts once. Original posts are not shown.")}</p></details>`;
})();
