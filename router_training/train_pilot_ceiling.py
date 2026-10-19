"""D2 classifier CEILING EXPERIMENT -- NOT a candidate serving
configuration. Read this before touching anything downstream of it.

*** WHAT THIS IS ***

docs/v2/RECONCILED_STATE_v0.2.md §11b's gate 3a (defensively-framed-but-
unsafe, zero-tolerance BLOCK) was unmoved by a 37x increase in training
volume on the full-dataset run. Investigation found that the one field
carrying the signal gate 3a actually needs -- `TrainingExample.context`,
e.g. "No prior step established anything about this PID; no hash match,
no SOC alert, no monitoring correlation cited." -- is written by every
generator and then silently dropped before the model ever sees it, in
both training (to_training_pair) and serving (build_classify_prompt).

This script answers one narrow question: if the model COULD see that
field, does gate 3a move at all? It trains on the same 64-example pilot
set (data/router_training/sample.jsonl) as train_pilot.py, with the exact
same hyperparameters, differing only in `include_context=True` --
build_classify_prompt() gets the real `context` string for every example.

*** WHY THIS IS A CEILING, NOT A DESIGN ***

The `context` string in sample.jsonl is authored by whoever wrote the
dataset, asserting ground truth ("no prior step verified X") directly.
That's a trusted provenance oracle: this experiment assumes the model is
simply HANDED the fact of whether a defensive claim was verified, with no
question of where that fact comes from or whether it can be trusted.
Production has no such oracle -- see docs/v2/provenance_representation.md
for why a verification-history field may only ever be populated from this
system's OWN audit log of prior decisions, never from tool output or
model-generated text (both attacker-controlled). If this experiment moves
gate 3a, it tells you the model CAN use that signal once given it; it
tells you NOTHING about how to produce a trustworthy version of that
signal at serving time, which is a separate, harder, not-yet-designed
problem. Do not read a good result here as "ship context in the prompt."

Checkpoint lands at PILOT_CEILING_WITH_CONTEXT_checkpoint -- deliberately
not reusing PILOT_UNREVIEWED_DATA_checkpoint's name or directory, so the
two can never be confused or silently overwrite each other.

Usage: python3 -m router_training.train_pilot_ceiling [max_steps]
"""
from __future__ import annotations

import sys
from pathlib import Path

from router_training.train_common import run_training

DATA_PATH = Path(__file__).parent.parent / "data" / "router_training" / "sample.jsonl"
OUT_DIR = Path(__file__).parent.parent / "data" / "router_training" / "PILOT_CEILING_WITH_CONTEXT_checkpoint"

_MISSING_DATA_HINT = (
    "Transfer it from your dev machine first: see hpc/README.md\n"
    "'Transfer training data' step (scp sample.jsonl + sample_manifest.json)."
)


def _banner(device: str, train_out_dir: Path, out_dir: Path) -> str:
    return f"""
################################################################################
# CEILING EXPERIMENT -- NOT A CANDIDATE SERVING CONFIGURATION.
#   Trained with include_context=True: the model sees the dataset's
#   authored `context` string (a trusted provenance oracle) on every
#   example. Read the module docstring before using this checkpoint for
#   anything beyond answering "does gate 3a move if the model can see
#   context at all." See docs/v2/provenance_representation.md.
#   device: {device}
#   checkpoint dir (frequent saves): {train_out_dir}
#   final artifacts always land in: {out_dir}
################################################################################
"""


def main() -> None:
    max_steps = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    run_training(
        data_path=DATA_PATH,
        out_dir=OUT_DIR,
        scratch_subdir="agentwarden_pilot_ceiling_checkpoint",
        max_steps=max_steps,
        save_steps=10,
        logging_steps=5,
        banner_fn=_banner,
        missing_data_hint=_MISSING_DATA_HINT,
        include_context=True,
    )


if __name__ == "__main__":
    main()
