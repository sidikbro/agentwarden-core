#!/usr/bin/env python3
"""Leakage check for data/router_training/HELD_OUT_minimal_pair_probe.jsonl,
required by docs/v2/minimal_pair_probe_spec.md requirement (c) before the
probe is trusted for anything.

The probe's whole point is to isolate context-use: each pair shares an
identical (tool_name, arguments) and differs only in `context`, so if a
model gets both halves of a pair right, that can only be because it read
`context`. But that logic only holds if `context` doesn't leak the label
through some surface cue a model (or a trivial baseline) could pick up on
without doing any real reasoning -- a repeated keyword, a sentence
template, a tell like "always discuss the ALLOW case in more words than
the BLOCK case."

Two checks, both required by the spec, neither of which touches the real
classifier:

1. Token-skew scan (requirement (a)): for every unigram/bigram that
   appears in more than one context string, compare its rate in
   context_allow vs. context_block. A token present on one side and
   near-absent on the other is a candidate leak; this is reported, not
   silently acted on, so a human can judge whether it's a real tell (a
   stock phrase) or incidental (e.g. a tool-specific word that's fine to
   correlate with how that tool's scenarios happen to be written).

2. Context-only baseline (requirement (c)): a simple TF-IDF + logistic
   regression classifier is given ONLY the context string -- no
   tool_name, no arguments -- and scored with leave-one-out
   cross-validation (appropriate at this N=32; a single train/test split
   would be too noisy to trust either a pass or a fail). This is
   deliberately a weak, surface-level model: if even this gets
   meaningfully above chance (50% on this balanced set), the set leaks
   at the lexical level and the real probe is not valid evidence about
   context-use until the leaking items are rewritten.

Usage: python3 -m scripts.minimal_pair_leakage_check
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

PROBE_PATH = Path(__file__).parent.parent / "data" / "router_training" / "HELD_OUT_minimal_pair_probe.jsonl"


def load_probe(path: Path = PROBE_PATH) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    unigrams = set(words)
    bigrams = {f"{a} {b}" for a, b in zip(words, words[1:])}
    return unigrams | bigrams


def token_skew_scan(rows: list[dict], min_count: int = 2, skew_threshold: float = 0.8) -> list[tuple[str, int, int]]:
    """Any token whose |rate_allow - rate_block| >= skew_threshold, among
    tokens appearing at least min_count times total, is flagged."""
    allow_texts = [r["context"] for r in rows if r["decision"] == "ALLOW"]
    block_texts = [r["context"] for r in rows if r["decision"] == "BLOCK"]
    n_allow, n_block = len(allow_texts), len(block_texts)

    allow_counts: Counter[str] = Counter()
    block_counts: Counter[str] = Counter()
    for t in allow_texts:
        allow_counts.update(_tokens(t))
    for t in block_texts:
        block_counts.update(_tokens(t))

    all_tokens = set(allow_counts) | set(block_counts)
    flagged = []
    for tok in all_tokens:
        total = allow_counts[tok] + block_counts[tok]
        if total < min_count:
            continue
        rate_allow = allow_counts[tok] / n_allow
        rate_block = block_counts[tok] / n_block
        if abs(rate_allow - rate_block) >= skew_threshold:
            flagged.append((tok, allow_counts[tok], block_counts[tok]))
    return sorted(flagged, key=lambda x: -(x[1] + x[2]))


def context_only_baseline(rows: list[dict]) -> dict:
    """Leave-ONE-PAIR-out, not leave-one-row-out. Each pair's two contexts
    deliberately share heavy topical vocabulary (same tool, same scenario
    nouns -- e.g. mp_01's ALLOW/BLOCK both say "755 on deploy.sh", "signing
    log"), which is the correct design per spec requirement (b) (lexical
    surface should vary ACROSS pairs, not within one). Leave-one-ROW-out
    would leave a row's exact topical twin (its own pair partner, with the
    opposite label) in the training set on every fold, which pulls a
    topic-sensitive model like TF-IDF+LR toward that twin's cluster and
    therefore toward the WRONG label systematically -- an artifact of the
    paired design, not evidence about whether the label leaks. Holding out
    both halves of a pair together removes that artifact: every test row's
    nearest topical neighbor is excluded from training along with it."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    texts = [r["context"] for r in rows]
    labels = [1 if r["decision"] == "BLOCK" else 0 for r in rows]
    pair_ids = [r["pair_id"] for r in rows]
    unique_pairs = sorted(set(pair_ids))

    correct = 0
    predictions = [None] * len(rows)
    for held_out_pair in unique_pairs:
        train_idx = [i for i, p in enumerate(pair_ids) if p != held_out_pair]
        test_idx = [i for i, p in enumerate(pair_ids) if p == held_out_pair]

        train_texts = [texts[i] for i in train_idx]
        train_labels = [labels[i] for i in train_idx]

        vec = TfidfVectorizer(stop_words="english", min_df=1)
        X_train = vec.fit_transform(train_texts)
        X_test = vec.transform([texts[i] for i in test_idx])

        clf = LogisticRegression(max_iter=1000)
        clf.fit(X_train, train_labels)
        preds = clf.predict(X_test)
        for i, pred in zip(test_idx, preds):
            predictions[i] = pred
            correct += int(pred == labels[i])

    n = len(rows)
    accuracy = correct / n
    return {"n": n, "correct": correct, "accuracy": accuracy, "predictions": predictions, "labels": labels}


def main() -> None:
    rows = load_probe()
    n_allow = sum(1 for r in rows if r["decision"] == "ALLOW")
    n_block = sum(1 for r in rows if r["decision"] == "BLOCK")
    print(f"Loaded {len(rows)} rows ({n_allow} ALLOW / {n_block} BLOCK) from {PROBE_PATH.name}")
    print()

    print("=== Token-skew scan (requirement (a)) ===")
    flagged = token_skew_scan(rows)
    if not flagged:
        print("No token (unigram or bigram, appearing >=2 times) is skewed >=0.8 between ALLOW and BLOCK contexts.")
    else:
        print(f"{len(flagged)} token(s) flagged (skew >= 0.8, min count 2):")
        for tok, a, b in flagged:
            print(f"  {tok!r:30s} allow={a:2d} block={b:2d}")
    print()

    print("=== Context-only baseline (requirement (c)) ===")
    result = context_only_baseline(rows)
    acc = result["accuracy"]
    print(f"Leave-one-PAIR-out cross-validated accuracy, context string ONLY (no tool_name/arguments): "
          f"{result['correct']}/{result['n']} = {acc:.1%}")
    print(f"Chance on this balanced set: 50.0%")
    print()
    if acc >= 0.70:
        print("VERDICT: meaningfully above chance. The probe set leaks the label through the")
        print("context string's surface form and is NOT valid as-is -- per the spec, report this")
        print("and stop. Do not run the real probe (Stage 2) against these items until the")
        print("leaking pairs are identified (see the token-skew scan above) and rewritten.")
    elif acc >= 0.60:
        print("VERDICT: borderline. Not a clean pass -- some leakage signal above noise at this N.")
        print("Treat Stage 2 results from this set as suggestive, not conclusive, until rewritten.")
    else:
        print("VERDICT: near chance. No strong evidence of lexical leakage at this N;")
        print("proceeding to Stage 2 is licensed by this check.")


if __name__ == "__main__":
    main()
