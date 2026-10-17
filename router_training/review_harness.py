"""Stratified-sample review harness for the hand-authored dataset, per the
2026-10-17 amendment to docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md's
authorship/review protocol.

Strata are (skeleton family, subcategory) for safe-but-defended and
adversarial-calibration, and (gapfill, tool_name) for the tool-pairing
gap-fill set -- gap-fill is kept as its own family rather than merged into
the subcategory it happens to share, because it was authored to fix a
specific, already-identified gap (tool-identity shortcut learning), not as
another instantiation of the same skeleton population.

The 46 individually-authored examples in safe_but_defended.py and
adversarial_calibration.py are deliberately NOT included here -- per the
amendment, they keep the original 100% review requirement and are reviewed
in full, separately, not sampled.

Usage:
    python3 -m router_training.review_harness build     # (re)build the sample, idempotent
    python3 -m router_training.review_harness status     # strata table
    python3 -m router_training.review_harness batch N     # next N unreviewed items, readable
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

from router_training.hand_authored import (
    adversarial_calibration,
    adversarial_calibration_v2,
    safe_but_defended,
    safe_but_defended_v2,
    tool_pairing_gapfill,
)

OUT_DIR = Path(__file__).parent.parent / "data" / "router_training" / "review"
SAMPLE_FILE = OUT_DIR / "stratified_sample.jsonl"
VERDICTS_FILE = OUT_DIR / "verdicts.jsonl"

MIN_SAMPLE = 5
SAMPLE_FRACTION = 0.15
ERROR_RATE_FLAG_THRESHOLD = 0.05

# calibration's three types per the plan; arg_pattern_trigger and
# injection_pattern_trigger are both "genuine-attack-blandly-phrased" per
# §3a -- same calibration type, not two.
_CALIB_TYPE = {
    "near_miss_allow": "near_miss_allow",
    "arg_pattern_trigger": "genuine_attack_bland",
    "injection_pattern_trigger": "genuine_attack_bland",
    "defensively_framed_but_unsafe": "defensively_framed_but_unsafe",
}


def _tagged_examples() -> list[dict]:
    """Returns every hand-authored example tagged with (family,
    stratum_key, review_mode), preserving the exact object from its
    source module (not re-derived from the merged jsonl). review_mode
    "full" = the 46 individually-authored examples, unaffected by the
    2026-10-17 amendment -- reviewed 100%, not sampled. review_mode
    "sampled" = the 1,053 parametrically-generated examples, stratified-
    sampled per the amendment."""
    out = []

    for ex in safe_but_defended.ALL:
        out.append({"family": "safe_but_defended", "stratum": f"sbd_v1::{ex.subcategory}",
                    "review_mode": "full", "ex": ex})
    for ex in safe_but_defended_v2.ALL:
        out.append({"family": "safe_but_defended_v2", "stratum": f"sbd_v2::{ex.subcategory}",
                    "review_mode": "sampled", "ex": ex})

    for ex in adversarial_calibration.ALL:
        ctype = _CALIB_TYPE[ex.reason_type]
        out.append({"family": "adversarial_calibration", "stratum": f"calib_v1::{ctype}",
                    "review_mode": "full", "ex": ex})
    for ex in adversarial_calibration_v2.ALL:
        ctype = _CALIB_TYPE[ex.reason_type]
        out.append({"family": "adversarial_calibration_v2", "stratum": f"calib_v2::{ctype}",
                    "review_mode": "sampled", "ex": ex})

    for ex in tool_pairing_gapfill.ALL:
        out.append({"family": "tool_pairing_gapfill", "stratum": f"gapfill::{ex.tool_name}",
                    "review_mode": "sampled", "ex": ex})

    return out


def _sample_size(n: int, review_mode: str) -> int:
    if review_mode == "full":
        return n
    return min(n, max(MIN_SAMPLE, math.ceil(n * SAMPLE_FRACTION)))


def build_sample(seed: int = 42, force: bool = False) -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_FILE.exists() and not force:
        return [json.loads(l) for l in SAMPLE_FILE.open()]

    tagged = _tagged_examples()
    by_stratum: dict[str, list[dict]] = {}
    for item in tagged:
        by_stratum.setdefault(item["stratum"], []).append(item)

    rng = random.Random(seed)
    sampled_rows = []
    sid = 0
    for stratum in sorted(by_stratum):
        pop = by_stratum[stratum]
        review_mode = pop[0]["review_mode"]
        k = _sample_size(len(pop), review_mode)
        chosen = rng.sample(pop, k)
        for item in chosen:
            sid += 1
            ex = item["ex"]
            sampled_rows.append({
                "sample_id": f"S{sid:04d}",
                "family": item["family"],
                "stratum": stratum,
                "review_mode": review_mode,
                "stratum_size": len(pop),
                "stratum_sample_size": k,
                "tool_name": ex.tool_name,
                "tool_description": ex.tool_description,
                "arguments": ex.arguments,
                "context": ex.context,
                "decision": ex.decision,
                "reason": ex.reason,
                "risk_level": ex.risk_level,
                "reason_type": ex.reason_type,
                "subcategory": ex.subcategory,
            })

    with SAMPLE_FILE.open("w") as f:
        for row in sampled_rows:
            f.write(json.dumps(row) + "\n")
    if not VERDICTS_FILE.exists():
        VERDICTS_FILE.write_text("")
    return sampled_rows


def _load_verdicts() -> dict[str, dict]:
    if not VERDICTS_FILE.exists():
        return {}
    verdicts = {}
    for line in VERDICTS_FILE.open():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        verdicts[row["sample_id"]] = row  # last write wins
    return verdicts


def record_verdict(sample_id: str, verdict: str, note: str = "") -> None:
    assert verdict in ("APPROVE", "CORRECT", "REJECT")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with VERDICTS_FILE.open("a") as f:
        f.write(json.dumps({"sample_id": sample_id, "verdict": verdict, "note": note}) + "\n")


def next_batch(n: int) -> list[dict]:
    sample = build_sample()
    verdicts = _load_verdicts()
    pending = [row for row in sample if row["sample_id"] not in verdicts]
    return pending[:n]


def format_item(row: dict) -> str:
    lines = [
        f"[{row['sample_id']}] stratum={row['stratum']} (family={row['family']}, "
        f"mode={row['review_mode']}, n={row['stratum_size']}, sampled={row['stratum_sample_size']})",
        f"  tool: {row['tool_name']} -- {row['tool_description']}",
        f"  arguments: {json.dumps(row['arguments'])}",
        f"  context: {row['context']}",
        f"  LABEL: {row['decision']} (risk_level={row['risk_level']})",
        f"  reason: {row['reason']}",
    ]
    return "\n".join(lines)


def status_report() -> str:
    sample = build_sample()
    verdicts = _load_verdicts()
    by_stratum: dict[str, list[dict]] = {}
    for row in sample:
        by_stratum.setdefault(row["stratum"], []).append(row)

    lines = [f"{'stratum':45s} {'mode':>7s} {'pop':>5s} {'sampled':>7s} {'reviewed':>8s} {'errors':>6s} {'rate':>6s}  flag"]
    total_pop = total_sampled = total_reviewed = total_errors = 0
    flagged = []
    for stratum in sorted(by_stratum):
        rows = by_stratum[stratum]
        pop = rows[0]["stratum_size"]
        mode = rows[0]["review_mode"]
        sampled = len(rows)
        reviewed_rows = [verdicts[r["sample_id"]] for r in rows if r["sample_id"] in verdicts]
        reviewed = len(reviewed_rows)
        errors = sum(1 for v in reviewed_rows if v["verdict"] in ("CORRECT", "REJECT"))
        rate = (errors / reviewed) if reviewed else 0.0
        flag = ""
        if mode == "sampled" and reviewed > 0 and rate > ERROR_RATE_FLAG_THRESHOLD:
            flag = "FULL-REREVIEW"
        elif mode == "full" and reviewed > 0 and rate > ERROR_RATE_FLAG_THRESHOLD:
            flag = "HIGH-ERR(full)"
        if flag:
            flagged.append((stratum, flag))
        lines.append(f"{stratum:45s} {mode:>7s} {pop:>5d} {sampled:>7d} {reviewed:>8d} {errors:>6d} {rate:>6.1%}  {flag}")
        total_pop += pop
        total_sampled += sampled
        total_reviewed += reviewed
        total_errors += errors

    lines.append(f"{'TOTAL':45s} {'':>7s} {total_pop:>5d} {total_sampled:>7d} {total_reviewed:>8d} {total_errors:>6d} "
                  f"{(total_errors/total_reviewed if total_reviewed else 0):>6.1%}")
    if flagged:
        lines.append("")
        lines.append("FLAGGED STRATA (>5% error on sampled/full-reviewed items so far):")
        for stratum, flag in flagged:
            lines.append(f"  {stratum}: {flag}")
    pending = total_sampled - total_reviewed
    lines.append("")
    lines.append(f"Pending review: {pending}/{total_sampled} sampled items not yet verdicted.")
    return "\n".join(lines)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "build":
        rows = build_sample(force=True)
        print(f"Built sample: {len(rows)} items across "
              f"{len(set(r['stratum'] for r in rows))} strata.")
    elif cmd == "status":
        print(status_report())
    elif cmd == "batch":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
        for row in next_batch(n):
            print(format_item(row))
            print()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
