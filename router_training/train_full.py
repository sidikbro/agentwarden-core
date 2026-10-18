"""D2 classifier fine-tune on the FULL dataset (2,370 examples, per
docs/v2/ROUTER_RETRAINING_PLAN_v0.1.md's §2 budget and
router_training/build_dataset_full.py). Separate script from
router_training/train_pilot.py -- not a bigger argument to it -- so the
64-example smoke-test checkpoint and this one can never be confused with
each other on disk or in a log. Shared mechanics live in
router_training/train_common.py.

*** READ THIS BEFORE USING ANYTHING THIS SCRIPT PRODUCES ***

This is the first training run on real volume, following the pilot's
degeneracy smoke test (scripts/classifier_canary_check.py), which found
real per-input discrimination but failed gate 3 (safe-but-defended ALLOW
rate 12.5% against a >=50% floor) and gate 3a (3/7 defensive-unsafe
misses) at 40 steps on 64 examples. This run is NOT pre-validated as
fixing that -- re-running the canary check against ITS checkpoint is the
next step after this script finishes, not assumed here.

Review status of this dataset, precisely (see
docs/v2/RECONCILED_STATE_v0.2.md §11b for the full account, and
ROUTER_RETRAINING_PLAN_v0.1.md's 2026-10-17 amendment for the protocol
this follows): 231 of 2,370 rows carry review_status=approved (the ones a
human reviewer actually inspected -- 46 individually-authored examples at
100%, plus a stratified sample of the parametrically-generated majority).
The rest are review_status=pending, individually unreviewed, but their
strata are cleared for use because the reviewed sample from each came
back at 0% error -- per the amendment, that's a stratum-level clearance,
not a claim that every single row was looked at. This is a materially
different (and better-founded) status than the pilot's "touch nothing,
100% unreviewed" -- but it is still not the "100% reviewed" bar the
original protocol set for hand-authored data before the amendment, so the
checkpoint directory name reflects that honestly rather than either
extreme.

Epochs/steps: the pilot used max_steps=40 on 64 examples (~1.25 epochs of
a smoke test, not a sizing decision). This default targets 3 full epochs
over 2,370 examples at the same effective batch size (2, via
per_device_train_batch_size=1 x gradient_accumulation_steps=2):
3 * ceil(2370 / 2) = 3,555 steps. Override with an explicit argument if a
different epoch count is wanted -- this is a reasoned default, not a
constraint.

Usage: python3 -m router_training.train_full [max_steps]
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from router_training.train_common import run_training

DATA_PATH = Path(__file__).parent.parent / "data" / "router_training" / "full_dataset.jsonl"

# Deliberately NOT "PILOT_UNREVIEWED_DATA" (this isn't unreviewed -- see
# module docstring) and NOT unqualified "REVIEWED" (most rows are
# individually pending, cleared at the stratum level, not inspected one
# by one). Named for exactly what it is.
OUT_DIR = Path(__file__).parent.parent / "data" / "router_training" / "FULL_DATASET_v1_checkpoint"

_EFFECTIVE_BATCH = 2  # per_device_train_batch_size=1 * gradient_accumulation_steps=2, see train_common.py
_DEFAULT_EPOCHS = 3

_MISSING_DATA_HINT = (
    "Transfer it from your dev machine first (data/ is gitignored, same as\n"
    "sample.jsonl): scp data/router_training/{full_dataset.jsonl,full_dataset_manifest.json}\n"
    "to this machine's data/router_training/ -- see hpc/README.md."
)


def _banner(device: str, train_out_dir: Path, out_dir: Path) -> str:
    return f"""
################################################################################
# FULL-DATASET RUN -- read the module docstring before citing anything here.
#   1. Training data: data/router_training/full_dataset.jsonl (2,370 target).
#      231/2,370 rows review_status=approved (individually inspected);
#      the rest are review_status=pending, cleared at the STRATUM level by
#      a 0%-error stratified sample -- see RECONCILED_STATE_v0.2.md §11b.
#   2. device: {device}
#   3. checkpoint dir (frequent saves): {train_out_dir}
#      final artifacts always land in: {out_dir}
#   4. Next required step after this finishes: re-run
#      scripts/classifier_canary_check.py against this checkpoint and
#      compare gate 3 (safe-but-defended ALLOW rate) and gate 3a against
#      the pilot's 12.5% / 3-of-7-missed baseline. Not assumed fixed here.
################################################################################
"""


def _default_max_steps() -> int:
    if not DATA_PATH.exists():
        return _DEFAULT_EPOCHS * 1  # irrelevant -- run_training will hit the missing-data FATAL path first
    n = sum(1 for _ in DATA_PATH.open())
    steps_per_epoch = math.ceil(n / _EFFECTIVE_BATCH)
    return _DEFAULT_EPOCHS * steps_per_epoch


def main() -> None:
    max_steps = int(sys.argv[1]) if len(sys.argv) > 1 else _default_max_steps()
    run_training(
        data_path=DATA_PATH,
        out_dir=OUT_DIR,
        scratch_subdir="agentwarden_full_checkpoint",
        max_steps=max_steps,
        save_steps=100,
        logging_steps=25,
        banner_fn=_banner,
        missing_data_hint=_MISSING_DATA_HINT,
    )


if __name__ == "__main__":
    main()
