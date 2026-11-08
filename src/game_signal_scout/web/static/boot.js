// 画面の読み込み。表示する日（URL は変えない）を決め、そのページに必要なデータを接続口（/api/…）から読んでから、ページの JS を動かす。
// <script src="boot.js" data-need="day pages search work" data-run="page.js"></script>
(() => {
  const me = document.currentScript, need = (me.dataset.need || "").split(/\s+/).filter(Boolean), run = (me.dataset.run || "").split(/\s+/).filter(Boolean);
  const A = window.ASS, main = document.querySelector("main");
  // 一時的な失敗（アプリの起動し直し・反映の間の 502/503/504・通信の失敗）は、知らせを出して自動で読み直す（#34: 本文が空のまま残った）
  const TEMP = new Set([502, 503, 504]), WAIT = [2, 4, 8, 15, 30, 30, 30, 30];   // 秒。合わせて約 2 分半
  const get = async p => {
    let r;
    try { r = await fetch(p, { cache: "no-store" }); } catch (e) { e.temporary = true; throw e; }
    if (!r.ok) { const e = new Error(`${p}: ${r.status}`); e.temporary = TEMP.has(r.status); throw e; }
    return r.json();
  };
  const notice = (msg, kind) => {
    if (!main) return;
    let el = document.getElementById("load-note");
    if (!el) { main.insertAdjacentHTML("afterbegin", `<div id="load-note" role="alert"></div>`); el = document.getElementById("load-note"); }
    el.className = kind; el.textContent = msg;
  };
  const fail = err => { console.error(err); notice(A.tr("データを読み込めませんでした。時間をおいて開き直してください。", "Could not load the data. Please try again later."), "load-err"); };
  const load = src => new Promise((ok, ng) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = () => ng(new Error(src)); document.body.appendChild(s); });
  const start = async () => {
    // 表示する日（#48）: 履歴の項目が覚えている日（読み直し・戻る/進む）→ 本文のリンクで持ち越した日（sessionStorage）→ 公開済みの最新の日。
    // 覚えるのは過去の日を選んだときだけ。最新の日を選んだ・ナビで移った（common.js）ときは覚えず、データが更新されたら新しい最新の日を出す
    const days = await get("api/days"), latest = days.built.at(-1);
    let day = (history.state && history.state.day) || A.sstore("ass.day");
    if (!day || !days.built.includes(day)) day = latest;
    const keep = d => {
      const past = d !== latest ? d : null;
      try { if (past) sessionStorage.setItem("ass.day", past); else sessionStorage.removeItem("ass.day"); } catch (e) { /* 保存できない: 最新の日を出す */ }
      try { history.replaceState({ ...(history.state || {}), day: past }, ""); } catch (e) { /* そのまま */ }
    };
    keep(day);
    A.days = days; A.day = day;
    A.setDay = d => { keep(d); location.reload(); };   // 日を変える（URL は変えない）
    const jobs = [];
    if (need.includes("day")) jobs.push(get(`api/days/${day}`).then(x => { A.D = x; }));
    if (need.includes("pages")) jobs.push(get("api/pages").then(x => { A.P = x; }));
    if (need.includes("search")) jobs.push(get("api/search").then(x => { A.S = x; }));
    if (need.includes("work")) {
      const id = new URLSearchParams(location.search).get("id") || "";
      if (!/^w\d+$/.test(id)) throw new Error("bad id");
      jobs.push(get(`api/works/${id}`).then(x => { A.W = x; }));
    }
    await Promise.all(jobs);
    for (const s of run) await load(s);
    // 今日の兆しの文章の組版（6 ページ共通）。ダッシュボードは見出し（h1）があるので、文章は段落だけ。
    // 新しい表示（ui_next。ADR 0045 の文章は原文の抜粋を引用する）では、引用の中の句点で文を分けない（本番の表示はこれまでどおり）
    const qn = !!(A.D && A.D.dashboard && A.D.dashboard.ui_next);
    { const dl = document.querySelector("#lead .lede"); if (dl) { const sp = dl.querySelector(".lede-t"); if (sp) dl.innerHTML = sp.innerHTML; A.shapeDigest(dl, { lead: false, quotes: qn }); } }
    ["#sp-digest .dg-t", "#rv-sum > .dg-t", "#pa-sum > .dg-t", "#ls-sum > .dg-t"].forEach(q => A.shapeDigest(document.querySelector(q), { quotes: qn }));
    A.restoreScroll();   // 言語を切り替えて読み直したときは、見ていた位置へ戻す
  };
  (async () => {
    for (let i = 0; ; i++) {
      try { await start(); break; }
      catch (e) {
        if (!e.temporary || i >= WAIT.length) throw e;
        console.warn(e);
        notice(A.tr("データを準備しています。自動で読み込み直します…", "Preparing the data. Reloading automatically…"), "load-wait");
        await new Promise(ok => setTimeout(ok, WAIT[i] * 1000));
      }
    }
    const el = document.getElementById("load-note"); if (el) el.remove();
  })().catch(fail);
})();
