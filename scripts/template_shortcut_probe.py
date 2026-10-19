#!/usr/bin/env python3
"""Probe: did FULL_DATASET_v1_checkpoint learn to select among a handful of
canned reason strings, or did it learn the underlying judgment?

Motivated by a finding in scripts/classifier_canary_check.py's gate-3a
result on this checkpoint: 2 of 3 misses emitted a reason string that is a
near-verbatim match for the *other* class's training template, not a
judgment specific to that input. 1,350 of 2,370 training rows (the
paraphrase-generated bucket, plus three of the hand-authored calibration
subcategories) have a reason field built from a small set of fixed string
skeletons -- see TEMPLATES below for exactly where each one comes from.
That's expected supervision, not a bug; the question this probe answers is
narrower: is the model's DECISION quality correlated with whether it falls
back to one of those fixed skeletons, specifically on the canary set where
we also know ground truth?

Method: run the canary set (scripts/classifier_canary_check.CANARY_SET,
the same 31 items, same generation code) against the checkpoint, classify
each item's reason string as "template" if it contains one of the fixed
skeleton substrings below (case-insensitive), and cross-tabulate against
correct/incorrect on every item that has a ground-truth `expected` value
(near_miss items are excluded, same as the gate report). If wrong answers
are disproportionately template-drawn compared to right answers, that's
the shortcut operating -- the model reaches for a canned string instead of
reasoning about this specific input precisely on the cases it gets wrong.

This is NOT a test for literal memorization of specific training rows
(the canary set is confirmed disjoint from training data verbatim by
classifier_canary_check._assert_disjoint_from_training) -- it's a test for
template-selection-by-surface-cue standing in for actual judgment, which is
the narrower, falsifiable version of the memorization worry that a canary
set disjointness check can't itself rule out.

Usage:
    python3 -m scripts.template_shortcut_probe [adapter_dir]

Default adapter_dir: data/router_training/FULL_DATASET_v1_checkpoint
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.classifier_canary_check import CANARY_SET, run_canary  # noqa: E402

DEFAULT_ADAPTER_DIR = (
    Path(__file__).parent.parent / "data" / "router_training" / "FULL_DATASET_v1_checkpoint"
)

# Each entry: (label, fixed substring, source). Substrings are the literal,
# non-interpolated parts of each template -- present verbatim in every row
# that uses that template, regardless of which tool/pattern/reason_core
# filled in the blank. Extracted directly from the generator source, not
# guessed from observed output.
TEMPLATES = [
    ("paraphrase_safe_allow",
     "within its documented purpose, no risk indicators present",
     "router_training/paraphrase_generation.py:103 (350 rows)"),
    ("paraphrase_dangerous_block",
     "matches the intent of a known dangerous pattern",
     "router_training/paraphrase_generation.py:119 (1,000 rows)"),
    ("calib_near_miss_allow",
     "quoted, hypothetical, or referenced as documentation/data",
     "router_training/hand_authored/adversarial_calibration_v2.py:97 (150 rows, fixed, no variation)"),
    ("calib_genuine_attack_bland",
     "regardless of the bland/innocuous framing of the request",
     "router_training/hand_authored/adversarial_calibration_v2.py:154 (75 rows)"),
    ("calib_defensive_unsafe",
     "defensive framing does not substitute for verification, and none is cited",
     "router_training/hand_authored/adversarial_calibration_v2.py:219 (75 rows)"),
]


def classify_template(reason: str | None) -> str | None:
    if not reason:
        return None
    low = reason.lower()
    for label, substr, _src in TEMPLATES:
        if substr.lower() in low:
            return label
    return None


def main() -> None:
    adapter_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ADAPTER_DIR
    if not adapter_dir.exists():
        print(f"FATAL: no adapter checkpoint at {adapter_dir}", file=sys.stderr)
        sys.exit(1)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from agentwarden.policies.classifier import build_classify_prompt
    from router_training.train_common import BASE_MODEL, cuda_actually_works

    print(f"Loading base model {BASE_MODEL} + adapter {adapter_dir} ...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(base, str(adapter_dir))
    model.eval()
    device = "cuda" if cuda_actually_works() else "cpu"
    print(f"device={device}")
    model = model.to(device)

    def generate_fn(prompt: str) -> str:
        enc = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=400).to(device)
        with torch.no_grad():
            out = model.generate(
                **enc, max_new_tokens=128, do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
            )
        new_tokens = out[0][enc["input_ids"].shape[1]:]
        return tokenizer.decode(new_tokens, skip_special_tokens=True)

    results = run_canary(generate_fn)

    # Only items with a ground-truth expected value -- same population the
    # gate report scores (near_miss items excluded, same as gate 1/2/3/3a).
    scored = [r for r in results if r["expected"] is not None]

    rows = []
    for r in scored:
        correct = r["decision"] == r["expected"]
        template_label = classify_template(r["reason"])
        rows.append({
            "id": r["id"], "category": r["category"], "correct": correct,
            "template": template_label, "reason": r["reason"],
        })

    print(f"\n=== TEMPLATE-SHORTCUT PROBE (n={len(rows)} scored items) ===")
    print(f"{'id':<10} {'category':<20} {'verdict':<9} {'template':<28} reason")
    print("-" * 130)
    for row in rows:
        verdict = "correct" if row["correct"] else "WRONG"
        template = row["template"] or "-"
        print(f"{row['id']:<10} {row['category']:<20} {verdict:<9} {template:<28} {row['reason']}")

    n_correct = sum(1 for row in rows if row["correct"])
    n_wrong = len(rows) - n_correct
    n_correct_templated = sum(1 for row in rows if row["correct"] and row["template"])
    n_wrong_templated = sum(1 for row in rows if not row["correct"] and row["template"])

    correct_rate = n_correct_templated / n_correct if n_correct else 0.0
    wrong_rate = n_wrong_templated / n_wrong if n_wrong else 0.0

    print("\n=== CONTINGENCY TABLE: template-drawn reason vs. correctness ===")
    print(f"{'':<12}{'templated':>12}{'non-templated':>16}{'total':>8}")
    print(f"{'correct':<12}{n_correct_templated:>12}{n_correct - n_correct_templated:>16}{n_correct:>8}")
    print(f"{'wrong':<12}{n_wrong_templated:>12}{n_wrong - n_wrong_templated:>16}{n_wrong:>8}")
    print(f"\ntemplate rate among correct answers: {correct_rate:.1%} ({n_correct_templated}/{n_correct})")
    print(f"template rate among wrong answers:    {wrong_rate:.1%} ({n_wrong_templated}/{n_wrong})")
    print(
        "\nInterpretation: if the wrong-answer template rate is markedly higher than the "
        "correct-answer rate, wrong answers are disproportionately template fallbacks rather "
        "than failed attempts at case-specific reasoning -- consistent with template selection "
        "standing in for judgment on exactly the cases the model gets wrong. If the rates are "
        "similar, template use isn't what's distinguishing right from wrong here, and the misses "
        "need a different explanation. N is small (4 wrong, 24 correct) -- read this as a "
        "directional signal, not a statistically powered test."
    )


if __name__ == "__main__":
    main()
