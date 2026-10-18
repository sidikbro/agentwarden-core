"""Regression guard for the D2 classifier's train/serve input format.

This is the SECOND time training and serving have silently diverged on
the exact string sent to the model (see agentwarden/policies/classifier.py
::build_classify_prompt's docstring -- the first was the decision/action
JSON-key mismatch; this one was a trailing "\\n" present in training data
but absent from serving, which made the PILOT_UNREVIEWED_DATA_checkpoint
adapter emit EOS immediately on ~every real query). The fix was to give
both sides exactly one shared builder function rather than two copies kept
in sync by convention. These tests exist so that if a future edit
reintroduces a second copy (inline string-building in train_common.py, or
a backend in classifier.py that bypasses build_classify_prompt), it fails
loudly here instead of silently shipping a checkpoint that can't talk to
its own serving path.
"""
from __future__ import annotations

from agentwarden.policies.classifier import build_classify_prompt
from router_training.train_common import to_training_pair


def test_training_prompt_is_byte_identical_to_serving_prompt():
    example = {
        "tool_name": "read",
        "arguments": {"path": "README.md"},
        "decision": "ALLOW",
        "reason": "test reason",
    }
    train_prompt, _ = to_training_pair(example)
    serve_prompt = build_classify_prompt(example["tool_name"], example["arguments"])
    assert train_prompt == serve_prompt


def test_classify_prompt_ends_with_exactly_one_newline():
    # Pinned down explicitly, not just "matches training": a checkpoint
    # trained on a specific separator is sensitive to exactly this, not
    # "some whitespace" -- zero newlines reproduces the EOS-collapse bug
    # this guards against; two would be an equally silent, equally real
    # divergence from what any future retrain actually sees.
    prompt = build_classify_prompt("read", {"path": "README.md"})
    assert prompt.endswith("\n")
    assert not prompt.endswith("\n\n")


def test_training_pair_target_follows_prompt_with_no_extra_separator():
    # Guards the OTHER half of the format: train_common.py's tokenize() does
    # `prompt + target + eos` (no inserted separator), relying on the
    # prompt itself already ending in "\n". If build_classify_prompt ever
    # stops including that trailing newline, this full/target boundary
    # would silently collapse back into the original bug.
    example = {
        "tool_name": "exec",
        "arguments": {"cmd": "whoami"},
        "decision": "BLOCK",
        "reason": "test reason",
    }
    prompt, target = to_training_pair(example)
    full = prompt + target
    assert full.endswith('"test reason"}')
    assert "\n{" in full  # the single "\n" boundary between prompt and target JSON
