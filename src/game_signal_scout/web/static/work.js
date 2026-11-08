// 作品詳細（work.html?id=w123）。data/work/<id>.json（事前計算）だけを使う。各ページのカード・作品を探すから開く。
// 構成: 作品の見出し（バナー ／ 画像・作品名・作品情報・リンク・載っているページ ／ あらすじ）→ 話題の動き（全幅 1 段: 出典の切り替え〔2 つ以上のとき〕→ 変化の要約 → 期間ボタンと棒 ｜ 凡例・読み方・言語圏・出典。すべて選んだ出典の数。#53）→ 転換点（全幅・横に 3 列。あるときだけ）→ 創作の動き（作家の数。あるときだけ。#19）。
// 話題の動きと創作の動きは同じ棒の部品（rangeChart）。7 日から始め、30 日（日ごと）・90 日（週ごと）・1 年・全期間（月ごと。長いと四半期）に切り替える（#52。高さは変えない）。
// 変化の要約は事前計算の事実（summary・points）から数で組む（LLM は使わない。変化がなければ「顕著な変化は観測されていない」）。日付を縦に並べない。
// 判定の基準の数字は書かない。色は言語にだけ使う。作品名は省略しない。
(() => {
  const A = window.ASS, { tr, esc, nm, md, ppl, chip, ln, wn, FMT, SEASON, AIR, SRC, GENRE, KIND } = A, W = A.W, $ = id => document.getElementById(id);
  // 年だけ・年月だけの日付（放送前の作品）は、分かっている所までにする
  const ymd = o => !(o && o.y) ? "" : A.lang === "en" ? [o.y, o.m, o.m && o.d].filter(Boolean).map((x, i) => i ? String(x).padStart(2, "0") : x).join("-")
    : o.m ? `${o.y}/${o.m}${o.d ? `/${o.d}` : ""}` : `${o.y}年`;
  const KSHORT = { surge: tr("急増", "Jump"), emergence: tr("新登場", "New"), new_language: tr("言語圏", "New area"), continuing: tr("継続", "Ongoing"), resurgence: tr("再浮上", "Back") };
  const KNAME = { surge: tr("急に増えた", "Jump"), emergence: tr("初めて話題に", "First appearance"), new_language: tr("新しい言語圏でも", "New language area"), continuing: tr("増加が続いている", "Keeps growing"), resurgence: tr("再び話題に", "Back in the conversation") };
  const GROUP = [["emotion", tr("感情", "Feelings"), tr("感じたこと・評価", "What they felt")], ["desire", tr("欲求・意向", "Wants"), tr("求めていること", "What they want")],
    ["action", tr("行動", "Actions"), tr("実際にしたこと", "What they did")], ["share", tr("共有", "Sharing"), tr("共有したこと（要確認）", "What they shared (to be checked)")]];
  const QG = { emotion: GROUP[0][1], complaint: GROUP[0][1], desire: GROUP[1][1], sequel_desire: GROUP[1][1], watch_start: GROUP[2][1], watching: GROUP[2][1],
    source_material_read: GROUP[2][1], recommend: GROUP[2][1], fan_creation: GROUP[2][1], share: GROUP[3][1] };
  const PAGE = { language_spread: [tr("言語圏の広がり", "Language spread"), "langspread.html"],
    post_air: [tr("放送後も熱い（放送を終えた作品・これから終える作品）", "After the finale (ended / ending soon)"), "postair.html"],
    revival: [tr("再燃（話題が落ち着いている作品）", "Heating up again (quiet titles)"), "revival.html"] };
  const name = nm(W.name);
  document.title = `${name} | Game Signal Scout`;
  const days = W.days, last = days.at(-1);
  // 話題の動きは出典（Source）ごとの系列（streams。#53）。棒・札・要約・言語圏・転換点はすべて選んだ出典の数で、出典をまたいで足さない
  const ST = W.streams || [];
  let SI = Math.min(W.lead || 0, Math.max(0, ST.length - 1));

  /* ---------- 作品の見出し: 画像 ｜ 作品名・基本情報 ｜ あらすじ（作品名の列と同じ高さに収まる行数で折りたたみ、続きを読むで全幅に全文）。
     その下に全幅の項目の行（ジャンルとタグ・公式と配信・載っているページ）。2026-10-18 Issue #7: タグと配信リンクを中央の狭い列に積むと、
     その列が見出しの高さを決め、あらすじを折りたたんでも右が空いた。高さは画像と作品名で決まり、あらすじは同じ高さまで伸び、項目は全幅で 1〜2 行 ---------- */
  // あらすじは表示の言語の文だけを出す（ほかの言語の文で埋めない。#60）
  const syn = A.lang === "en" ? W.synopsis.en : W.synopsis.ja;
  // 続編・期の案内だけの短い説明は「あらすじ」と見出さない（#54。作品情報の synopsis_kind）
  // Game: あらすじの代わりにゲーム内容（Steam のストアの「このゲームについて」）
  const NOTE = W.synopsis_kind === "note", SYN = tr("ゲーム内容", "About the game");
  const synNote = A.lang === "en" || !W.synopsis_mt ? "" : `英語の${NOTE ? "説明" : "あらすじ"}を機械翻訳しています。`;
  const row = (label, body, cls = "") => `<div${cls ? ` class="${cls}"` : ""}><dt>${label}</dt><dd>${body}</dd></div>`;
  const STORY = syn ? `<div class="wk-story"><h3>${SYN}</h3><p class="wk-syn" id="wk-syn">${esc(syn).replace(/\n{2,}/g, A.lang === "en" ? " <br><br>" : "<br><br>").replace(/\n/g, A.lang === "en" ? " " : "")}</p>
    <p class="wk-sf"><button type="button" class="wk-more" id="wk-more" aria-controls="wk-syn" aria-expanded="false" hidden>${tr("続きを読む", "Read more")}</button>${synNote ? `<span class="wk-mt">${synNote}</span>` : ""}</p></div>` : "";
  const when = W.year && W.season ? tr(`${W.year}年${SEASON[W.season]}`, `${SEASON[W.season]} ${W.year}`) : W.year ? tr(`${W.year}年`, `${W.year}`) : "";
  const meta = [FMT[W.fmt], when, AIR[W.status], W.episodes ? tr(`全${W.episodes}話`, `${W.episodes} episodes`) : ""].filter(Boolean).join(tr("・", " · "));
  const sub = [W.studios.length ? `${tr("制作", "Studio")}: ${W.studios.join(tr("、", ", "))}` : "", W.source ? `${tr("原作", "Source")}: ${SRC[W.source] || W.source}` : "",
    W.start ? `${tr("放送開始", "Started")}: ${ymd(W.start)}` : "", W.end ? `${tr("放送終了", "Ended")}: ${ymd(W.end)}` : ""].filter(Boolean).join(" ／ ");
  // 外部リンク（web/links.py で重複・リンク切れを除いたもの）。公式サイトは言語を分かるときだけ添え、同じ見出しが並ぶときはドメインと道筋で区別する
  const LL = { ja: ["日本語", "Japanese"], en: ["英語", "English"], zh: ["中国語", "Chinese"], ko: ["韓国語", "Korean"], fr: ["フランス語", "French"],
    es: ["スペイン語", "Spanish"], pt: ["ポルトガル語", "Portuguese"], de: ["ドイツ語", "German"], it: ["イタリア語", "Italian"], th: ["タイ語", "Thai"],
    id: ["インドネシア語", "Indonesian"], vi: ["ベトナム語", "Vietnamese"] };
  const lname = l => l.kind === "official"
    ? (l.lang && LL[l.lang] ? tr(`公式サイト（${LL[l.lang][0]}）`, `Official site (${LL[l.lang][1]})`) : tr("公式サイト", "Official site")) : esc(l.site);
  const link = l => `<a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer"${l.hint ? ` title="${esc(l.url)}"` : ""}>${lname(l)}${l.hint ? `<small class="lh">${esc(l.hint)}</small>` : ""}${
    l.state === "region" ? `<small class="ls">${tr("地域制限あり", "region-limited")}</small>` : ""} ↗</a>`;
  const offi = W.links.filter(l => l.kind === "official"), strm = W.links.filter(l => l.kind === "streaming");
  const links = [offi, strm].filter(x => x.length).map(x => x.map(link).join("")).join('<span class="wk-lsep" aria-hidden="true"></span>');
  const other = A.lang === "en" ? W.name.ja : W.name.en;
  // 前のページへ: このタブで作品詳細へ移る直前のページ（common.js の ass.from）。直接開いたときは作品を探すへの通常のリンク
  const PN = { index: ["ダッシュボード", "Dashboard"], finds: ["プレイヤーの発見", "What players found"], revival: ["再燃", "Heating up again"], postair: ["放送後も熱い", "After the finale"],
    langspread: ["言語圏の広がり", "Language spread"], search: ["作品を探す", "Find titles"], lang: ["言語別の作品", "Titles by language"] };
  const from = A.fromPage(W.id);
  const back = from ? `<a class="wk-back" id="wk-back" href="${esc(from.href)}">${tr(`← 前のページ（${(PN[from.page] || PN.search)[0]}）へ`, `← Back to ${(PN[from.page] || PN.search)[1]}`)}</a>`
    : `<a class="wk-back" href="search.html">${tr("← 作品を探す", "← Find titles")}</a>`;
  // 日本人が最初に判断すること（#2）: 日本語で遊べるか（UI・字幕・音声を分けて）→ 開発元と国・地域 → 機種。出典と確かめた日を添える
  const yn = v => v == null ? `<span class="jq">${tr("未確認", "Unknown")}</span>` : v ? `<span class="jy">${tr("あり", "Yes")}</span>` : `<span class="jn">${tr("なし", "No")}</span>`;
  const J = W.jp;
  const PLAT = { "Windows": "Windows", "Mac": "Mac", "Linux・Steam Deck": "Linux・Steam Deck" };
  const judge = `<div class="wk-judge" id="wk-judge">
      <p class="wkj-jp">${A.jpTag(W)}<span class="wkj-d">${tr("UI", "Interface")} ${yn(J && J.ui)}　${tr("字幕", "Subtitles")} ${yn(J && J.sub)}　${tr("音声", "Voice")} ${yn(J && J.voice)}</span>
        <small class="wkj-s">${J ? tr(`ストアの表記（${esc(W.jp_at || "")} 確認）`, `Store listing (checked ${esc(W.jp_at || "")})`) : tr("ストアの表記を確かめられていません", "Not checked yet")}</small></p>
      <p class="wkj-dev"><b>${tr("開発元", "Developer")}</b> ${A.devLine(W, 99)}${(W.dev || []).some(d => d.ref) ? ` <small class="wkj-s">${tr("国・地域の出典: ", "Country source: ")}${W.dev.filter(d => d.ref).map(d => `<a href="${esc(d.ref)}" rel="noopener" target="_blank">${esc(d.n)} ↗</a>`).join(" ")}</small>` : ""}</p>
      ${(W.plat || []).length ? `<p class="wkj-pl"><b>${tr("機種", "Platforms")}</b> ${W.plat.map(p => esc(PLAT[p] || p)).join(tr("・", ", "))}</p>` : ""}
    </div>`;
  const head = `${back}
    ${W.banner ? `<div class="wk-banner"><img src="${esc(W.banner)}" alt="" referrerpolicy="no-referrer"></div>` : ""}
    <section class="wk-head${W.banner ? "" : " nob"}"><div class="art">${W.cover ? `<img src="${esc(W.cover)}" alt="${esc(name)}" referrerpolicy="no-referrer">` : ""}</div>
      <div class="wk-ht"><h1>${esc(name)}</h1>${other && other !== name ? `<p class="wk-en">${esc(other)}</p>` : ""}
        ${meta ? `<p class="wk-meta">${esc(meta)}</p>` : ""}${sub ? `<p class="wk-sub">${esc(sub)}</p>` : ""}</div>
      ${judge}${STORY}<dl class="wk-rows">
        ${W.genres.length || (W.extra && W.extra.tags.length) ? row(tr("ジャンル・タグ", "Genres & tags"), `<div class="wk-cls">${W.genres.length ? `<p class="wk-g">${W.genres.map(g => `<span>${esc(GENRE[g] || g)}</span>`).join("")}</p>` : ""}<!--tags--></div>`) : ""}
        ${links ? row(tr("公式・配信", "Official & streaming"), `<p class="wk-l">${links}</p>`) : ""}
        ${W.pages.length ? row(tr("載っているページ", "Also on"), `<p class="wk-l wk-pg">${W.pages.map(p => `<a href="${PAGE[p][1]}">${PAGE[p][0]} →</a>`).join("")}</p>`) : ""}</dl>
      <!--cr--></section>`;

  /* ---------- 話題の動き・創作の動き（共通の棒の部品。#52）: 期間（ranges。content.chart_ranges）ごとに、7 日・30 日は日ごと、90 日は週ごと、1 年・全期間は月ごと（長いと四半期）。
     週・月の棒は観測できた日の 1 日平均（content.periods）。一部しか観測できなかった区切りは斜線、1 日も観測できなかった区切りは —（0 で埋めない）。
     日付は幅に合わせて間引き、棒はホバー・タップ・キーボードで期間・数・観測の状態を出す ---------- */
  const MONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const UNIT = { day: tr("日", "day"), week: tr("週", "week"), month: tr("月", "month"), quarter: tr("四半期", "quarter"), year: tr("年", "year") };
  const RLABEL = { 7: tr("7日", "7 days"), 30: tr("30日", "30 days"), 90: tr("90日", "90 days"), 365: tr("1年", "1 year"), all: tr("全期間", "All") };
  const fromTo = (a, b) => a.slice(0, 4) === b.slice(0, 4) ? tr(`${md(a)}〜${md(b)}`, `${md(a)}–${md(b)}`)   // 年をまたぐときは年も
    : tr(`${+a.slice(0, 4)}/${md(a)}〜${+b.slice(0, 4)}/${md(b)}`, `${md(a)}, ${a.slice(0, 4)} – ${md(b)}, ${b.slice(0, 4)}`);
  const span = r => fromTo(r.from, r.to);
  // 区切りの名前（読み方の文）: 週は期間、月は「2026年10月」、四半期は「2026年4Q」
  const pname = (p, u) => { const y = +p.from.slice(0, 4), m = +p.from.slice(5, 7), q = Math.floor((m - 1) / 3) + 1;
    return u === "week" ? fromTo(p.from, p.to) : u === "year" ? tr(`${y}年`, `${y}`) : u === "month" ? tr(`${y}年${m}月`, `${MONS[m - 1]} ${y}`) : tr(`${y}年${q}Q`, `Q${q} ${y}`); };
  const unitText = r => r.unit === "day" ? tr("1日ごと", "Per day") : tr(`${UNIT[r.unit]}ごとの1日平均`, `Daily average per ${UNIT[r.unit]}`);
  // 区切りの下の名前: 週は始まりの日、月は「10月」、四半期は「1Q」、年は「2030年」。年は、間引いた後に見える名前のうち年が変わったところに付ける（thin1）
  const plabel = (p, u) => { const y = +p.from.slice(0, 4), m = +p.from.slice(5, 7), q = Math.floor((m - 1) / 3) + 1;
    if (u === "week") return md(p.from);
    if (u === "year") return tr(`${y}年`, `${y}`);
    const [sh, lo] = u === "month" ? [tr(`${m}月`, MONS[m - 1]), tr(`${y}/${m}`, `${MONS[m - 1]} ${y}`)] : [tr(`${q}Q`, `Q${q}`), tr(`${y} ${q}Q`, `Q${q} ${y}`)];
    return `<small data-y="${y}" data-s="${sh}" data-l="${lo}">${lo}</small>`; };
  const kinds = e => e.filter(k => KNAME[k]).map(k => KNAME[k]).join(tr("・", ", "));
  // 1 本の棒（日でも区切りでも同じ作り）: v = 高さの値（観測できなければ null）、o = c / p / n、e = 変化の種類、t = 触れたときの説明
  const bar = (v, mx, o, e, label, t) => `<div class="c${o === "p" ? " pt" : ""}${o === "n" ? " na" : ""}${e && e.length ? " ev" : ""}" tabindex="0" role="img" aria-label="${esc(t)}" data-tip="${esc(t)}">
      <span class="tag">${e && e.length ? e.filter(k => KSHORT[k]).map(k => KSHORT[k]).join(tr("・", " · ")) : ""}</span>
      <span class="bar"><i style="height:${(v || 0) / mx * 100}%"></i></span><b>${o === "n" ? "—" : v}</b>${label.startsWith("<small") ? label : `<small>${label}</small>`}</div>`;
  // 系列 S（days・vals・obs は直近の日ごと、marks、ranges、who = 数の言い方）の期間 r の棒
  const rangeChart = (S, r) => { let cells;
    if (r.unit === "day") { const k = Math.max(0, S.days.length - r.days), mx = Math.max(1, ...S.vals.slice(k).map(v => v || 0));
      cells = S.days.slice(k).map((d, i) => { const o = S.obs[k + i] || "n", v = o === "n" ? null : S.vals[k + i], e = S.marks[d];
        return bar(v, mx, o, e, md(d), o === "n" ? tr(`${md(d)}: 観測できなかった日`, `${md(d)}: not observed`)
          : tr(`${md(d)}: ${v}人${o === "p" ? "（一部の時間だけ観測）" : ""}${e ? `・${kinds(e)}` : ""}`, `${md(d)}: ${S.who(v)}${o === "p" ? " (partly observed)" : ""}${e ? ` · ${kinds(e)}` : ""}`)); });
    } else { const mx = Math.max(1, ...r.items.map(p => p.avg || 0));
      cells = r.items.map((p, i) => { const o = !p.obs ? "n" : p.obs < p.len || p.part ? "p" : "c", per = fromTo(p.from, p.to);   // 観測していない日・範囲の外の日がある区切りは斜線
        return bar(p.avg, mx, o, p.marks, plabel(p, r.unit), !p.obs ? tr(`${per}: 観測できなかった（0/${p.len}日）`, `${per}: not observed (0/${p.len} days)`)
          : tr(`${per}: 1日平均${p.avg}人・延べ${p.sum}人・観測できた日${p.obs}/${p.len}日${p.part ? `（うち一部の時間だけ${p.part}日）` : ""}${p.marks.length ? `・${kinds(p.marks)}` : ""}`,
               `${per}: ${p.avg} a day on average · ${p.sum} in total · observed ${p.obs}/${p.len} days${p.part ? ` (${p.part} partly)` : ""}${p.marks.length ? ` · ${kinds(p.marks)}` : ""}`)); }); }
    return `<div class="wk-ch${cells.length > 14 ? " dense" : ""}" style="--n:${cells.length}">${cells.join("")}</div>`; };
  // 期間の読み方（いちばん多い日・区切り）と、斜線・— の意味
  const noteOf = (S, r) => { if (r.unit === "day") { const k = Math.max(0, S.days.length - r.days), ix = S.days.map((d, i) => i).slice(k);
      const top = ix.reduce((b, i) => (S.vals[i] || 0) > (S.vals[b] || 0) ? i : b, ix[0]);
      return tr(`${fromTo(S.days[k], S.days.at(-1))}でいちばん多い日は${md(S.days[top])}の${S.vals[top] || 0}人。${S.what[0]}斜線の日は一部の時間しか観測できなかった日で、数が実際より少ないことがあります。—は観測できなかった日、0人の日は観測はできていて該当がなかった日です。`,
        `Busiest day between ${fromTo(S.days[k], S.days.at(-1))}: ${md(S.days[top])} with ${S.who(S.vals[top] || 0)}. ${S.what[1]}Hatched days were only partly observed, so counts may be low. — means not observed; 0 means observed with nothing found.`); }
    const full = r.items.filter(p => p.obs === p.len && !p.part), pool = full.length ? full : r.items, u = UNIT[r.unit];   // いちばん多い区切りは、すべての日を観測できた区切りから
    const top = pool.reduce((b, p) => (p.avg || 0) > (b.avg || 0) ? p : b, pool[0]);
    return tr(`${span(r)}を${u}ごとにまとめ、棒は観測できた日の1日平均の人数です。1日平均がいちばん多い${u}は${pname(top, r.unit)}の${top.avg || 0}人（延べ${top.sum}人${full.length ? `。斜線の${u}を除く` : ""}）。${S.what[0]}斜線は観測していない日がある${u}、—は1日も観測できなかった${u}で、0人とは分けています。`,
      `${span(r)}, grouped by ${u}; each bar is the daily average over observed days. Highest: ${pname(top, r.unit)} with ${top.avg || 0} a day (${top.sum} in total${full.length ? `; hatched ${u}s excluded` : ""}). ${S.what[1]}Hatched ${u}s include days not observed; — means not observed at all (not zero).`); };
  const keyOf = r => { const u = UNIT[r.unit]; return `<span><i class="ev"></i>${tr(`変化が見つかった${u}`, `${r.unit === "day" ? "Day" : "Period"} with a change`)}</span><span><i></i>${tr(`それ以外の${u}`, "Others")}</span>
      <span><i class="pt"></i>${tr(r.unit === "day" ? "一部の時間だけ観測できた日" : `観測していない日がある${u}`, "Partly observed")}</span><span><i class="na"></i>${tr(`観測できなかった${u}（—）`, "Not observed (—)")}</span>`; };
  const BOX = [];   // 棒の部品の一覧（id = wk-c<番号>）
  const rangeBox = (S, k = BOX.length, cur = 0) => { BOX[k] = { ...S, cur }; const id = `wk-c${k}`, r = S.ranges[cur];
    return `${S.ranges.length > 1 ? `<p class="wk-rng" role="group" aria-label="${tr("期間", "Range")}">${S.ranges.map((x, i) => `<button type="button" data-box="${k}" data-r="${i}" aria-pressed="${i === cur}">${RLABEL[x.key] || esc(x.key)}</button>`).join("")}<span class="u" id="${id}-u">${unitText(r)}</span></p>` : ""}
      <p class="wk-read" id="${id}-r" aria-live="polite"></p><div class="wk-chart" id="${id}-ch">${rangeChart(S, r)}</div>`; };
  const fallback = n => [{ key: "all", unit: "day", days: n, from: days[Math.max(0, days.length - n)], to: last }];

  /* ---------- 変化の要約: 選んだ出典の事前計算の事実から数で組み、話題の動きのカードの先頭に置く（結論 → 棒 → 読み方の順。2026-10-18 Issue #7） ---------- */
  const lnames = cs => cs.map(c => esc(ln(c))).join(tr("・", ", "));
  const slabel = st => esc(tr(st.label[0], st.label[1]));
  const summaryOf = st => { const SM = st.summary || {}, L = SM.latest || {}, sent = [];
    const notable = ["surge", "emergence", "new_language", "continuing"].includes(L.kind) || ((st.point_sets || {}).base || []).length > 0 || (SM.new_langs || []).length > 0;
    if (!notable) sent.push(tr("顕著な変化は観測されていません。", "No notable change has been observed."));
    if (SM.recent) sent.push(tr(`直近の観測${SM.recent.days}日（${md(SM.recent.from)}〜${md(SM.recent.to)}）に話題にした人は延べ${SM.recent.people}人${SM.before ? `、その前の${SM.before.days}日は${SM.before.people}人` : ""}です。`,
      `Over the last ${SM.recent.days} observed days (${md(SM.recent.from)}–${md(SM.recent.to)}) ${SM.recent.people} people talked about it${SM.before ? `, versus ${SM.before.people} in the ${SM.before.days} days before` : ""}.`));
    if (L.kind === "surge") sent.push(tr(`${md(L.day)}は${L.n}人で、普段（中央値${L.base}人）の${L.ratio}倍に急に増えました。`, `On ${md(L.day)}, ${A.ppl(L.n)} — ${L.ratio}× the usual (median ${L.base}).`));
    else if (L.kind === "emergence") sent.push(tr(`${md(L.day)}に初めて話題になりました（${L.n}人）。`, `It was first talked about on ${md(L.day)} (${A.ppl(L.n)}).`));
    else if (L.kind === "new_language") sent.push(tr(`${md(L.day)}に新しい言語圏（${lnames(L.langs)}）でも話題になりました（${L.n}人）。`, `On ${md(L.day)} it was also talked about in a new language area (${lnames(L.langs)}; ${A.ppl(L.n)}).`));
    else if (L.kind === "continuing") sent.push(tr(`${md(L.day)}も${L.n}人で、${L.streak}日続いています。`, `${A.ppl(L.n)} on ${md(L.day)} — ${L.streak} days in a row.`));
    else if (L.kind === "steady") sent.push(tr(`${md(L.day)}は${L.n}人で普段どおりです。`, `${A.ppl(L.n)} on ${md(L.day)}, about the usual.`));
    else if (L.observed === false) sent.push(tr(`${md(L.day)}は観測できていません。`, `${md(L.day)} was not observed.`));
    else if (L.n != null) sent.push(tr(`${md(L.day)}に話題にした人は${L.n}人です。`, `${A.ppl(L.n)} on ${md(L.day)}.`));
    if ((SM.new_langs || []).length) sent.push(tr(`直近7日で初めて話題になった言語圏: ${lnames(SM.new_langs)}。`, `Language areas seen for the first time in the last 7 days: ${lnames(SM.new_langs)}.`));
    return (ST.length > 1 ? tr(`${slabel(st)}では、`, `On ${slabel(st)}: `) : "") + sent.join(A.lang === "en" ? " " : ""); };
  /* ---------- 話題の動き（全幅 1 段）: 出典の切り替え（2 つ以上のとき）→ 要約 → 期間ボタンと棒（左）｜ 凡例・読み方・言語圏・出典（右）。棒は右の列の高さまで伸び、段の中に空きを作らない。
     要約や説明の長さで棒の幅は変わらない（2026-10-18 Issue #7: 左右の段に分けると要約の下が大きく空き、説明の折り返しで左だけが縦に伸びた） ---------- */
  const streamS = st => ({ days, vals: st.series.map((x, i) => (st.observed[i] || "n") === "n" ? null : x.a), obs: st.observed, marks: st.marks || {},
    ranges: st.ranges || fallback(days.length), who: n => A.ppl(n || 0), what: ["", ""] });
  const trendBody = (st, cur = 0) => { const S = streamS(st), r = S.ranges[cur], langTot = {};
    st.series.forEach(x => Object.entries(x.l).forEach(([c, n]) => { langTot[c] = Math.max(langTot[c] || 0, n); }));
    return `${ST.length > 1 ? `<p class="wk-rng wk-srcsel" role="group" aria-label="${tr("出典", "Source")}"><span class="u">${tr("出典", "Source")}</span>${ST.map((x, i) => `<button type="button" data-stream="${i}" aria-pressed="${i === SI}">${slabel(x)}${tr(`（延べ${x.persons_days}人）`, ` (${x.persons_days})`)}</button>`).join("")}</p>` : ""}
      <p class="wk-sum"><b class="lb">${tr("変化の要約", "What changed")}</b>${summaryOf(st)}</p>
      <div class="wk-trc">${rangeBox(S, 0, cur)}</div>
      <div class="wk-trt"><p class="wk-key" id="wk-c0-k">${keyOf(r)}</p>
        <p class="wk-note" id="wk-c0-n">${noteOf(S, r)}</p>
        ${Object.keys(langTot).length ? `<p class="wk-langs"><span>${tr("話題になった言語圏", "Language areas")}</span>${Object.entries(langTot).sort((a, b) => b[1] - a[1]).map(([c]) => chip(c)).join("")}</p>` : ""}
        <p class="wk-langs wk-src"><span>${tr("出典", "Source")}</span>${slabel(st)}${ST.length > 1 ? tr("（出典ごとに数え、ほかの出典の人数とは足していません）", " (counted per source; never added across sources)") : ""}</p></div>`; };
  const trend = ST.length ? `<section class="wk-sec" id="wk-trend"><div class="sec-h"><h2>${tr("話題の動き", "Buzz over time")}</h2><p>${tr("この作品を話題にした人の数です。上の札は、見つかった変化です。棒に触れると期間・人数・観測の状態が出ます。", "People who talked about this title. Tags show changes found. Hover or tap a bar for the period, count and observation status.")}</p></div>
    <div class="wk-card wk-tr" id="wk-tr0">${trendBody(ST[SI])}</div></section>` : "";

  /* ---------- 転換点: 裏づけのある最大 3 件（日付・種類・人数・普段・言語圏・引用）。話題の動きの期間に合わせて、その期間の中で選んだものを出す（#52）。
     量が日によって違うので、全幅の段に横 3 列（右の段に押し込まない） ---------- */
  const point = p => `<li><b class="d">${md(p.day)}</b><span class="k">${KNAME[p.kind] || esc(p.kind)}</span><span class="n">${tr(`${p.n}人`, A.ppl(p.n))}${p.base != null && p.kind !== "resurgence" ? tr(`（普段${p.base}人・${p.ratio}倍）`, ` (usual ${p.base}, ${p.ratio}×)`) : ""}${p.kind === "resurgence" && p.quiet ? tr(`（${p.quiet}日ぶり）`, ` (after ${p.quiet} quiet days)`) : ""}</span>${p.langs.map(c => chip(c)).join("")}
    ${p.quotes.length ? `<ul class="qs">${p.quotes.map(q => `<li><q>${esc(q.quote)}</q><small class="qg">${tr("自動分類", "Auto type")}: ${esc(QG[q.kind] || "")}</small><a href="${esc(q.url)}" target="_blank" rel="noopener noreferrer">${tr("原文", "Original")} ↗</a></li>`).join("")}</ul>` : ""}</li>`;
  const pHead = r => { const sp = r.unit === "day" ? fromTo(days[0], last) : span(r);
    return tr(`${sp}の中で、データで裏づけのある転換点だけです（最大3件）。原文は、公開してよい投稿の一部です。`, `Only turning points the data supports in ${sp} (up to 3). Quotes are excerpts from posts that may be shown.`); };
  const pset = r => { const st = ST[SI] || {}, by = Object.fromEntries((st.points || []).map(p => [p.day, p]));   // 期間ごとに選んだ日（point_sets。日ごとの期間は base。#52）
    return (((st.point_sets || {})[r.unit === "day" ? "base" : r.key]) || []).map(d => by[d]).filter(Boolean); };
  const pBody = r => { const ps = pset(r); return ps.length ? `<ul class="wk-tp wk-tp3">${ps.map(point).join("")}</ul>` : `<p class="wk-note">${tr("この期間に、裏づけのある転換点はありません。", "No supported turning point in this range.")}</p>`; };
  const R0 = (BOX[0] || {}).ranges ? BOX[0].ranges[0] : null;
  const points = R0 && ST.some(st => (st.points || []).length) ? `<section class="wk-sec" id="wk-points"><div class="sec-h"><h2>${tr("転換点", "Turning points")}</h2><p id="wk-tp-h">${pHead(R0)}</p></div>
    <div class="wk-card" id="wk-tp-b">${pBody(R0)}</div></section>` : "";

  /* ---------- 創作の動き（#19）: 創作を観測する Source の作家の数。話題にした人の数とは別の数で、足さない。Source ごとに 1 枚（Source をまたいで足さない。ADR 0035）。
     作りは話題の動きと同じ（要約 → 期間ボタンと棒 ｜ 読み方・出典。棒は共通の部品） ---------- */
  const CR = W.creation || [];
  const crCard = c => { const idx = days.map((d, i) => i).filter(i => c.o[i] !== "n").slice(-30);
    if (!idx.length) return "";
    const v = idx.map(i => c.n[i]), rec = v.slice(-7), bef = v.slice(-14, -7), sum = a => a.reduce((x, y) => x + y, 0);
    const say = tr(`直近の観測${rec.length}日（${md(days[idx.at(-rec.length)])}〜${md(days[idx.at(-1)])}）にこの作品を描いた作家は延べ${sum(rec)}人${bef.length ? `、その前の${bef.length}日は${sum(bef)}人` : ""}です。`,
      `Over the last ${rec.length} observed days (${md(days[idx.at(-rec.length)])}–${md(days[idx.at(-1)])}) ${sum(rec)} artist-days drew this title${bef.length ? `, versus ${sum(bef)} in the ${bef.length} days before` : ""}.`);
    const S = { days, vals: c.n, obs: c.o, marks: {}, ranges: c.ranges || fallback(idx.length), who: n => `${n || 0} artist${n === 1 ? "" : "s"}`,
      what: ["数えているのは作家（作家のタグ）の数で、投稿した人の数ではありません。成人向けの投稿は数えていません。", "Counts are artists (artist tags), not uploaders. Adult posts are not counted. "] };
    const k = BOX.length;
    return `<div class="wk-card wk-tr"><p class="wk-sum"><b class="lb">${tr("変化の要約", "What changed")}</b>${say}</p>
      <div class="wk-trc">${rangeBox(S)}</div>
      <div class="wk-trt"><p class="wk-note" id="wk-c${k}-n">${noteOf(S, S.ranges[0])}</p>
        <p class="wk-langs wk-src"><span>${tr("出典", "Source")}</span>${esc(tr(c.label[0], c.label[1]))}</p></div></div>`; };
  const crCards = CR.map(crCard).join("");
  const creation = crCards ? `<section class="wk-sec" id="wk-creation"><div class="sec-h"><h2>${tr("創作の動き", "Fan art over time")}</h2><p>${tr("この作品のイラストを描いた作家の数です。話題にした人の数とは別に数えていて、足していません。", "Artists who drew this title. Counted separately from people who talked about it; the two are never added together.")}</p></div>${crCards}</section>` : "";

  /* ---------- AniList の追加の作品情報（ADR 0041）。取れた項目だけ段にする（空のカードを作らない）。出典は最後の段にだけ 1 か所、段の説明文は出さない（2026-10-12 のユーザーの指示） ---------- */
  const X = W.extra, EX = A.EXTRA, num = A.num;
  const ext = (url, label) => url ? `<a class="ex-ext" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>` : "";
  const src = X ? `<p class="ex-src">${tr("出典", "Source")}: ${ext(X.url, "AniList")}${X.fetched ? tr(`（${X.fetched.replace(/-/g, "/")} 時点）`, ` (as of ${X.fetched})`) : ""}</p>` : "";
  const sec = (id, ja, en, body) => body ? `<section class="wk-sec wk-x" id="${id}"><div class="sec-h"><h2>${tr(ja, en)}</h2></div>${body}</section>` : "";
  const titleOf = t => (A.lang === "en" ? t.en || t.ja : t.ja || t.en) || "";
  const more = (id, n, ja, en) => n > 0 ? `<button type="button" class="ex-more" data-more="${id}" aria-expanded="false">${tr(`${ja}（ほか${n}${tr("件", "")}）`, `${en} (${n} more)`)}</button>` : "";
  let score = "", air = "", voices = "", cast = "", rel = "", altrend = "", alSrc = false;
  if (X) {
    /* 評価と視聴状況（AniList の利用者の採点・登録の集計。このサイトの観測人数ではない） */
    const smax = Math.max(1, ...X.scores.map(x => x[1]));
    const cScore = X.score != null ? `<div class="wk-card ex-c"><h3>${tr("平均評価", "Average score")}</h3>
        <p class="ex-big"><b>${X.score}</b><span>/ 100</span></p>
        ${X.votes ? `<p class="ex-mean">${tr(`採点した人 ${num(X.votes)}人`, `${num(X.votes)} ratings`)}</p>` : ""}
        ${X.scores.length ? `<div class="ex-hist" role="img" aria-label="${tr("採点の分布", "Score distribution")}">${X.scores.map(([s, n]) => `<span title="${s}: ${num(n)}"><i style="height:${Math.max(2, n / smax * 100)}%"></i><small>${s}</small></span>`).join("")}</div>
        <p class="ex-cap">${tr("採点の分布（10点ごとの人数）", "Score distribution (people per 10 points)")}</p>` : ""}</div>` : "";
    const cPop = X.popularity ? `<div class="wk-card ex-c"><h3>${tr("人気", "Popularity")}</h3>
        <dl class="ex-kv"><div><dt>${tr("リストに入れた人", "On users' lists")}</dt><dd>${tr(`<b>${num(X.popularity)}</b>人`, `<b>${num(X.popularity)}</b>`)}</dd></div>
        ${X.favourites ? `<div><dt>${tr("お気に入りにした人", "Favorited by")}</dt><dd>${tr(`<b>${num(X.favourites)}</b>人`, `<b>${num(X.favourites)}</b>`)}</dd></div>` : ""}</dl>
        ${X.rankings.length ? `<p class="ex-rk">${X.rankings.map(r => `<span>${esc(EX.RANK(r))}</span>`).join("")}</p>` : ""}</div>` : "";
    const stTot = X.statuses.reduce((a, [, n]) => a + n, 0);
    const cSt = stTot ? `<div class="wk-card ex-c"><h3>${tr("視聴状況", "Watch status")}</h3>
        <p class="ex-stack" role="img" aria-label="${tr("視聴状況の割合", "Watch status shares")}">${X.statuses.map(([k, n]) => `<i style="width:${n / stTot * 100}%;background:${EX.STATUS[k][1]}" title="${esc(EX.STATUS[k][0])}"></i>`).join("")}</p>
        <ul class="ex-leg">${X.statuses.map(([k, n]) => `<li><i style="background:${EX.STATUS[k][1]}"></i><span>${esc(EX.STATUS[k][0])}</span><b>${num(n)}${tr("人", "")}</b><small>${Math.round(n / stTot * 100)}%</small></li>`).join("")}</ul></div>` : "";
    const cards = [cScore, cPop, cSt].filter(Boolean);
    score = cards.length ? sec("wk-score", "評価と視聴状況", "Scores and watch status",
      `<div class="ex-cards n${cards.length}">${cards.join("")}</div>`) : "";

    /* 放送・配信（放送の期間・話数・次回の放送・予告編）。公式サイト・配信サービスは見出しのリンクにある。予告編の絵は作品のバナー（外部の画像を増やさない。配信の CSP） */
    // 過ぎた予定は、画面が開いた時点の時計で外す（作品情報は取得した日の値。まもなく放送の枠と同じ規則）
    const nx = X.next && X.next.airingAt && X.next.airingAt * 1000 > Date.now() ? new Date(X.next.airingAt * 1000) : null;
    const nxs = nx ? nx.toLocaleString(A.lang === "en" ? "en-US" : "ja-JP", { month: "numeric", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "";
    const rows = [
      W.start ? [tr("放送期間", "Run"), `${ymd(W.start)}${W.end ? ` 〜 ${ymd(W.end)}` : tr(" 〜", " –")}`] : null,
      when ? [tr("シーズン", "Season"), when] : null,
      (X.episodes || W.episodes) ? [tr("話数", "Episodes"), tr(`全${X.episodes || W.episodes}話`, `${X.episodes || W.episodes}`) + (X.duration ? tr(`（1話 ${X.duration}分）`, ` (${X.duration} min each)`) : "")] : null,
      nx ? [tr("次の放送", "Next episode"), tr(`第${X.next.episode}話 ${nxs}`, `Ep. ${X.next.episode}: ${nxs}`)] : null,
      X.hashtag ? [tr("公式ハッシュタグ", "Official hashtag"), esc(X.hashtag)] : null].filter(Boolean);
    const trl = X.trailer ? `<a class="wk-card ex-trl" href="https://www.youtube.com/watch?v=${encodeURIComponent(X.trailer.id)}" target="_blank" rel="noopener noreferrer">
        <span class="th">${W.banner || W.cover ? `<img src="${esc(W.banner || W.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}<span class="pl" aria-hidden="true"></span></span>
        <span class="tt">${tr("予告編を YouTube で見る", "Watch the trailer on YouTube")} ↗</span></a>` : "";
    air = rows.length || trl ? sec("wk-air", "放送・配信", "Airing and where to watch",
      `<div class="ex-air${trl ? "" : " one"}">${rows.length ? `<div class="wk-card"><dl class="ex-dl">${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl></div>` : ""}${trl}</div>`) : "";

    /* レビューとプレイヤーの交流（本文は転載しない。採点とリンクだけ）。1 枚のカード: 採点は 2 列に並べ、掲示板のリンクは同じ行に
       （2026-10-18 Issue #7: 「プレイヤーの交流」はリンク 1 つで、隣に小さなカードを置くとその下が空いた） */
    // 件数は出さない（AniList の pageInfo.total は上限で切られることがあり、正しい件数と確かめられない）
    const rv = X.reviews, goRv = ext(X.reviews_url, tr("AniList でレビューを読む", "Read reviews on AniList")), goSo = ext(X.social, tr("AniList の掲示板・活動を見る", "Open forum and activity on AniList"));
    voices = rv.n || goSo ? sec("wk-voices", "レビューとプレイヤーの交流", "Reviews and player discussion",
      `<div class="wk-card ex-c"><h3>${rv.n ? tr("AniList のレビュー", "Reviews on AniList") : tr("プレイヤーの交流", "Fan discussion")}</h3>
        ${rv.n && rv.top.length ? `<ul class="ex-rv">${rv.top.map((r, i) => `<li><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer"><b>${r.score}</b><span>/ 100</span><small>${r.votes ? tr(`${num(r.votes)}人中 ${num(r.up)}人が参考になった`, `${num(r.up)} of ${num(r.votes)} found it helpful`) : tr(`レビュー ${i + 1}`, `Review ${i + 1}`)}</small><em>${tr("読む", "Read")} ↗</em></a></li>`).join("")}</ul>` : ""}
        <p class="ex-go">${rv.n ? goRv : ""}${rv.n && goSo ? `<span class="ex-gl"><span class="lb">${tr("プレイヤーの交流", "Fan discussion")}</span>${goSo}</span>` : goSo}</p></div>`) : "";

    /* キャラクター・スタッフ（最初の 6 人・8 行。もっと見るで続き。全員は AniList で） */
    const RJ = { MAIN: tr("メイン", "Main"), SUPPORTING: tr("サブ", "Supporting"), BACKGROUND: tr("その他", "Background") };
    const CH = 8, ST = 8;
    const cCh = X.chars.length ? `<div class="wk-card ex-c"><h3>${tr("キャラクターと声優", "Characters and voice cast")}</h3>
        <ul class="ex-ch" id="ex-ch">${X.chars.map((c, i) => `<li${i >= CH ? " hidden" : ""}><span class="im">${c.img ? `<img src="${esc(c.img)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}</span>
          <span class="tx"><a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer"><b>${esc(nm(c.name))}</b></a><small class="rl">${RJ[c.role] || ""}</small>
          ${c.va.length ? `<small class="va">${tr("声", "Voice")}: ${c.va.map(v => `<a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(nm(v.name))}</a>`).join(tr("、", ", "))}</small>` : ""}</span></li>`).join("")}</ul>
        <p class="ex-go">${more("ex-ch", X.chars.length - CH, "もっと見る", "Show more")}${ext(X.characters_url, tr("AniList ですべて見る", "See all on AniList"))}</p></div>` : "";
    const cSt2 = X.staff.length ? `<div class="wk-card ex-c"><h3>${tr("制作スタッフ", "Staff")}</h3>        <dl class="ex-dl ex-staff" id="ex-st">${X.staff.map((s, i) => `<div${i >= ST ? " hidden" : ""}><dt>${esc(EX.role(s.role))}</dt><dd><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(nm(s.name))}</a></dd></div>`).join("")}</dl>
        <p class="ex-go">${more("ex-st", X.staff.length - ST, "もっと見る", "Show more")}${ext(X.staff_url, tr("AniList ですべて見る", "See all on AniList"))}</p></div>` : "";
    cast = cCh || cSt2 ? sec("wk-cast", "キャラクター・スタッフ", "Characters and staff",
      `<div class="ex-cards n${[cCh, cSt2].filter(Boolean).length} cast">${cCh}${cSt2}</div>`) : "";

    /* 関連作品・おすすめ（このサイトに作品詳細があれば内側へ。なければ AniList へ） */
    const TL = 6;
    const tile = (x, label, id, i) => { const href = x.inner ? A.workUrl(x.inner) : x.url, out = !x.inner;
      return `<li${i >= TL ? " hidden" : ""}><a href="${esc(href)}"${out ? ' target="_blank" rel="noopener noreferrer"' : ""}>
        <span class="art">${x.cover ? `<img src="${esc(x.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy">` : ""}</span>
        <span class="tx">${wn(x.title, 2, "b")}<small>${[label, FMT[String(x.fmt || "").toLowerCase()], x.year].filter(Boolean).map(esc).join(tr("・", " · "))}</small>
        ${x.score != null && id === "ex-rc" ? `<small>${tr(`平均評価 ${x.score}`, `Score ${x.score}`)}</small>` : ""}<em>${x.inner ? tr("このサイトの作品詳細 →", "Details on this site →") : "AniList ↗"}</em></span></a></li>`; };
    const cRel = X.relations.length ? `<div class="wk-card ex-c"><h3>${tr("関連作品", "Related titles")}</h3><ul class="ex-tiles" id="ex-rl">${X.relations.map((x, i) => tile(x, EX.REL[x.rel], "ex-rl", i)).join("")}</ul>
        <p class="ex-go">${more("ex-rl", X.relations.length - TL, "もっと見る", "Show more")}</p></div>` : "";
    const cRec = X.recs.length ? `<div class="wk-card ex-c"><h3>${tr("この作品が好きな人へのおすすめ", "Recommended if you like this")}</h3>
        <ul class="ex-tiles" id="ex-rc">${X.recs.map((x, i) => tile(x, tr(`${num(x.votes)}人が推薦`, `${num(x.votes)} recommend`), "ex-rc", i)).join("")}</ul>
        <p class="ex-go">${more("ex-rc", X.recs.length - TL, "もっと見る", "Show more")}</p></div>` : "";
    rel = cRel || cRec ? sec("wk-rel", "関連作品・おすすめ", "Related and recommended",
      `${cRel}${cRec}`) : "";

    /* AniList での推移（#37）: その日に AniList の利用者がこの作品をリストに入れた数（前の日からの増え方）。このサイトの「話題にした人」とは別の数で、足さない。
       取った時点でまだ終わっていない日（part）は斜線にして、要約から外す。棒は直近 25 日。 */
    const T = X.trends.slice(-25).filter(t => t.add != null), tl = T.filter(t => !t.part).at(-1);
    const dd = t => { const d = new Date(t.d * 1000); return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`; };
    const done = T.filter(t => !t.part), amx = Math.max(1, ...T.map(t => Math.max(0, t.add))), sumA = a => a.reduce((x, y) => x + Math.max(0, y.add), 0);
    const r7 = done.slice(-7), b7 = done.slice(-14, -7);
    altrend = done.length >= 3 ? sec("wk-altrend", "AniList での推移", "Trends on AniList",
      `<div class="wk-card"><p class="wk-sum"><b class="lb">${tr("変化の要約", "What changed")}</b>${tr(`直近${r7.length}日（${dd(r7[0])}〜${dd(r7.at(-1))}）に AniList でこの作品をリストに入れた人は ${num(sumA(r7))}人${b7.length ? `、その前の${b7.length}日は ${num(sumA(b7))}人` : ""}です。`,
          `In the last ${r7.length} days (${dd(r7[0])}–${dd(r7.at(-1))}), ${num(sumA(r7))} AniList users added this title to their list${b7.length ? `, versus ${num(sumA(b7))} in the ${b7.length} days before` : ""}.`)}</p>
        <div class="ex-tch" style="--n:${T.length}">${T.map(t => { const lab = tr(`${dd(t)}: リストに入れた人 ${num(Math.max(0, t.add))}人${t.part ? "（集計の途中）" : ""}`, `${dd(t)}: ${num(Math.max(0, t.add))} added${t.part ? " (still counting)" : ""}`);
          return `<span class="${t.part ? "pt" : ""}" role="img" aria-label="${esc(lab)}" title="${esc(lab)}"><i style="height:${Math.max(2, Math.max(0, t.add) / amx * 100)}%"></i></span>`; }).join("")}</div>
        <p class="ex-tax"><span>${dd(T[0])}</span><span>${dd(T.at(-1))}</span></p>
        <dl class="ex-kv ex-kv3"><div><dt>${tr(`${dd(tl)} にリストに入れた人`, `Added on ${dd(tl)}`)}</dt><dd><b>${num(Math.max(0, tl.add))}</b>${tr("人", "")}</dd></div>
          ${tl.wip != null ? `<div><dt>${tr(`${dd(tl)} の視聴中の人`, `Watching on ${dd(tl)}`)}</dt><dd><b>${num(tl.wip)}</b>${tr("人", "")}</dd></div>` : ""}
          ${tl.sc != null ? `<div><dt>${tr("その日の平均評価", "Average score that day")}</dt><dd><b>${tl.sc}</b> / 100</dd></div>` : ""}</dl>
        <p class="wk-note">${tr("AniList（ゲームの視聴記録のサービス）の利用者が、この作品を自分のリストに入れた数です（1日ごと。前の日からの増え方）。このサイトで話題にした人の数とは別に数えていて、足していません。斜線の日はまだ集計の途中です。",
          "How many AniList users added this title to their list each day (the day-to-day increase). Counted separately from the people who talked about it on this site; the two are never added together. Hatched days are still being counted.")}</p></div>`) : "";
    /* 出典は、出ている AniList の段のうち最後の段の終わりに 1 か所だけ */
    const segs = { score, air, voices, cast, rel, altrend }, last = Object.keys(segs).filter(k => segs[k]).pop();
    if (last) ({ score, air, voices, cast, rel, altrend } = { ...segs, [last]: segs[last].replace(/<\/section>$/, `${src}</section>`) });
    alSrc = !!last;
  }
  // タグ（AniList。ネタバレのタグ・成人向けのタグは出さない。関連の強いものから 8 つ、続きは「すべてのタグ」）
  const tags = X && X.tags.length ? `<p class="wk-tg">${X.tags.map((t, i) => `<span class="t"${i >= 8 ? " hidden" : ""} title="${esc(t.name)}">${esc(EX.tag(t.name))}</span>`).join("")}${X.tags.length > 8 ? `<button type="button" class="ex-more sm" data-more="wk-tg" aria-expanded="false">${tr(`すべてのタグ（ほか${X.tags.length - 8}）`, `All tags (${X.tags.length - 8} more)`)}</button>` : ""}</p>` : "";

  const cr = W.credit && !alSrc ? `<p class="wk-cr">${tr("作品情報", "Title info")}: <a href="${esc(W.credit_url)}" target="_blank" rel="noopener noreferrer">${esc(W.credit)} ↗</a></p>` : "";
  $("wk").innerHTML = `${head.replace("<!--tags-->", tags).replace("<!--cr-->", cr)}${score}<div class="wk-grid">${trend}${points}${creation}</div>${air}${voices}${cast}${rel}${altrend}`;
  // もっと見る: 隠した行を出す（もう一度押すと戻す）。内側のスクロールは使わない
  document.querySelectorAll(".ex-more").forEach(b => b.addEventListener("click", () => {
    const box = b.dataset.more === "wk-tg" ? b.closest(".wk-tg") : $(b.dataset.more), open = b.getAttribute("aria-expanded") !== "true", lim = ["wk-tg", "ex-st", "ex-ch"].includes(b.dataset.more) ? 8 : 6;
    [...box.children].filter(x => !x.classList.contains("ex-more") && !x.classList.contains("lb")).forEach((x, i) => { if (i >= lim) x.hidden = !open; });
    if (!b.dataset.label) b.dataset.label = b.textContent;
    b.setAttribute("aria-expanded", String(open)); b.textContent = open ? tr("閉じる", "Show less") : b.dataset.label; }));

  // あらすじの折りたたみ: 作品名の列の高さ（狭い画面は 3 行）を超えるときだけボタンを出す（短いあらすじには出さない）。全文は消さず、表示だけを切り替える
  { const p = $("wk-syn"), b = $("wk-more");
    if (p && b) {
      const st = p.closest(".wk-story"), ht = document.querySelector(".wk-ht");
      const fit = () => { if (b.getAttribute("aria-expanded") === "true") return;
        const lh = parseFloat(getComputedStyle(p).lineHeight) || 26, side = st.offsetLeft > ht.offsetLeft;   // 作品名の横にあるときだけ高さを合わせる
        const room = ht.getBoundingClientRect().bottom - p.getBoundingClientRect().top - (b.parentElement.offsetHeight + 6);
        p.style.setProperty("--cl", String(side ? Math.max(3, Math.floor(room / lh)) : 3));
        b.hidden = p.scrollHeight <= p.clientHeight + 2; };
      b.addEventListener("click", () => { const open = b.getAttribute("aria-expanded") !== "true";
        b.setAttribute("aria-expanded", String(open)); p.classList.toggle("open", open); st.classList.toggle("open", open);
        b.textContent = open ? tr("閉じる", "Close") : tr("続きを読む", "Read more"); if (!open) p.closest(".wk-head").scrollIntoView({ block: "nearest" }); });
      fit(); window.addEventListener("resize", fit); if (document.fonts) document.fonts.ready.then(fit);
      try { if (new URLSearchParams(location.search).get("syn") === "open" && !b.hidden) b.click(); } catch (e) { /* 確認用 */ } } }
  // 前のページへ: 戻る先に、そのときの位置と状態（日付は sessionStorage のまま・探す条件・スクロール位置）を戻させる
  { const a = $("wk-back"); if (a && from) a.addEventListener("click", () => A.goBack(from)); }
  // 棒の部品: 期間の切り替え（高さは変えない。話題の動きは転換点・凡例・読み方も同じ期間に）と、日付の間引き（幅に入る数だけ。最初と最後を優先し、重ねない）。
  // 数や札が棒の幅に収まらないときは、数を隠して札を点にする（触れると出る）。図は枠の外へはみ出さない（#52）
  { const LW = A.lang === "en" ? 48 : 40;
    const thin1 = ch => { const ls = [...ch.querySelectorAll("small")], n = ls.length; if (!n) return;
      const c0 = ch.querySelector(".c");
      if (!ch.classList.contains("dense") && [...ch.querySelectorAll(".c > b, .c > .tag")].some(x => x.scrollWidth > c0.clientWidth + 1)) ch.classList.add("dense");
      const lw = Math.max(LW, ...ls.map(l => l.scrollWidth + 8));                        // いちばん長い名前（「2027 1Q」など）が重ならない間隔
      const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(ch.clientWidth / lw))));
      const on = new Set(); for (let i = 0; i < n; i += step) on.add(i);                 // 最初から step ごと
      const lastReg = Math.floor((n - 1) / step) * step; if (lastReg !== n - 1) on.delete(lastReg); on.add(n - 1);   // 最後は必ず出し、近すぎる手前の 1 つを消す
      ls.forEach((l, i) => l.classList.toggle("off", !on.has(i)));
      let py = null; ls.forEach((l, i) => { if (!l.dataset.y || !on.has(i)) return; l.textContent = l.dataset.y !== py ? l.dataset.l : l.dataset.s; py = l.dataset.y; }); };
    // 選んだ棒の値（日付・人数・観測の状態）をグラフの上の 1 行に出す。初めは最新の棒。ホバー・タップ・キーボードで変わる（#59: 30 日は棒が細く数を隠すので、値が読めなかった）
    const pick = (k, c) => { const ch = $(`wk-c${k}-ch`), rd = $(`wk-c${k}-r`); if (!ch || !rd || !c) return;
      const cs = [...ch.querySelectorAll(".c")]; BOX[k].sel = cs.indexOf(c);   // 描き直し（幅の変化）でも選んだ棒を保つ
      cs.forEach(x => x.classList.toggle("sel", x === c)); rd.textContent = c.dataset.tip; };
    const paint = k => { const S = BOX[k], r = S.ranges[S.cur], ch = $(`wk-c${k}-ch`);
      ch.innerHTML = rangeChart(S, r); thin1(ch.querySelector(".wk-ch"));
      const cs = [...ch.querySelectorAll(".c")]; pick(k, cs[S.sel] || cs.at(-1));
      if ($(`wk-c${k}-u`)) $(`wk-c${k}-u`).textContent = unitText(r);
      if ($(`wk-c${k}-n`)) $(`wk-c${k}-n`).innerHTML = noteOf(S, r);
      if ($(`wk-c${k}-k`)) $(`wk-c${k}-k`).innerHTML = keyOf(r);
      if (k === 0 && $("wk-tp-b")) { $("wk-tp-h").textContent = pHead(r); $("wk-tp-b").innerHTML = pBody(r); } };
    // 期間と出典の切り替え（描き直した後のボタンにも効くよう、ページで受ける）。出典を替えても、同じ期間があればその期間のまま
    const onBar = e => { const c = e.target.closest && e.target.closest(".wk-chart .c"); if (c) pick(+c.closest(".wk-chart").id.slice(4, -3), c); };
    ["pointerover", "focusin", "click"].forEach(t => document.addEventListener(t, onBar));
    document.addEventListener("click", e => { const b = e.target.closest("button[data-box], button[data-stream]"); if (!b) return;
      if (b.dataset.stream != null) { const key = BOX[0].ranges[BOX[0].cur].key; SI = +b.dataset.stream;
        const rs = streamS(ST[SI]).ranges, cur = Math.max(0, rs.findIndex(x => x.key === key)); $("wk-tr0").innerHTML = trendBody(ST[SI], cur); paint(0); return; }
      // 期間を替えたら最新の棒から
      const k = +b.dataset.box; BOX[k].cur = +b.dataset.r; BOX[k].sel = null; b.parentNode.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b))); paint(k); });
    const all = () => BOX.forEach((S, k) => $(`wk-c${k}-ch`) && paint(k));
    all(); window.addEventListener("resize", all); if (document.fonts) document.fonts.ready.then(all); }
})();

