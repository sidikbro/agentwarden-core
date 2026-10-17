#!/bin/bash
# Submit from the repo root on the manager node, with conda DEACTIVATED
# (the cluster requires this — `conda deactivate` first if setup_env.sh
# left an env active in your shell):
#
#   cd ~/agentwarden-core
#   conda deactivate
#   sbatch hpc/train_pilot.sbatch
#
# See hpc/README.md for the full procedure, including how sample.jsonl
# gets onto the cluster (it's gitignored — a fresh clone won't have it).

#SBATCH --job-name=agentwarden-pilot
#SBATCH --gpus=rtx_3090:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=03:00:00
#SBATCH --mem=8G
#SBATCH --output=hpc/logs/%x-%j.out
#SBATCH --error=hpc/logs/%x-%j.err
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=sidik@post.bgu.ac.il

# --- Sizing rationale (read before changing) --------------------------------
# --time=01:00:00: conservative for a FIRST run of unknown network speed.
#   The uncertain cost is the ~3GB Qwen2.5-1.5B-Instruct download from
#   the HF Hub on first run (cached under $HOME after that — HF's
#   default cache dir is on home storage, which persists across jobs).
#   Training itself (max_steps=40, LoRA, batch=1) should take well under
#   10 minutes on an RTX 3090: the CPU-only local dev run did 40 steps
#   at 35-75s/step with no GPU acceleration at all, so a real GPU should
#   be at least an order of magnitude faster per step. Lower this once
#   you've seen an actual runtime in the .out log.
# --mem=8G: lowered from the cluster's 24G default after attempt 1's
#   jobstats showed actual RAM use of only 1.6GB (of the requested 24G) --
#   this is HOST (CPU-side) memory, separate from the 4.4GB GPU memory the
#   same job used, which --gpus=rtx_3090:1 governs on its own and is not
#   affected by this setting. 8G keeps a real margin over the measured
#   1.6GB (dataloader workers, HF Hub download buffering on a cold cache,
#   etc.) without holding 24G of a shared resource idle for a job that
#   doesn't need it. Raise this again, with the same kind of measured
#   justification, only if a future run (bigger batch/dataset/rank)
#   actually needs more.
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

if [ ! -f data/router_training/sample.jsonl ]; then
    echo "FATAL: data/router_training/sample.jsonl is missing." >&2
    echo "This is expected on a fresh clone (data/ is gitignored)." >&2
    echo "See hpc/README.md 'Transfer training data' — scp it from your dev machine first." >&2
    exit 1
fi

MAX_STEPS="${MAX_STEPS:-40}"
echo "Running train_pilot.py with max_steps=${MAX_STEPS}"

python3 -m router_training.train_pilot "$MAX_STEPS"

echo "Job finished at $(date)"
echo "Final adapter: data/router_training/PILOT_UNREVIEWED_DATA_checkpoint/ (on home storage)"
