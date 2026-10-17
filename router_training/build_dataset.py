"""Orchestrates dataset generation per docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md.

THIS RUN IS A SAMPLE, not the full ~2,300-example dataset — scoped per
the user's explicit request to review a sample (>=20 safe-but-defended,
>=20 BLOCK) before any weights are touched. The hand-authored examples are
the full first-pass draft for those categories; the paraphrase-diversified
bucket here is a small proof-of-pipeline slice, not the full ~1,350.

Usage: python3 -m router_training.build_dataset
"""
from __future__ import annotations

import json
from pathlib import Path

from router_training.contamination_check import check_dataset
from router_training.hand_authored import adversarial_calibration, safe_but_defended
from router_training.paraphrase_generation import generate_dangerous_example, generate_safe_example
from router_training.schema import DatasetManifest, TrainingExample
from router_training.tool_registry import load_arg_patterns, load_tool_registry

OUT_DIR = Path(__file__).parent.parent / "data" / "router_training"

# Modest, deliberately small sample for the paraphrase-diversified bucket
# in this pass -- proves the generation pipeline works correctly across a
# spread of risk levels; NOT the full ~1,350-example target.
PARAPHRASE_SAFE_TOOLS = ["read", "web_search", "sessions_list", "web_fetch", "write", "cron"]
PARAPHRASE_DANGEROUS_SAMPLES = 12   # tool x pattern pairs, sampled below


def generate_paraphrase_sample() -> list[TrainingExample]:
    registry = load_tool_registry()
    patterns = load_arg_patterns()
    examples: list[TrainingExample] = []

    print(f"Generating {len(PARAPHRASE_SAFE_TOOLS)} safe paraphrase examples via hermes3:8b...")
    for name in PARAPHRASE_SAFE_TOOLS:
        try:
            examples.append(generate_safe_example(registry[name]))
            print(f"  ok: {name}")
        except Exception as e:
            print(f"  FAILED: {name}: {e}")

    print(f"Generating {PARAPHRASE_DANGEROUS_SAMPLES} dangerous paraphrase examples via hermes3:8b...")
    # Pair each of a spread of non-always-block, arguably-risky tools with
    # a distinct arg_pattern, so the sample covers pattern diversity too.
    dangerous_tools = ["write_file", "write", "edit", "web_fetch", "cron", "sessions_send"]
    count = 0
    for i, name in enumerate(dangerous_tools):
        if count >= PARAPHRASE_DANGEROUS_SAMPLES:
            break
        for pattern in patterns[i * 2 % len(patterns): i * 2 % len(patterns) + 2]:
            if count >= PARAPHRASE_DANGEROUS_SAMPLES:
                break
            try:
                examples.append(generate_dangerous_example(registry[name], pattern))
                print(f"  ok: {name} / {pattern['description']}")
                count += 1
            except Exception as e:
                print(f"  FAILED: {name} / {pattern.get('description')}: {e}")

    return examples


def build_manifest(examples: list[TrainingExample], contamination) -> DatasetManifest:
    manifest = DatasetManifest(total=len(examples))
    for ex in examples:
        manifest.by_decision[ex.decision] = manifest.by_decision.get(ex.decision, 0) + 1
        manifest.by_reason_type[ex.reason_type] = manifest.by_reason_type.get(ex.reason_type, 0) + 1
        manifest.by_source[ex.source] = manifest.by_source.get(ex.source, 0) + 1
        manifest.by_review_status[ex.review_status] = manifest.by_review_status.get(ex.review_status, 0) + 1
    manifest.contamination_check = {"ok": contamination.ok, "violations": contamination.violations}
    return manifest


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    hand_authored: list[TrainingExample] = list(safe_but_defended.ALL) + list(adversarial_calibration.ALL)
    print(f"Hand-authored (drafted, PENDING review): {len(hand_authored)} "
          f"({sum(1 for e in hand_authored if e.decision == 'ALLOW')} ALLOW / "
          f"{sum(1 for e in hand_authored if e.decision == 'BLOCK')} BLOCK)")

    paraphrase = generate_paraphrase_sample()
    print(f"Paraphrase-diversified (sample, PENDING review): {len(paraphrase)} "
          f"({sum(1 for e in paraphrase if e.decision == 'ALLOW')} ALLOW / "
          f"{sum(1 for e in paraphrase if e.decision == 'BLOCK')} BLOCK)")

    all_examples = hand_authored + paraphrase

    # Structural contamination check (tool overlap with v2 benchmark,
    # forbidden content). We EXPECT the "review_status=pending" flag on
    # every example at this stage -- everything here is a draft awaiting
    # human review, not yet training-eligible. Report that separately from
    # genuine contamination violations, which should be zero.
    contamination = check_dataset(all_examples)
    real_violations = [v for v in contamination.violations if "review_status=pending" not in v]
    pending_count = len(contamination.violations) - len(real_violations)

    manifest = build_manifest(all_examples, contamination)

    out_file = OUT_DIR / "sample.jsonl"
    with out_file.open("w") as f:
        for ex in all_examples:
            f.write(json.dumps(ex.to_dict()) + "\n")

    manifest_file = OUT_DIR / "sample_manifest.json"
    manifest_file.write_text(json.dumps({
        "total": manifest.total,
        "by_decision": manifest.by_decision,
        "by_reason_type": manifest.by_reason_type,
        "by_source": manifest.by_source,
        "by_review_status": manifest.by_review_status,
        "structural_contamination_violations": real_violations,
        "pending_review_count": pending_count,
    }, indent=2))

    print()
    print(f"Wrote {len(all_examples)} examples to {out_file}")
    print(f"Manifest: {manifest_file}")
    print()
    print("=== Contamination check ===")
    print(f"Structural violations (tool overlap, forbidden content): {len(real_violations)}")
    for v in real_violations:
        print(f"  VIOLATION: {v}")
    print(f"Pending-review flags (expected -- every example here is a draft): {pending_count}")
    print()
    print("=== Composition ===")
    print("by_decision:", manifest.by_decision)
    print("by_reason_type:", manifest.by_reason_type)
    print("by_source:", manifest.by_source)


if __name__ == "__main__":
    main()
