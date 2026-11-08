"""変化の根拠の報告から「何が起きたか」を数える（Game 固有。規則は語の一致だけ。LLM は使わない）。

- themes(): 根拠の報告の自由記述に、内容の語（起動直後に落ちる・NVIDIA など）が出る報告の数。2 件以上のものだけを返す。
  画面は「NVIDIA の GPU・ドライバ（4/5 件）」のように、数えた件数と母数をそのまま出す（言い切らない。原因とは書かない）。
- label_notes(): ProtonDB の記述の項目名（verdict など）を日本語にし、項目ごとに改行する。本文は原文のまま（訳さない）。
語の一致なので誤りを含む（例: "online" が単に遊び方を述べている）。2026-11-08 に本番の 76 件の変化の根拠で当たり方を確かめて語を決めた。
"""
from __future__ import annotations

import re

THEMES: list[tuple[str, str, re.Pattern]] = [(k, label, re.compile(p, re.I)) for k, label, p in [
    ("dropped", "開発元が Linux（Proton）での動作を止めた",
     r"(dropp|revok|remov|pull|block|disabl|end|kill)\w*\s+(out\s+)?(the\s+)?(linux|proton|steam ?deck)(\s+support)?|"
     r"(linux|proton|steam ?deck)\s+support\s+(was\s+|has been\s+|is\s+)?(dropp|revok|remov|pull|disabl|end|gone)\w*|"
     r"no longer (supports?|works? on|runs? on) (linux|proton|steam ?deck)|support (was )?revoked|deliberately (dropped|blocked)"),
    ("startup", "起動しない・起動直後に落ちる",
     r"(crash\w*|freez\w*|clos\w*)\s+(on|at|right at|after|during)\s+(the\s+)?(start\s?up|launch\w*|boot\w*|start)|"
     r"(won'?t|doesn'?t|does not|didn'?t|can'?t|cannot|fails? to|not)\s+(even\s+)?(start|launch|boot|open)|crash\w* (instantly|immediately)|"
     r"instant(ly)? crash|on start\s?up|at launch|startup crash"),
    ("black", "黒い画面のまま", r"black screen"),
    ("ingame", "プレイ中に落ちる・固まる",
     r"(crash\w*|freez\w*|hang\w*)\s+(during|mid|in[- ]game|randomly|after a (while|bit|few)|every|frequently|often)|random(ly)? (crash|freez)|"
     r"frequent crash|crashes? (a lot|often|constantly)|crash\w*\s+(at|during|on|after|before|in)\s+(the\s+)?(end|loading|tutorial|cutscene|round|mission|raid|match|map)|"
     r"crash\w*,? once|(system|complete|hard|full) freeze|freez\w* (at|during|after|every|when)|\bhang\w* (right )?after"),
    ("graphics", "表示が崩れる・テクスチャが欠ける",
     r"textures? (are |were |is )?missing|missing textures|\bpink\b|magenta|graphical (glitch|issue|bug|corruption)|rendering (problem|issue|bug)|"
     r"flicker\w*|artifact(s|ing)\b|corrupted (graphics|textures)"),
    ("nvidia", "NVIDIA の GPU・ドライバ", r"nvidia|geforce|\brtx\b|\bgtx\b|dlss"),
    ("amd", "AMD の GPU・ドライバ", r"\bamd\b|radeon|\brx ?\d{3,4}|radv|\bmesa\b"),
    ("anticheat", "アンチチート", r"anti[- ]?cheat|easy ?anti|\beac\b|battl?eye|vanguard|ricochet|\bban(ned)?\b"),
    ("online", "オンライン・マルチプレイ", r"multi-?player|\bonline\b|matchmak\w*|\bservers?\b|cross-?play|\bco-?op\b|\bpvp\b"),
    ("launcher", "ランチャー・ログイン", r"launcher|ea app|ubisoft connect|battle\.net|rockstar|\blog ?in\b|sign[- ]?in|account"),
    ("performance", "動作が重い・カクつく", r"stutter\w*|low fps|fps drop\w*|frame ?drops?|poor performance|performance (is )?(bad|poor|terrible)|\blag(gy|s)?\b|shader comp"),
    ("video", "ムービー・動画が再生されない", r"(cutscenes?|videos?|movies?|fmv)\s+(do(es)?n'?t|don'?t|won'?t|not|aren'?t|are not|fail)|media ?foundation|black (cutscene|video)"),
    ("controller", "コントローラ", r"controller|gamepad|dualsense|dualshock|joystick"),
    ("update", "更新・パッチの後から",
     r"(after|since|before|prior to)\s+(the\s+)?([\w\"'.:-]+\s+){0,4}(update|patch)\b|(update|patch)\s+(broke|broken)|broke(n)? (after|since|with)"),
    ("oob", "設定を変えずに遊べる", r"out of the box|works? (perfectly|flawlessly|great|fine|well)|runs? (perfectly|flawlessly|great|fine|well)|no (issues|problems)|"
     r"plays? (perfectly|flawlessly|great|fine)|just works|no tweaks"),
    ("workaround", "回避策が書かれている",
     r"works? (if|when|with|after|by|fine with)|fix(ed)? (it )?(by|with|using)|can be fixed|workaround|work around|\bsolution\b|"
     r"(by|after|try|tried|need to|have to|must|just|then)\s+(disabl|downgrad|roll\w* back|turn\w* off|delet)\w*|"
     r"launch option|%command%|proton_\w+|winedlloverrides|-dx11|-vulkan|-dx12"),
]]
FIX_KEYS = {"oob", "workaround"}   # 「直った」の根拠は「遊べる」報告。不具合の語（online など）は「online で遊べる」にも当たるので出さない
MIN_REPORTS = 2      # この数以上の報告に出た内容だけを出す（1 件だけの語は個人の事情と区別できない）

# ProtonDB の記述の項目名（sources.protondb.notes の "項目: 本文 | 項目: 本文" の形）
LABELS = {"verdict": "結論", "concludingNotes": "補足", "customizationsUsed": "設定の変更", "significantBugs": "大きな不具合",
          "inputFaults": "入力の不具合", "stabilityFaults": "安定性", "performanceFaults": "性能", "graphicalFaults": "表示の不具合",
          "audioFaults": "音の不具合", "windowingFaults": "ウィンドウ", "saveGameFaults": "セーブ", "launchFlagsUsed": "起動の設定",
          "variant": "Proton の種類", "extra": "その他", "verdictOob": "初期状態での結論", "launcher": "ランチャー", "tinker": "調整",
          "onlineMultiplayerAppraisal": "オンラインの評価", "notesForDevelopers": "開発者への補足"}
_FIELD = re.compile(r"(?:^|\s\|\s)([A-Za-z]+):\s")


def themes(notes: list[str], side: str) -> list[dict]:
    """内容の語が出た報告の数（多い順。MIN_REPORTS 以上だけ）。side = fail は不具合の語、fix は FIX_KEYS だけ。"""
    texts = [_FIELD.sub(" | ", t) for t in notes if t]   # 項目名（launcher: など）には当てない
    out = []
    for key, label, rx in THEMES:
        if (key in FIX_KEYS) != (side == "fix") and key != "workaround":
            continue
        n = sum(1 for t in texts if rx.search(t))
        if n >= MIN_REPORTS:
            out.append({"key": key, "label": label, "n": n})
    return sorted(out, key=lambda x: -x["n"])


def label_notes(notes: str | None) -> str:
    """'verdict: X | concludingNotes: Y' → '結論: X\\n補足: Y'（知らない項目名はそのまま）。"""
    s = (notes or "").strip()
    if not s:
        return ""
    parts = []
    marks = list(_FIELD.finditer(s))
    if not marks or marks[0].start() != 0:
        return s
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(s)
        body = s[m.end():end].strip()
        parts.append(f"{LABELS.get(m.group(1), m.group(1))}: {body}")
    return "\n".join(parts)
