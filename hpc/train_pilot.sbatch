#!/bin/bash
# Submit from the repo root on the manager node, with conda DEACTIVATED
# (the cluster requires this — `conda deactivate` first if setup_env.sh
# left an env active in your shell):
#
#   cd ~/agentwarden-core
#   conda deactivate
#   sbatch hpc/train_pilot.sbatch                                  # pilot (64 examples)
#   TRAIN_MODULE=router_training.train_full sbatch hpc/train_pilot.sbatch   # full dataset (2,370)
#
# TRAIN_MODULE picks which script runs (default: the 64-example pilot);
# MAX_STEPS overrides that script's own default step count either way.
# Same sbatch file for both — the two scripts write to different,
# honestly-named checkpoint directories (see each script's docstring), so
# there's nothing for them to collide on.
#
# See hpc/README.md for the full procedure, including how the training
# data gets onto the cluster (data/ is gitignored — a fresh clone won't
# have it, for either script).

#SBATCH --job-name=agentwarden-pilot
#SBATCH --gpus=rtx_3090:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=03:00:00
#SBATCH --mem=24G
# --output only, no --error: Slurm then merges stderr into the same file
# as stdout. A real failure (see the --mem note below) put its traceback
# in .err while both of us kept reading .out looking for it -- merging the
# streams means the next failure's traceback is wherever we're already
# looking, not in a second file nobody checks until someone says "did you
# look at .err?"
#SBATCH --output=hpc/logs/%x-%j.out
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=sidik@post.bgu.ac.il

# --- Sizing rationale (read before changing) --------------------------------
# --time=03:00:00: covers both scripts with real margin. The pilot's
#   measured GPU rate was ~0.5s/step (40 steps in a 21s training-loop
#   window, attempt 2's jobstats). train_full.py's default of 3,555 steps
#   (3 epochs over 2,370 examples at effective batch 2) at that same rate
#   is ~30 minutes of actual training; add the one-time ~3GB
#   Qwen2.5-1.5B-Instruct HF Hub download (cached under $HOME after the
#   first run on this cluster, regardless of which script pulls it) and
#   this still has well over an hour of slack. Lower this only with a
#   measured runtime from an actual .out log for the specific script
#   you're sizing it for — train_full's real per-step rate on 2,370
#   examples hasn't been confirmed yet, only extrapolated from the pilot.
# --mem=24G: left at the cluster default. This was lowered to 8G once,
#   on the strength of a 21-SECOND smoke-test run's jobstats (1.6GB host
#   RAM used) -- too short a window to be representative, and it was
#   wrongly blamed for a later crash that was actually an unrelated bug
#   (a callback missing its TrainerCallback base class, fixed in
#   router_training/train_common.py). Don't right-size this from a smoke
#   test again: only lower it on the strength of a full, representative
#   run's jobstats (a real multi-hundred-step training run, not a
#   21-second one), and say which run's numbers justified the new value.
# --gpus=rtx_3090:1 / no --partition: if this job stays PENDING in
#   `squeue --me` for longer than expected, check `sinfo -o "%P %G"` for
#   the GPU partition's name and add `#SBATCH --partition=<name>` —
#   not set here because the exact partition name for this cluster
#   wasn't available when this file was written.
# -----------------------------------------------------------------------

set -euo pipefail

echo "Job ${SLURM_JOB_ID:-?} started on $(hostname) at $(date)"
echo "SLURM_SCRATCH_DIR=${SLURM_SCRATCH_DIR:-<unset — checkpoints will go straight to home storage>}"

module load anaconda
source activate agentwarden-pilot

cd "$SLURM_SUBMIT_DIR"

TRAIN_MODULE="${TRAIN_MODULE:-router_training.train_pilot}"

# No sbatch-level data-file check here (it used to hardcode a check for
# sample.jsonl specifically, which would have been WRONG for
# train_full.py's full_dataset.jsonl) -- both scripts already do this
# check themselves with a specific, actionable error naming the exact
# missing file, so this just runs the module and lets it report that.
if [ -n "${MAX_STEPS:-}" ]; then
    echo "Running ${TRAIN_MODULE} with max_steps=${MAX_STEPS}"
    python3 -m "$TRAIN_MODULE" "$MAX_STEPS"
else
    echo "Running ${TRAIN_MODULE} with its own default step count"
    python3 -m "$TRAIN_MODULE"
fi

echo "Job finished at $(date)"
echo "Final adapter directory is named in ${TRAIN_MODULE}'s own module docstring (on home storage)."
