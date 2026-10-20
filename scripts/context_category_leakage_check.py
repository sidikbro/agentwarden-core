#!/usr/bin/env python3
"""Decisive leakage test on the ORIGINAL dataset's gate-3 / gate-3a
categories, prompted by the ceiling experiment's all-5-gates-pass result
(docs/v2/RECONCILED_STATE_v0.2.md SS11b) and the minimal-pair probe's own
leakage finding (docs/v2/minimal_pair_probe_spec.md) -- both point at the
same mechanism, and this test checks it directly on the real training
rows rather than on 16 hand-authored pairs.

Question: can `context` alone (no tool_name, no arguments) predict which
of the two categories a row belongs to -- safe_but_defended (ALLOW) vs.
defensively_framed_but_unsafe (BLOCK) -- using nothing but surface
lexical register (TF-IDF + logistic regression, the same crude setup as
scripts/minimal_pair_leakage_check.py's context-only baseline)?

If yes, well above the MAJORITY-CLASS baseline (not 50% -- these two
categories are 652 vs. 106 rows, so always predicting safe_but_defended
already scores ~86%), that's a direct demonstration that the ceiling
experiment's gate-3a pass is explained by the two categories' context
strings having a different lexical register, not by the model exercising
provenance judgment -- the same register a human author's writing habits
would produce when drafting 652 "this was fine" scenarios vs. 106 "this
wasn't" scenarios, without either author ever composing a genuine
minimal pair.

Usage: python3 -m scripts.context_category_leakage_check
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "router_training" / "full_dataset.jsonl"


def load_rows() -> list[dict]:
    rows = []
    with DATA_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            if r["reason_type"] in ("safe_but_defended", "defensively_framed_but_unsafe"):
                rows.append(r)
    return rows


def main() -> None:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import balanced_accuracy_score, f1_score, confusion_matrix

    rows = load_rows()
    texts = [r["context"] for r in rows]
    labels = [1 if r["reason_type"] == "defensively_framed_but_unsafe" else 0 for r in rows]  # 1=dfu, 0=sbd
    n = len(rows)
    n_dfu = sum(labels)
    n_sbd = n - n_dfu
    majority_baseline = max(n_dfu, n_sbd) / n

    print(f"Loaded {n} rows: {n_sbd} safe_but_defended (label 0) / {n_dfu} defensively_framed_but_unsafe (label 1)")
    print(f"Majority-class baseline accuracy (always predict the larger class): {majority_baseline:.1%}")
    print("Plain accuracy is misleading here given this imbalance -- reporting balanced accuracy and F1 too.")
    print()

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(stop_words="english", min_df=2)),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    preds = cross_val_predict(pipe, texts, labels, cv=cv)

    accuracy = sum(p == y for p, y in zip(preds, labels)) / n
    bal_acc = balanced_accuracy_score(labels, preds)
    f1_dfu = f1_score(labels, preds, pos_label=1)
    cm = confusion_matrix(labels, preds)

    print("=== 5-fold stratified cross-validated results, context string ONLY ===")
    print(f"Plain accuracy:            {accuracy:.1%}  (majority baseline: {majority_baseline:.1%})")
    print(f"Balanced accuracy:         {bal_acc:.1%}  (chance under class_weight='balanced': 50.0%)")
    print(f"F1 (defensively_framed_but_unsafe as positive class): {f1_dfu:.3f}")
    print(f"Confusion matrix [rows=true sbd/dfu, cols=pred sbd/dfu]:\n{cm}")
    print()

    if bal_acc >= 0.80:
        print("VERDICT: context alone separates the two categories well above chance (balanced accuracy).")
        print("This is the explanation, not a caveat, for the ceiling experiment's gate-3a pass: the two")
        print("categories' context strings differ enough in lexical register that a crude bag-of-words")
        print("classifier recovers the category from register alone. A model shown context during training")
        print("has every opportunity to learn the same shortcut instead of provenance judgment.")
    elif bal_acc >= 0.65:
        print("VERDICT: meaningfully above chance but not overwhelming. Register leakage is present and")
        print("material, but not so dominant that it's the only explanation available.")
    else:
        print("VERDICT: near chance by balanced accuracy. Register leakage does not explain the gate-3a")
        print("result; look elsewhere for the mechanism.")


if __name__ == "__main__":
    main()
