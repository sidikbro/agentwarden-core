#!/usr/bin/env python3
"""Reusable shortcut-audit harness, across every benchmark obtainable
without credentials, not just STAC/AgentDojo. For each benchmark, reports:

1. **Tool-identity-alone separability** -- out-of-fold AUC and TPR at a
   fixed FAR (0.12, this project's reference point), from a 5-fold
   stratified CV logistic regression over one-hot(tool_name) ONLY (no
   position feature this time -- `benchmark/a4/arms.py::arm0_scores`'s
   position feature turned out to contribute almost nothing on STAC, §13a,
   and "position in the sequence" is not even a comparable concept across
   benchmarks with very different session structures; this audit asks the
   narrower, portable question "does tool identity alone leak the label,"
   not arm 0's full definition).
2. **Action-content leakage** -- `scripts/semantic_leakage_gate.py`'s
   existing AMI / nearest-centroid / TF-IDF+LR signals and thresholds, on
   the serialized `(tool_name, arguments)` action -- the exact same
   question gate 3 (§9) already asked of STAC and AgentDojo, asked here of
   every other benchmark too, with the same thresholds, reused directly
   rather than re-derived.
3. **Whether a tool-matched negative exists** -- within the same task/
   session, does the identical tool name appear in both a labeled-benign
   and a labeled-attack action? If so, how many of the benchmark's tasks
   support that match (the same question `build_stac_matched_s0_pairs` /
   `build_agentdojo_matched_s0_pairs` already answered for STAC/AgentDojo,
   generalized to any benchmark that reports this shape of data).

Nothing past that: no baseline, no arms, no training. This harness takes a
list of `AuditRecord`s and reports on them; it does not decide what counts
as benign/attack for a given benchmark -- each benchmark's loader
(`benchmark/a4/audit_loaders/*.py`) makes and states that call explicitly,
since (per instruction) the audit's credibility rests on that definition
being stated, not assumed. A loader that cannot obtain its benchmark
without credentials or without live execution raises
`BenchmarkNotObtainedError` with the reason, rather than approximating.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

MIN_ROWS_PER_CLASS = 5  # same floor scripts/semantic_leakage_gate.py uses; CV below it isn't meaningful
TARGET_FAR = 0.12  # docs/v2/A4_MULTITURN_SPEC_v0.2.md §10's reference point


class BenchmarkNotObtainedError(Exception):
    """Raised by a loader when its benchmark is gated (credentials,
    terms-of-use form) or requires live execution with no static
    trajectory to extract actions from. Carries the reason as its message
    -- callers report this and move on, per instruction, rather than
    approximating a substitute."""


@dataclass(frozen=True)
class AuditRecord:
    """One labeled action. `task_id` groups records into the same
    session/task for the tool-matched-negative check -- two records with
    the same `task_id` are "the same session," however that benchmark
    defines a session; two records from different, independent sessions
    must never share a `task_id` even if coincidentally similar."""

    benchmark: str
    task_id: str
    tool_name: str
    arguments: dict[str, Any]
    label: str  # "benign" or "attack" -- nothing else

    def __post_init__(self) -> None:
        if self.label not in ("benign", "attack"):
            raise ValueError(f"label must be 'benign' or 'attack', got {self.label!r}")


def action_text(record: AuditRecord) -> str:
    """Serialized (tool_name, arguments) -- the same action-content shape
    `agentwarden/core/decision_input.py::call_only_json` uses for gate 3,
    kept consistent so this audit's leakage numbers are directly
    comparable to STAC/AgentDojo's existing gate-3 numbers."""
    return json.dumps({"tool_name": record.tool_name, "arguments": record.arguments}, sort_keys=True, ensure_ascii=False)


def tool_identity_scores(records: list[AuditRecord]) -> tuple[list[int], list[float]]:
    """Out-of-fold P(attack) from a 5-fold stratified CV logistic
    regression over one-hot(tool_name) alone. Returns (labels, scores) in
    the same order as `records`."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    labels = [1 if r.label == "attack" else 0 for r in records]
    tool_names = sorted({r.tool_name for r in records})
    tool_index = {name: i for i, name in enumerate(tool_names)}

    X = np.zeros((len(records), max(len(tool_names), 1)))
    for i, r in enumerate(records):
        X[i, tool_index[r.tool_name]] = 1.0

    y = np.asarray(labels)
    class_counts = np.bincount(y, minlength=2)
    n_splits = min(5, int(class_counts.min()))
    if n_splits < 2:
        raise ValueError(f"not enough rows per class for CV: {class_counts}")
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)
    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    proba = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")
    scores = proba[:, 1]
    return labels, [float(s) for s in scores]


def content_classifier_scores(
    records: list[AuditRecord],
    text_fn: Callable[[AuditRecord], str] = action_text,
) -> tuple[list[int], list[float]]:
    """Out-of-fold P(attack) from a 5-fold stratified CV TF-IDF + logistic
    regression over `text_fn(record)` -- `action_text()` (the FULL
    serialized action: `tool_name` + `arguments`) by default, not tool
    identity alone. This is "a monitor fit the way the literature does":
    a discriminative classifier trained directly on the full action
    representation, exactly the construction `scripts/
    semantic_leakage_gate.py::tfidf_lr_cv_balanced_accuracy` already uses
    for gate 3's balanced-accuracy number, reused here to get a
    continuous score instead (`method="predict_proba"`) so
    `tpr_at_far()` can report AUC/TPR at a fixed FAR the same way
    `tool_identity_scores()`'s output does. Note the default `action_text()`
    includes `tool_name` as a token among others -- this classifier is not
    forbidden from using tool identity, it is simply not restricted to
    it, which is exactly the point: a real-world "fit a monitor on the
    full action" approach would include tool identity as one signal among
    many, so if it collapses the same way `tool_identity_scores()` does on
    a tool-matched subset, that is evidence the tool-identity shortcut
    survives inside ordinary full-content training too, not just in the
    deliberately narrow arm-0 construction. `text_fn` is overridable (see
    `scripts/a4_aseval_representation_ablation.py`) for representation
    ablations that need a different serialization than the default full
    action -- e.g. response-content-only, with `tool_name` excluded."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import Pipeline

    labels = [1 if r.label == "attack" else 0 for r in records]
    texts = [text_fn(r) for r in records]

    y = np.asarray(labels)
    class_counts = np.bincount(y, minlength=2)
    n_splits = min(5, int(class_counts.min()))
    if n_splits < 2:
        raise ValueError(f"not enough rows per class for CV: {class_counts}")
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)
    pipe = Pipeline(
        [
            ("tfidf", TfidfVectorizer(stop_words="english", min_df=2)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )
    proba = cross_val_predict(pipe, texts, y, cv=cv, method="predict_proba")
    scores = proba[:, 1]
    return labels, [float(s) for s in scores]


def tpr_at_far(labels: list[int], scores: list[float], target_far: float) -> dict[str, float]:
    import numpy as np
    from sklearn.metrics import roc_auc_score, roc_curve

    y = np.asarray(labels)
    s = np.asarray(scores)
    fpr, tpr, _ = roc_curve(y, s)
    tpr_at_target = float(np.interp(target_far, fpr, tpr))
    auc = float(roc_auc_score(y, s)) if len(set(labels)) > 1 else float("nan")
    return {"tpr_at_target_far": tpr_at_target, "auc": auc}


def content_leakage_gate(records: list[AuditRecord]) -> dict[str, Any]:
    """Gate 3's exact signals/thresholds (`scripts/semantic_leakage_gate.py`
    reused directly), on `action_text()` -- benign vs. attack."""
    from scripts.semantic_leakage_gate import run_pair

    rows_by_label = {"BENIGN": [], "ATTACK": []}
    for r in records:
        key = "ATTACK" if r.label == "attack" else "BENIGN"
        rows_by_label[key].append({"text": action_text(r)})
    return run_pair(rows_by_label, "BENIGN", "ATTACK", text_field="text", embedding_cache={})


def tool_matched_negative_fraction(records: list[AuditRecord]) -> dict[str, Any]:
    """Of the distinct task_ids with at least one benign and one attack
    record, how many have the identical tool name appear in both?"""
    by_task: dict[str, dict[str, set[str]]] = {}
    for r in records:
        slot = by_task.setdefault(r.task_id, {"benign": set(), "attack": set()})
        slot[r.label].add(r.tool_name)  # r.label is "benign" or "attack", enforced by AuditRecord.__post_init__

    eligible = 0
    matched = 0
    for tools in by_task.values():
        if not tools["benign"] or not tools["attack"]:
            continue
        eligible += 1
        if tools["benign"] & tools["attack"]:
            matched += 1
    return {"n_tasks_total": len(by_task), "n_tasks_eligible": eligible, "n_tasks_matched": matched}


def tool_matched_subset(records: list[AuditRecord]) -> list[AuditRecord]:
    """The confound-controlled subset: records belonging to a tool-matched
    task (`tool_matched_negative_fraction`'s "matched" tasks), restricted
    further to only the actions whose tool name is one of the SHARED
    tools for that task (present on both the benign and attack side).
    Tool identity cannot trivially separate benign/attack within this
    subset by construction -- every tool name included appears on both
    labels somewhere in its own task. Mirrors the discipline
    `benchmark/a4/s0_inputs.py::build_stac_matched_s0_pairs` already
    applied to STAC specifically (restrict to the literally-reused tool),
    generalized to any benchmark/task structure.

    Does NOT itself guarantee the subset's attack/benign balance matches
    the full set's -- callers must check that separately (a balance shift
    would confound a before/after comparison on this subset)."""
    by_task: dict[str, dict[str, set[str]]] = {}
    for r in records:
        slot = by_task.setdefault(r.task_id, {"benign": set(), "attack": set()})
        slot[r.label].add(r.tool_name)

    shared_tools_by_task: dict[str, set[str]] = {}
    for task_id, tools in by_task.items():
        shared = tools["benign"] & tools["attack"]
        if shared:
            shared_tools_by_task[task_id] = shared

    return [r for r in records if r.task_id in shared_tools_by_task and r.tool_name in shared_tools_by_task[r.task_id]]


def run_audit(benchmark: str, records: list[AuditRecord]) -> dict[str, Any]:
    labels_all = [r.label for r in records]
    n_benign = labels_all.count("benign")
    n_attack = labels_all.count("attack")

    result: dict[str, Any] = {
        "benchmark": benchmark,
        "n": len(records),
        "n_benign": n_benign,
        "n_attack": n_attack,
    }

    if min(n_benign, n_attack) < MIN_ROWS_PER_CLASS:
        result["skipped"] = True
        result["reason"] = f"min class count {min(n_benign, n_attack)} < {MIN_ROWS_PER_CLASS}, CV not meaningful"
        return result

    labels, scores = tool_identity_scores(records)
    tool_identity = tpr_at_far(labels, scores, TARGET_FAR)
    result["tool_identity_auc"] = tool_identity["auc"]
    result["tool_identity_tpr_at_far"] = tool_identity["tpr_at_target_far"]

    result["content_leakage"] = content_leakage_gate(records)
    result["tool_matched_negative"] = tool_matched_negative_fraction(records)

    return result


def print_table(results: list[dict[str, Any]]) -> None:
    header = f"{'benchmark':<28} {'n':>6} {'tool-id AUC':>11} {'TPR@FAR=.12':>11} {'content gate':>14} {'tool-matched':>13}"
    print(header)
    print("-" * len(header))
    for r in results:
        if r.get("skipped"):
            print(f"{r['benchmark']:<28} {r['n']:>6}   SKIPPED ({r['reason']})")
            continue
        gate = r["content_leakage"]
        gate_verdict = "FAIL" if gate.get("fail_reasons") else "PASS"
        tm = r["tool_matched_negative"]
        tm_str = f"{tm['n_tasks_matched']}/{tm['n_tasks_eligible']}"
        print(
            f"{r['benchmark']:<28} {r['n']:>6} {r['tool_identity_auc']:>11.3f} "
            f"{r['tool_identity_tpr_at_far']:>11.3f} {gate_verdict:>14} {tm_str:>13}"
        )


# -- loader registry -------------------------------------------------------
# Each entry: name -> (loader_fn, note). loader_fn() -> list[AuditRecord],
# or raises BenchmarkNotObtainedError. Registered lazily (imported inside
# the function) so one missing optional dependency doesn't break every
# other benchmark's loader.

LoaderFn = Callable[[], list[AuditRecord]]


def _registry() -> dict[str, LoaderFn]:
    from .audit_loaders import REGISTRY

    return REGISTRY


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=None, help="restrict to these benchmark names")
    parser.add_argument("--json-out", type=__import__("pathlib").Path, default=None)
    args = parser.parse_args()

    registry = _registry()
    names = args.only if args.only else sorted(registry)

    results = []
    not_obtained = []
    for name in names:
        if name not in registry:
            print(f"SKIPPED: no loader registered for {name!r}")
            continue
        loader = registry[name]
        print(f"=== {name} ===")
        try:
            records = loader()
        except BenchmarkNotObtainedError as e:
            print(f"    NOT OBTAINED: {e}\n")
            not_obtained.append({"benchmark": name, "reason": str(e)})
            continue
        result = run_audit(name, records)
        results.append(result)
        if result.get("skipped"):
            print(f"    SKIPPED: {result['reason']}\n")
        else:
            print(
                f"    n={result['n']} tool-id AUC={result['tool_identity_auc']:.3f} "
                f"TPR@FAR={result['tool_identity_tpr_at_far']:.3f} "
                f"content-gate={'FAIL' if result['content_leakage'].get('fail_reasons') else 'PASS'} "
                f"tool-matched={result['tool_matched_negative']['n_tasks_matched']}/"
                f"{result['tool_matched_negative']['n_tasks_eligible']}\n"
            )

    print("\n=== FINAL TABLE ===")
    print_table(results)

    if not_obtained:
        print("\n=== NOT OBTAINED (gated or live-execution-only) ===")
        for item in not_obtained:
            print(f"    {item['benchmark']}: {item['reason']}")

    if args.json_out:
        import json as _json

        args.json_out.write_text(_json.dumps({"results": results, "not_obtained": not_obtained}, indent=2))
        print(f"\nWrote results to {args.json_out}")


if __name__ == "__main__":
    main()
