"""Full-scale dataset build per docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md §2's
revised budget (~2,300: 650 hand-authored safe-but-defended, 300
hand-authored adversarial/borderline calibration, 1,350 paraphrase-
diversified). Supersedes build_dataset.py's explicitly-sample-scoped run
(kept as-is, not modified -- its sample.jsonl output stays the
already-reviewed-pending provenance record of the pilot).

Deliberate deviation from a literal reading of §1 ("tools.yaml's 39 real
tools" as ground truth, no further qualification): the paraphrase-
diversified BLOCK bucket (arg_pattern/injection triggers, the Stage-2-
relevant signal) is weighted toward the 27 tools that actually reach
LLMClassifierPolicy in production (agentwarden/policies/classifier.py::
SKIP_CLASSIFIER_TOOLS excludes 12 of the 39 -- read, read_file, ls, glob,
grep, memory_get, memory_search, session_status, web_search, memory_save,
sessions_list, sessions_history -- from ever invoking Stage 2 at all).
Training heavily on tools the classifier will never be asked to classify
in production is a worse use of the same budget than the plan's silent
default of uniform-across-39 would produce. Flagged here explicitly as a
reasoned deviation, not a silent one -- see docs/v2/RECONCILED_STATE_v0.2.md
for the full writeup. The safe/generic bucket still includes skip-tools
(a minority share) since that's a defensible chunk of realistic traffic
composition and matches this project's existing convention of including
a few skip-tool examples "to test classifier reasoning in the abstract."

Usage: python3 -m router_training.build_dataset_full
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from router_training.contamination_check import check_dataset
from router_training.hand_authored import (
    adversarial_calibration,
    adversarial_calibration_v2,
    safe_but_defended,
    safe_but_defended_v2,
    tool_pairing_gapfill,
)
from router_training.paraphrase_generation import generate_dangerous_example, generate_safe_example
from router_training.schema import DatasetManifest, TrainingExample
from router_training.tool_registry import load_arg_patterns, load_tool_registry

OUT_DIR = Path(__file__).parent.parent / "data" / "router_training"

PARAPHRASE_SAFE_TARGET = 350
PARAPHRASE_DANGEROUS_TARGET = 1000

# Skip-classifier tools still get a minority share of the safe bucket
# (realistic-traffic-composition reasoning above); dangerous bucket
# excludes them entirely -- Stage 2 never sees a dangerous-framed call to
# a tool it's never invoked for, so there is no real-world analog to train.
_SKIP_TOOLS_SAFE_SHARE = 0.15


def _weighted_tool_cycle(registry: dict, n: int, include_skip: bool, seed: int) -> list[str]:
    rng = random.Random(seed)
    names = [n for n, e in registry.items() if include_skip or not e.classifier_skip]
    if include_skip:
        skip_names = [n for n, e in registry.items() if e.classifier_skip]
        nonskip_names = [n for n, e in registry.items() if not e.classifier_skip]
        n_skip = int(n * _SKIP_TOOLS_SAFE_SHARE)
        chosen = [rng.choice(skip_names) for _ in range(n_skip)]
        chosen += [rng.choice(nonskip_names) for _ in range(n - n_skip)]
        rng.shuffle(chosen)
        return chosen
    return [rng.choice(names) for _ in range(n)]


def generate_paraphrase_full(progress_every: int = 25) -> list[TrainingExample]:
    registry = load_tool_registry()
    patterns = load_arg_patterns()
    examples: list[TrainingExample] = []

    safe_tools = _weighted_tool_cycle(registry, PARAPHRASE_SAFE_TARGET, include_skip=True, seed=1001)
    print(f"Generating {len(safe_tools)} safe paraphrase examples via hermes3:8b...")
    for i, name in enumerate(safe_tools):
        try:
            examples.append(generate_safe_example(registry[name]))
        except Exception as e:
            print(f"  FAILED safe[{i}] {name}: {e}")
        if (i + 1) % progress_every == 0:
            print(f"  ... {i + 1}/{len(safe_tools)} safe done")

    dangerous_tools = _weighted_tool_cycle(registry, PARAPHRASE_DANGEROUS_TARGET, include_skip=False, seed=2002)
    rng = random.Random(3003)
    print(f"Generating {len(dangerous_tools)} dangerous paraphrase examples via hermes3:8b...")
    for i, name in enumerate(dangerous_tools):
        pattern = rng.choice(patterns)
        try:
            examples.append(generate_dangerous_example(registry[name], pattern))
        except Exception as e:
            print(f"  FAILED dangerous[{i}] {name}/{pattern.get('description')}: {e}")
        if (i + 1) % progress_every == 0:
            print(f"  ... {i + 1}/{len(dangerous_tools)} dangerous done")

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

    hand_authored: list[TrainingExample] = (
        list(safe_but_defended.ALL) + list(safe_but_defended_v2.ALL)
        + list(adversarial_calibration.ALL) + list(adversarial_calibration_v2.ALL)
        + list(tool_pairing_gapfill.ALL)
    )
    print(f"Hand-authored (drafted, PENDING review): {len(hand_authored)} "
          f"({sum(1 for e in hand_authored if e.decision == 'ALLOW')} ALLOW / "
          f"{sum(1 for e in hand_authored if e.decision == 'BLOCK')} BLOCK)")

    paraphrase = generate_paraphrase_full()
    print(f"Paraphrase-diversified (PENDING review): {len(paraphrase)} "
          f"({sum(1 for e in paraphrase if e.decision == 'ALLOW')} ALLOW / "
          f"{sum(1 for e in paraphrase if e.decision == 'BLOCK')} BLOCK)")

    all_examples = hand_authored + paraphrase

    contamination = check_dataset(all_examples)
    real_violations = [v for v in contamination.violations if "review_status=pending" not in v]
    pending_count = len(contamination.violations) - len(real_violations)

    manifest = build_manifest(all_examples, contamination)

    out_file = OUT_DIR / "full_dataset.jsonl"
    with out_file.open("w") as f:
        for ex in all_examples:
            f.write(json.dumps(ex.to_dict()) + "\n")

    manifest_file = OUT_DIR / "full_dataset_manifest.json"
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
