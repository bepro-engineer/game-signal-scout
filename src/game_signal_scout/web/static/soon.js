// まもなく発売（#2 2026-11-11 オーナーの左メニュー「ゲームを見つける」）: サイドバーの「まもなく発売」と同じデータ（api/soon。signal/upcoming.py）を、
// 全件カードで並べる。発売日が近い作品（日付の順。過ぎた日は開いた時点の日本時間の暦で外す）と、注目の近日発売（発売日が月・四半期・未定）。
// 作品詳細がある作品は詳細へ、ない作品はストアへ。話題にした人の数は、このサイトが数えた人数（あるときだけ）。
(async () => {
  const A = window.ASS, { tr, esc, num, nm, art, wn } = A, $ = id => document.getElementById(id);
  let S = {};
  try { const r = await fetch("api/soon", { cache: "no-store" }); if (r.ok) S = await r.json(); } catch (e) { /* なし */ }
  const today = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  const dated = (S.dated || []).filter(x => x.release.date >= today), picks = S.picks || [];
  const WD = [["日", "Sun"], ["月", "Mon"], ["火", "Tue"], ["水", "Wed"], ["木", "Thu"], ["金", "Fri"], ["土", "Sat"]];
  const when = x => { if (!x.release.date) return tr(x.release.ja, x.release.en);
    const d = new Date(x.release.date + "T00:00:00Z"), w = WD[d.getUTCDay()];
    return x.release.date === today ? tr("今日発売", "Out today") : tr(`${d.getUTCMonth() + 1}/${d.getUTCDate()}（${w[0]}）発売`, `Out ${w[1]} ${d.getUTCMonth() + 1}/${d.getUTCDate()}`); };
  const href = x => x.id ? `href="${A.workUrl(x.id)}"` : `href="${esc(x.store)}" target="_blank" rel="noopener noreferrer"`;
  const card = x => `<li class="so-c"><a class="cardlink" ${href(x)} aria-label="${esc(nm(x.name))}"></a>${art(x)}<div>${wn(x.name, 2)}
      <span class="so-w">${when(x)}</span>${x.people ? `<span class="so-p">${tr(`${num(x.people)}人が話題に`, `${num(x.people)} talking`)}</span>` : ""}${x.id ? "" : `<span class="so-s">${tr("ストアのページへ", "Store page")}</span>`}</div></li>`;
  $("so-body").innerHTML = (dated.length ? `<h3 class="so-h">${tr(`発売日が近い作品（${num(dated.length)}作品）`, `Releasing soon (${num(dated.length)})`)}</h3><ul class="so-list">${dated.map(card).join("")}</ul>` : "")
    + (picks.length ? `<h3 class="so-h">${tr(`注目の近日発売（${num(picks.length)}作品）`, `Anticipated (${num(picks.length)})`)}</h3><ul class="so-list">${picks.map(card).join("")}</ul>` : "")
    + (!dated.length && !picks.length ? `<div class="rv-empty"><div><b>${tr("これから発売の作品は、まだ分かっていません。", "No upcoming games are known yet.")}</b></div></div>` : "")
    + `<p class="fsrc">${tr("ストアの人気の近日発売です。発売日はストアの表示で、変わることがあります。", "Popular upcoming games on the store. Release dates are as shown on the store and may change.")}</p>`;
})();
