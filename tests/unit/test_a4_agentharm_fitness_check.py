"""Tests for scripts/a4_agentharm_fitness_check.py against a small
synthetic fixture, schema-faithful to the real harmful/benign behavior
files -- exercises the alarm-keyword heuristic and the paired
tool-sequence comparison without needing the real dataset."""
from __future__ import annotations

import json

from scripts.a4_agentharm_fitness_check import ALARM_KEYWORDS, _load_behaviors


def _write(tmp_path, name, behaviors):
    path = tmp_path / name
    path.write_text(json.dumps({"behaviors": behaviors}))
    return path


def test_load_behaviors_reads_real_shaped_fixture(tmp_path):
    behaviors = [
        {"id": "1-1", "target_functions": ["send_email", "post_on_x"], "prompt": "do something"},
    ]
    path = _write(tmp_path, "harmful_behaviors_test_public.json", behaviors)
    loaded = _load_behaviors(path)
    assert loaded == behaviors


def test_alarm_keywords_flag_only_unambiguous_names():
    assert any(k in "create_ransomware" for k in ALARM_KEYWORDS)
    assert any(k in "download_from_alpha_bay" for k in ALARM_KEYWORDS)
    assert not any(k in "send_email" for k in ALARM_KEYWORDS)
    assert not any(k in "post_on_x" for k in ALARM_KEYWORDS)
    assert not any(k in "transfer_money" for k in ALARM_KEYWORDS)
