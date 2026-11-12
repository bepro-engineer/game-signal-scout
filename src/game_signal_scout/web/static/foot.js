// 全ページ共通のフッター（サイト説明・運営方針・権利関係のページへの入口）。common.js の後に読む
(() => {
  const A = window.ASS, tr = A.tr, main = document.querySelector(".app > main"); if (!main || document.getElementById("site-foot")) return;
  const L = [["about", "このサイトについて", "About"], ["guide", "データの見方", "How to read the data"], ["rights", "出典と権利について", "Sources and rights"],
    ["terms", "利用規約・データ利用ポリシー", "Terms of use"], ["privacy", "プライバシーポリシー", "Privacy policy"]];
  main.insertAdjacentHTML("afterend",   // 本文（main）の外に置く（作品詳細などは本文を後から書き換える）
    `<footer class="site-foot" id="site-foot">
    <nav aria-label="${tr("サイトについて", "About this site")}">${L.map(([k, ja, en]) => `<a href="${k}.html"${A.page === k ? ' aria-current="page"' : ""}>${tr(ja, en)}</a>`).join("")}<button type="button" class="to-top" id="to-top">${tr("↑ 上へ移動", "↑ Back to top")}</button></nav>
    <p>${tr("Game Signal Scout は、ローカル AI で世界のゲームのプレイヤーの反応を分析しています。作品の名前・画像などの権利は、それぞれの権利者に帰属します。作品の情報と画像: Steam",
      "Game Signal Scout analyzes how game players around the world react, using local AI. Rights in titles, images and the like belong to their respective owners. Title information and images: Steam")}</p>
  </footer>`);
  // 一番下まで読んだあと上に戻りやすくする（2026-10-15 のユーザーの指示。リンクの行の右端。新しい段は足さない）
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const toTop = () => window.scrollTo({ top: 0, behavior: still.matches ? "auto" : "smooth" });
  document.getElementById("to-top").addEventListener("click", toTop);
  // 長いページの途中から上のメニューへ戻る右下のボタン（2026-11-12 のオーナーの指示。#2。Anime と同じ操作感）。先頭付近と、最下部の「上へ移動」が見えている間は隠す
  const foot = document.getElementById("site-foot"), name = tr("ページの先頭（メニュー）へ戻る", "Back to top (menu)");
  document.body.insertAdjacentHTML("beforeend", `<button type="button" class="to-top-fab" id="to-top-fab" aria-label="${name}" title="${name}" hidden><span aria-hidden="true">↑</span></button>`);
  const fab = document.getElementById("to-top-fab");
  let footSeen = false, queued = false;
  const update = () => { queued = false; fab.hidden = footSeen || window.scrollY < window.innerHeight; };
  const later = () => { if (!queued) { queued = true; requestAnimationFrame(update); } };
  new IntersectionObserver(([e]) => { footSeen = e.isIntersecting; later(); }).observe(foot);
  addEventListener("scroll", later, { passive: true }); addEventListener("resize", later);
  // 戻ったあと、キーボードで続けて操作できるよう、見えているメニューの先頭（たたんだ幅ではメニューのボタン）に移る
  fab.addEventListener("click", () => { toTop(); [...document.querySelectorAll("#nav a, #navbtn")].find(e => e.getClientRects().length)?.focus({ preventScroll: true }); });
  update();
})();
