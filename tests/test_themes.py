"""変化の根拠の報告から内容を数える規則（publication/themes）。例文は 2026-11-08 の本番の根拠の言い回しを短く言い換えたもの。"""
from game_signal_scout.publication.themes import label_notes, themes


def keys(notes, side="fail"):
    return {t["key"]: t["n"] for t in themes(notes, side)}


def test_problem_themes_need_two_reports_and_ignore_field_names():
    notes = ["verdict: Game crashes on startup on nvidia card | concludingNotes: Can be fixed by changing config.ini",
             "verdict: crashes instantly, also nvidia | launcher: Lutris",
             "verdict: black screen | onlineMultiplayerAppraisal: fine"]
    k = keys(notes)
    assert k["startup"] == 2 and k["nvidia"] == 2
    assert "black" not in k                  # 1 件だけの内容は出さない
    assert "launcher" not in k and "online" not in k   # 項目名（launcher:・onlineMultiplayerAppraisal:）には当てない


def test_dropped_support_update_and_graphics_from_real_phrasings():
    notes = ["verdict: Linux support ended in latest closed beta", "verdict: Game dropped Linux support",
             "verdict: Unplayable since recent Major Update \"Hostile Encounters\" | graphicalFaults: textures are missing, pink everywhere",
             "verdict: magenta mess after Hostile Encounters update."]
    k = keys(notes)
    assert k["dropped"] == 2 and k["update"] == 2 and k["graphics"] == 2


def test_false_matches_found_in_real_reports_are_avoided():
    assert "performance" not in keys(["currently flags for forbidden software", "it flags the account"])        # flags の lag
    assert "workaround" not in keys(["The devs disabled proton support after switching to Elytra", "after switching to a new anticheat"])
    assert "anticheat" not in keys(["the beacon is broken", "beacon again"])                                  # beacon の eac


def test_fix_side_shows_only_playable_and_workaround():
    notes = ["verdict: Works perfectly out of the box | multiplayer works", "verdict: runs great online", "verdict: works if you use PROTON_USE_WINED3D=1",
             "verdict: launch option -dx11 needed"]
    assert keys(notes, "fix") == {"oob": 2, "workaround": 2}


def test_label_notes_translates_field_names_only():
    assert label_notes("verdict: Crashes | concludingNotes: Works if X | weirdField: y") == "結論: Crashes\n補足: Works if X\nweirdField: y"
    assert label_notes("free text without fields") == "free text without fields"
    assert label_notes(None) == ""
