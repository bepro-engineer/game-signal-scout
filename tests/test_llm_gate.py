"""LLM 枠の接続口: 旗がオフなら何もしない。オンなら共有の部品（scout_llm_gate）を通り、別の利用者が持つ間は取れない。

共有の部品が入っていない環境では、オンの試験は skip する（Game は部品を複製しない）。推論エンジンには接続しない。
"""
from __future__ import annotations

import threading

import pytest

from game_signal_scout import llm_gate


def test_disabled_gate_is_a_no_op(monkeypatch):
    monkeypatch.setattr(llm_gate, "_settings", lambda: {"enabled": False})
    with llm_gate.hold("classify") as g:
        assert g is None


def test_enabled_gate_without_component_does_not_run_unguarded(monkeypatch):
    monkeypatch.setattr(llm_gate, "_settings", lambda: {"enabled": True, "config": "/nonexistent/llm_gate.toml"})
    monkeypatch.setattr(llm_gate, "_GATE", None)
    with pytest.raises(llm_gate.GateUnavailableError):
        with llm_gate.hold("classify"):
            pytest.fail("枠なしで中に入った")


def test_enabled_gate_excludes_another_user(monkeypatch, tmp_path):
    sg = pytest.importorskip("scout_llm_gate")
    cfg = tmp_path / "llm_gate.toml"
    cfg.write_text(f'root = "{tmp_path / "gate"}"\nbase_url = "http://127.0.0.1:9"\nwait_seconds = 1\npoll_seconds = 0.05\n')
    monkeypatch.setattr(llm_gate, "_settings", lambda: {"enabled": True, "config": str(cfg)})
    monkeypatch.setattr(llm_gate, "_GATE", None)
    other = sg.Gate(sg.load_config(cfg))          # 別の利用者（Anime や n8n の代わり）
    inside, release = threading.Event(), threading.Event()

    def game_job():
        with llm_gate.hold("classify"):
            inside.set()
            release.wait(5)
    t = threading.Thread(target=game_job)
    t.start()
    assert inside.wait(5)
    with pytest.raises(sg.GateError):
        other.acquire("anime:test", wait=0.3)
    release.set()
    t.join(5)
    other.acquire("anime:test", wait=2)            # Game が返した後は取れる
    other.release()
    assert other.read_state().get("uncertain") is False
