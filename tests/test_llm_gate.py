"""機械で 1 つの LLM 枠の接続口（Anime の llm_gate.py をそのまま流用）。Anime の試験は Anime だけの常駐・監視に依るので、枠の基本の振る舞いだけを確かめる。"""
import pytest

from game_signal_scout import llm_gate


def test_disabled_gate_is_a_no_op(monkeypatch):
    monkeypatch.setattr(llm_gate, "settings", lambda: {"enabled": False})
    with llm_gate.hold("game:test"):
        pass
    with llm_gate.request("m"):
        pass


def test_enabled_gate_without_component_does_not_run_unguarded(monkeypatch):
    monkeypatch.setattr(llm_gate, "settings", lambda: {"enabled": True, "config": "/nonexistent/llm_gate.toml"})
    llm_gate._load.cache_clear()
    with pytest.raises(llm_gate.GateUnavailableError):
        with llm_gate.hold("game:test"):
            pytest.fail("枠なしで推論を始めてはいけない")
    llm_gate._load.cache_clear()


def test_providers_config_uses_the_shared_gate():
    s = llm_gate.settings()
    assert s["enabled"] is True and s["config"] == "/Users/Shared/scout-infra/llm_gate.toml" and s["owner"] == "game"
