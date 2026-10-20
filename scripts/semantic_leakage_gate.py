#!/usr/bin/env python3
"""Reusable leakage gate: can a label be recovered from a text field alone?

Generalizes the one-off check in scripts/context_category_leakage_check.py
(which was hardcoded to safe_but_defended vs. defensively_framed_but_unsafe,
`context` only, TF-IDF+LR only) into a reusable tool: any label field, any
text field (`context` or `arguments`), any pair of label values, plus a
semantic-embedding signal the earlier script didn't have.

Two independent signals are computed and reported side by side, not reduced
to a single number:

1. Semantic embeddings (sentence-transformers/all-MiniLM-L6-v2) -> two views:
   - Adjusted Mutual Information between unsupervised KMeans(k=2) clusters
     and the true labels (does the text's natural geometry already separate
     the labels, with no supervision at all?).
   - Nearest-centroid balanced accuracy, 5-fold stratified CV (does a trivial
     supervised classifier recover the label from the embedding?).
2. TF-IDF + logistic regression, 5-fold stratified CV, balanced accuracy —
   the same cheap lexical signal `context_category_leakage_check.py` used,
   kept here as a second, cheaper check (catches token-level/keyword leakage
   that a semantic embedding might smooth over, or vice versa).

Embedding model and why no `sentence-transformers` package:
    Checked directly: `sentence-transformers` is NOT installed in this
    environment (`pip show sentence-transformers` / import both fail).
    `torch` and `transformers` ARE installed (used elsewhere in this repo to
    train router_training's own classifier). Rather than silently falling
    back to TF-IDF alone and calling that "the embedding signal", this script
    loads sentence-transformers/all-MiniLM-L6-v2 (22.7M params, 384-dim, ~90MB)
    directly via `transformers.AutoModel` and implements that model's own
    documented pooling recipe by hand (mean-pool token embeddings over the
    attention mask, L2-normalize) — the exact computation the
    sentence-transformers package would run for this model, through a
    lower-level library already present. See `_check_deps()`: if `torch` or
    `transformers` were ALSO missing, this script stops and names them rather
    than picking a different model or method silently.

No API calls: the only network access is the one-time Hugging Face Hub
download of this model's weights on first run (cached under
~/.cache/huggingface after that — same precedent as this repo's
`router_training/train_*.py` scripts downloading Qwen2.5-1.5B). All
embedding computation runs on-device, in-process.

Pass/fail thresholds (PASS = the label is NOT recoverable from the text
alone):

- Adjusted Mutual Information < 0.10.
  AMI is already corrected for chance agreement (its expected value under
  two independent partitions is ~0, regardless of cluster-size or
  class-size imbalance — Vinh, Epps & Bailey 2010, the paper that defined
  it), so any positive AMI at or above a small threshold reflects a real
  structural association, not an artifact of the correction. 0.10 is a
  conservative floor consistent with how that paper's own experiments
  describe AMI < 0.1 as negligible correspondence and > 0.3 as a real one:
  this is an audit for ANY recoverable signal, not a tolerance band to
  thread, so the floor is set low rather than requiring a strong result
  before flagging it.
- Nearest-centroid balanced accuracy < 0.65 (chance = 0.50 regardless of
  class-size imbalance, since balanced accuracy averages per-class recall).
- TF-IDF+LR balanced accuracy < 0.65.
  0.65 reuses the exact boundary `context_category_leakage_check.py`
  already drew between "near chance" and "meaningfully above chance" for
  this same kind of check, for continuity across both scripts. 0.80 is
  still used in the verdict text as the line for "well above chance", but
  the gate's PASS/FAIL cutoff is 0.65: anything past the near-chance band
  is already a finding worth surfacing in an audit, not something to wait
  on until it becomes severe.

A category pair FAILS the gate (text leaks the label) if ANY of the three
numbers crosses its threshold. All three are always reported even when only
one crosses, so a pass/fail call is never made on a single metric alone.

Usage:
    python3 -m scripts.semantic_leakage_gate --all-pairs
    python3 -m scripts.semantic_leakage_gate --pair safe_but_defended defensively_framed_but_unsafe
    python3 -m scripts.semantic_leakage_gate --all-pairs --text-field arguments
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_DATA_PATH = Path(__file__).parent.parent / "data" / "router_training" / "full_dataset.jsonl"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

AMI_FAIL_THRESHOLD = 0.10
BAL_ACC_FAIL_THRESHOLD = 0.65
BAL_ACC_SEVERE_THRESHOLD = 0.80
MIN_ROWS_PER_CLASS = 5  # below this, 5-fold stratified CV isn't meaningful; pair is skipped and flagged


def _check_deps() -> None:
    missing = []
    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("torch")
    try:
        import transformers  # noqa: F401
    except ImportError:
        missing.append("transformers")
    try:
        import sklearn  # noqa: F401
    except ImportError:
        missing.append("scikit-learn")
    if missing:
        print(
            "ERROR: no local embedding/clustering capability installed. "
            f"Missing: {', '.join(missing)}.",
            file=sys.stderr,
        )
        print(
            "Install these (e.g. `pip install torch transformers scikit-learn`) "
            "and re-run. Not picking a substitute method silently.",
            file=sys.stderr,
        )
        sys.exit(1)


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def get_text(row: dict[str, Any], field: str) -> str:
    if field == "arguments":
        return json.dumps(row["arguments"], sort_keys=True)
    return str(row[field])


# --- embedding backend -------------------------------------------------

_tokenizer = None
_model = None


def _get_embedder():
    global _tokenizer, _model
    if _model is None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        print(
            f"Loading embedding model {EMBEDDING_MODEL} "
            "(first run downloads ~90MB from the HF Hub; cached after that)...",
            file=sys.stderr,
        )
        _tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL)
        _model = AutoModel.from_pretrained(EMBEDDING_MODEL)
        _model.eval()
    return _tokenizer, _model


def embed_texts(texts: Sequence[str], batch_size: int = 32):
    """Mean-pool token embeddings over the attention mask, L2-normalize.

    This is sentence-transformers/all-MiniLM-L6-v2's own documented pooling
    recipe, run by hand through `transformers`+`torch` directly (see module
    docstring for why: the `sentence-transformers` package itself isn't
    installed here).
    """
    import numpy as np
    import torch

    tokenizer, model = _get_embedder()
    chunks = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = list(texts[i : i + batch_size])
            enc = tokenizer(batch, padding=True, truncation=True, max_length=256, return_tensors="pt")
            out = model(**enc)
            token_embeddings = out.last_hidden_state  # (B, T, H)
            mask = enc["attention_mask"].unsqueeze(-1).float()  # (B, T, 1)
            summed = (token_embeddings * mask).sum(1)
            counts = mask.sum(1).clamp(min=1e-9)
            mean_pooled = summed / counts
            normed = torch.nn.functional.normalize(mean_pooled, p=2, dim=1)
            chunks.append(normed.cpu().numpy())
    return np.concatenate(chunks, axis=0)


# --- signal 1: embeddings -> AMI (unsupervised) + nearest-centroid (CV) -

def ami_from_clustering(X, labels) -> float:
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_mutual_info_score

    n_clusters = len(set(labels))
    km = KMeans(n_clusters=n_clusters, random_state=0, n_init=10)
    cluster_ids = km.fit_predict(X)
    return float(adjusted_mutual_info_score(labels, cluster_ids))


def nearest_centroid_cv_balanced_accuracy(X, labels) -> float:
    import numpy as np
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.model_selection import StratifiedKFold

    labels = np.asarray(labels)
    class_counts = np.bincount(labels)
    n_splits = min(5, int(class_counts.min()))
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)

    preds = np.empty_like(labels)
    for train_idx, test_idx in cv.split(X, labels):
        X_train, y_train = X[train_idx], labels[train_idx]
        centroids = {}
        for c in set(y_train):
            centroids[c] = X_train[y_train == c].mean(axis=0)
        centroid_labels = sorted(centroids)
        centroid_matrix = np.stack([centroids[c] for c in centroid_labels])
        # embeddings are L2-normalized, so dot product == cosine similarity
        sims = X[test_idx] @ centroid_matrix.T
        pred_idx = sims.argmax(axis=1)
        preds[test_idx] = np.asarray(centroid_labels)[pred_idx]
    return float(balanced_accuracy_score(labels, preds))


# --- signal 2: TF-IDF + logistic regression (cheap, lexical) -----------

def tfidf_lr_cv_balanced_accuracy(texts: Sequence[str], labels: Sequence[int]) -> float:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import Pipeline

    labels = np.asarray(labels)
    class_counts = np.bincount(labels)
    n_splits = min(5, int(class_counts.min()))

    pipe = Pipeline(
        [
            ("tfidf", TfidfVectorizer(stop_words="english", min_df=2)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)
    preds = cross_val_predict(pipe, list(texts), labels, cv=cv)
    return float(balanced_accuracy_score(labels, preds))


# --- orchestration -------------------------------------------------------

def run_pair(
    rows_by_label: dict[str, list[dict[str, Any]]],
    label_a: str,
    label_b: str,
    text_field: str,
    embedding_cache: dict[int, Any],
) -> dict[str, Any]:
    rows_a = rows_by_label[label_a]
    rows_b = rows_by_label[label_b]
    n_a, n_b = len(rows_a), len(rows_b)

    if min(n_a, n_b) < MIN_ROWS_PER_CLASS:
        return {
            "label_a": label_a,
            "label_b": label_b,
            "n_a": n_a,
            "n_b": n_b,
            "skipped": True,
            "reason": f"min class count {min(n_a, n_b)} < {MIN_ROWS_PER_CLASS}, CV not meaningful",
        }

    all_rows = rows_a + rows_b
    texts = [get_text(r, text_field) for r in all_rows]
    labels = [0] * n_a + [1] * n_b
    majority_baseline = max(n_a, n_b) / (n_a + n_b)

    ids = [id(r) for r in all_rows]
    to_embed_texts = []
    to_embed_ids = []
    for rid, text in zip(ids, texts):
        if rid not in embedding_cache:
            to_embed_ids.append(rid)
            to_embed_texts.append(text)
    if to_embed_texts:
        new_embeddings = embed_texts(to_embed_texts)
        for rid, emb in zip(to_embed_ids, new_embeddings):
            embedding_cache[rid] = emb

    import numpy as np

    X = np.stack([embedding_cache[rid] for rid in ids])

    ami = ami_from_clustering(X, labels)
    centroid_bal_acc = nearest_centroid_cv_balanced_accuracy(X, labels)
    tfidf_bal_acc = tfidf_lr_cv_balanced_accuracy(texts, labels)

    fail_reasons = []
    if ami >= AMI_FAIL_THRESHOLD:
        fail_reasons.append(f"AMI {ami:.3f} >= {AMI_FAIL_THRESHOLD}")
    if centroid_bal_acc >= BAL_ACC_FAIL_THRESHOLD:
        fail_reasons.append(f"nearest-centroid balanced accuracy {centroid_bal_acc:.3f} >= {BAL_ACC_FAIL_THRESHOLD}")
    if tfidf_bal_acc >= BAL_ACC_FAIL_THRESHOLD:
        fail_reasons.append(f"TF-IDF+LR balanced accuracy {tfidf_bal_acc:.3f} >= {BAL_ACC_FAIL_THRESHOLD}")

    verdict = "FAIL (text leaks the label)" if fail_reasons else "PASS (label not recoverable from text alone)"

    return {
        "label_a": label_a,
        "label_b": label_b,
        "n_a": n_a,
        "n_b": n_b,
        "majority_baseline": majority_baseline,
        "ami": ami,
        "centroid_balanced_accuracy": centroid_bal_acc,
        "tfidf_lr_balanced_accuracy": tfidf_bal_acc,
        "verdict": verdict,
        "fail_reasons": fail_reasons,
        "skipped": False,
    }


def print_result(result: dict[str, Any]) -> None:
    a, b = result["label_a"], result["label_b"]
    if result.get("skipped"):
        print(f"{a:35s} vs {b:35s}  SKIPPED  ({result['reason']})")
        return
    print(f"{a} (n={result['n_a']}) vs {b} (n={result['n_b']})  [majority baseline {result['majority_baseline']:.1%}]")
    print(f"    AMI (clustering):                   {result['ami']:.3f}  (fail >= {AMI_FAIL_THRESHOLD})")
    print(f"    nearest-centroid balanced accuracy:  {result['centroid_balanced_accuracy']:.3f}  (fail >= {BAL_ACC_FAIL_THRESHOLD})")
    print(f"    TF-IDF+LR balanced accuracy:         {result['tfidf_lr_balanced_accuracy']:.3f}  (fail >= {BAL_ACC_FAIL_THRESHOLD})")
    print(f"    VERDICT: {result['verdict']}")
    if result["fail_reasons"]:
        for r in result["fail_reasons"]:
            print(f"        - {r}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--label-field", default="reason_type")
    parser.add_argument("--text-field", default="context", choices=["context", "arguments"])
    parser.add_argument("--pair", nargs=2, metavar=("LABEL_A", "LABEL_B"), default=None)
    parser.add_argument("--all-pairs", action="store_true")
    parser.add_argument("--json-out", type=Path, default=None, help="optional path to write machine-readable results")
    args = parser.parse_args()

    _check_deps()

    if not args.pair and not args.all_pairs:
        parser.error("specify --pair LABEL_A LABEL_B or --all-pairs")

    rows = load_rows(args.data)
    rows_by_label: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        rows_by_label.setdefault(r[args.label_field], []).append(r)

    print(f"Loaded {len(rows)} rows from {args.data}, label field = {args.label_field!r}, text field = {args.text_field!r}")
    print("Label counts: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(rows_by_label.items(), key=lambda kv: -len(kv[1]))))
    print()

    if args.pair:
        pairs = [tuple(args.pair)]
    else:
        pairs = list(itertools.combinations(sorted(rows_by_label), 2))

    embedding_cache: dict[int, Any] = {}
    results = []
    for label_a, label_b in pairs:
        if label_a not in rows_by_label or label_b not in rows_by_label:
            print(f"SKIPPED: {label_a} vs {label_b} -- one or both labels not present in data")
            continue
        result = run_pair(rows_by_label, label_a, label_b, args.text_field, embedding_cache)
        print_result(result)
        results.append(result)

    n_fail = sum(1 for r in results if not r.get("skipped") and r["fail_reasons"])
    n_pass = sum(1 for r in results if not r.get("skipped") and not r["fail_reasons"])
    n_skip = sum(1 for r in results if r.get("skipped"))
    print(f"=== SUMMARY: {n_pass} PASS, {n_fail} FAIL, {n_skip} SKIPPED (of {len(results)} pairs checked) ===")
    if n_fail:
        print("Pairs where the label leaks from text alone:")
        for r in results:
            if not r.get("skipped") and r["fail_reasons"]:
                print(f"    {r['label_a']} vs {r['label_b']}")

    if args.json_out:
        args.json_out.write_text(json.dumps(results, indent=2))
        print(f"\nWrote machine-readable results to {args.json_out}")


if __name__ == "__main__":
    main()
