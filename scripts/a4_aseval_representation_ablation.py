#!/usr/bin/env python3
"""ASEval representation ablation (docs/v2/RECONCILED_STATE_v0.2.md
§14c): on the 233-task tool-matched subset, how much of the
literature-style monitor's 0.888 AUC (`scripts/a4_aseval_confound_demo.py`,
§14a) is carried by adversary-writable tool-response content, versus
call-derived content?

**The schema check this script's own result turns on, done FIRST, before
any measurement.** ASEval's real per-turn schema
(`data/advance/injected.json`, confirmed by reading real turns directly,
not inferred) is exactly `{user, tool_response, tool_name,
injection_in_user, injection_in_tool, injection_type}`. There is NO call-
arguments field anywhere -- `tool_name` is a bare string label with no
accompanying parameters, and `tool_response` is the only other content
field. `benchmark/a4/audit_loaders/aseval.py` already discloses this: its
`AuditRecord.arguments` is populated as `{"tool_response": <truncated>}`,
i.e. it IS the tool's response text, not real call arguments, because no
call arguments exist in this export to put there instead.

**Consequence for the three representations requested:**
1. **Full action representation** -- `action_text()`, i.e. `tool_name` +
   `{"tool_response": ...}`. This is the existing 0.888 baseline (§14a),
   recomputed here for a self-contained artifact.
2. **Tool-response text ablated -- tool name and call arguments only,
   no mocked response content.** NOT CONSTRUCTIBLE from this schema: there
   is no call-arguments content to use. The only call-derived content at
   all is the bare `tool_name` string, which is a DIFFERENT, narrower
   question than "tool name and call arguments" presupposes (that
   question is already answered by `tool_identity_scores()`,
   AUC=0.501 on this exact subset, §14a -- cited here for reference, not
   substituted as an answer to this item). Per instruction, this script
   does NOT approximate the missing arguments field (e.g. by leaving it
   empty or duplicating `tool_name`) -- it stops on this item and reports
   that the boundary this item asks for does not exist in the data.
3. **Tool-response text only, nothing else.** Constructible: `tool_name`
   dropped, leaving only whatever `arguments` holds -- which for ASEval
   is already entirely `tool_response` text. Computed via
   `content_classifier_scores(records, text_fn=response_only_text)`.

No symbolic baseline, no arms, no training beyond the same CV
TF-IDF+LR already established for this purpose.

Usage:
    python3 -m scripts.a4_aseval_representation_ablation --json-out results.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.a4.audit_loaders.aseval import load_aseval
from benchmark.a4.shortcut_audit import (
    TARGET_FAR,
    AuditRecord,
    action_text,
    content_classifier_scores,
    tool_matched_subset,
    tpr_at_far,
)


def response_only_text(record: AuditRecord) -> str:
    """`arguments` alone, `tool_name` excluded. For ASEval specifically,
    `arguments` already IS `{"tool_response": ...}` (see module
    docstring), so this is "tool-response text only, nothing else" --
    constructible because `arguments` and `tool_name` are genuinely
    separate fields in `AuditRecord`, even though `arguments` itself is
    entirely response-derived for this benchmark."""
    return json.dumps(record.arguments, sort_keys=True, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    full = load_aseval()
    subset = tool_matched_subset(full)
    print(f"Tool-matched subset: n={len(subset)}, {len({r.task_id for r in subset})} tasks\n")

    print("=== Schema check (done first; the result below turns on this) ===")
    print("  Confirmed fields per ASEval turn: {user, tool_response, tool_name, injection_in_user,")
    print("  injection_in_tool, injection_type} -- no call-arguments field exists.")
    print("  AuditRecord.arguments for ASEval == {'tool_response': <text>} (aseval.py's own stated limitation).")
    print("  => Representation 2 (tool name + call arguments, no response) is NOT constructible.\n")

    print("=== 1. Full action representation (tool_name + {'tool_response': ...}) ===")
    labels_full, scores_full = content_classifier_scores(subset, text_fn=action_text)
    r_full = tpr_at_far(labels_full, scores_full, TARGET_FAR)
    print(f"  AUC={r_full['auc']:.3f}  TPR@FAR={r_full['tpr_at_target_far']:.3f}\n")

    print("=== 2. Tool name + call arguments, no response -- SKIPPED, not constructible ===")
    print("  No call-arguments field exists in ASEval's schema for this static export (see schema check above).")
    print("  Not approximated. For reference only (a different, narrower question -- tool_identity_scores()")
    print("  already reports this on the same subset, §14a): tool-identity-alone AUC=0.501.\n")

    print("=== 3. Tool-response text only, nothing else ===")
    labels_resp, scores_resp = content_classifier_scores(subset, text_fn=response_only_text)
    r_resp = tpr_at_far(labels_resp, scores_resp, TARGET_FAR)
    print(f"  AUC={r_resp['auc']:.3f}  TPR@FAR={r_resp['tpr_at_target_far']:.3f}\n")

    print("=== How much of the full representation's AUC does response-only content carry? ===")
    print(f"  Full:          AUC={r_full['auc']:.3f}")
    print(f"  Response-only: AUC={r_resp['auc']:.3f}")
    print(f"  Difference:    {r_full['auc'] - r_resp['auc']:+.3f}")

    out = {
        "n_subset": len(subset),
        "n_subset_tasks": len({r.task_id for r in subset}),
        "schema_check": {
            "turn_fields": ["user", "tool_response", "tool_name", "injection_in_user", "injection_in_tool", "injection_type"],
            "call_arguments_field_exists": False,
        },
        "full_representation": r_full,
        "call_only_representation": "not constructible -- no call-arguments field in ASEval's schema",
        "response_only_representation": r_resp,
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(out, indent=2))
        print(f"\nWrote results to {args.json_out}")


if __name__ == "__main__":
    main()
