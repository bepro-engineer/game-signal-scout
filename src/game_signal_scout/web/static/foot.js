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
  document.getElementById("to-top").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
})();
