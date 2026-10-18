"""D2 classifier PILOT fine-tune — proves the training pipeline mechanics
work end to end, per the "Track B (D2 classifier pilot)" instruction in
docs/v2/EXPERIMENTAL_PLAN_v0.2.md. This is explicitly NOT a citable model.

*** READ THIS BEFORE USING ANYTHING THIS SCRIPT PRODUCES ***

One standing gate this script deliberately does NOT satisfy, and must
not be read as having satisfied:

docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md §2's authorship/review protocol
requires 100% human review of hand-authored examples before they are
training-eligible. The only data this script trains on is
data/router_training/sample.jsonl (64 examples), and per
docs/v2/RECONCILED_STATE_v0.2.md §8, that sample is explicitly PENDING
human review -- "do not touch it until reviewed." This script trains on
it anyway, because "pilot" here means proving the MECHANICS (data
loading, tokenization, LoRA config, training loop, checkpoint save, a
degeneracy smoke test) run correctly end to end -- not producing a model
whose weights mean anything. The resulting checkpoint is written to a
directory named PILOT_UNREVIEWED_DATA specifically so it can never be
mistaken for a real result, and this script prints a loud warning banner
every time it runs.

The full-dataset run (2,370 reviewed-per-protocol examples, see
docs/v2/RECONCILED_STATE_v0.2.md §11b) is a separate script --
router_training/train_full.py -- not a bigger argument to this one, so
the two checkpoints can never be confused with each other on disk.
Shared training mechanics (CUDA verification, checkpoint mirroring, the
training loop itself) live in router_training/train_common.py so the two
scripts can't silently drift the way train/serve prompt formatting
already did once.

Runs on either a memory-constrained CPU-only dev box or a Slurm/GPU
cluster node without code changes -- see hpc/README.md for the cluster
procedure. Device and checkpoint-storage behavior are both detected at
runtime, not hardcoded to one environment -- see train_common.py's
docstrings for the CUDA-detection and scratch-mirroring rationale.

Usage: python3 -m router_training.train_pilot [max_steps]
"""
from __future__ import annotations

import sys
from pathlib import Path

from router_training.train_common import run_training

DATA_PATH = Path(__file__).parent.parent / "data" / "router_training" / "sample.jsonl"

# Final artifacts ALWAYS land here -- home storage, persistent, whether
# this runs locally or on the cluster. See hpc/README.md's "data problem"
# section for how sample.jsonl gets here on a fresh cluster clone (scp,
# not on-cluster regeneration -- regeneration would produce a DIFFERENT,
# unreviewed dataset each time, since paraphrase generation is
# non-deterministic; see router_training/paraphrase_generation.py).
OUT_DIR = Path(__file__).parent.parent / "data" / "router_training" / "PILOT_UNREVIEWED_DATA_checkpoint"

_MISSING_DATA_HINT = (
    "Transfer it from your dev machine first: see hpc/README.md\n"
    "'Transfer training data' step (scp sample.jsonl + sample_manifest.json)."
)


def _banner(device: str, train_out_dir: Path, out_dir: Path) -> str:
    return f"""
################################################################################
# PILOT RUN -- NOT A CITABLE MODEL. READ THE MODULE DOCSTRING.
#   1. Training data (data/router_training/sample.jsonl) is UNREVIEWED --
#      review_status=pending per docs/v2/RECONCILED_STATE_v0.2.md §8.
#   2. device: {device}
#   3. checkpoint dir (frequent saves): {train_out_dir}
#      final artifacts always land in: {out_dir}
# This proves the pipeline runs. It proves nothing about classifier quality.
################################################################################
"""


def main() -> None:
    max_steps = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    run_training(
        data_path=DATA_PATH,
        out_dir=OUT_DIR,
        scratch_subdir="agentwarden_pilot_checkpoint",
        max_steps=max_steps,
        save_steps=10,
        logging_steps=5,
        banner_fn=_banner,
        missing_data_hint=_MISSING_DATA_HINT,
    )


if __name__ == "__main__":
    main()
