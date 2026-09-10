# Classifier pilot on BGU's Slurm cluster

Runs `router_training/train_pilot.py` on `slurm.bgu.ac.il` — the same script
already verified working locally (CPU, killed by host memory pressure at
step 25/40 before completing — see `docs/v2/RECONCILED_STATE_v0.2.md` §11b).
This bundle exists to get it onto a real GPU. **This is still a pilot, not a
citable model** — see the warning banner `train_pilot.py` prints on every run
and the caveats in its module docstring; nothing here changes that.

**Prerequisite you need to fill in before any of this works:** edit
`hpc/train_pilot.sbatch` and replace `--mail-user=CHANGE_ME@post.bgu.ac.il`
with your real BGU address.

Don't build a Skill out of this yet — codify it only after it's run
successfully once.

---

## Commands, in order

### 1. Push local changes (from your dev machine, this repo)

```bash
git push
```

### 2. Clone or update the repo on the cluster (manager node only — git isn't on compute nodes, but home storage is shared, so this is the only place you need to run it)

```bash
ssh <you>@slurm.bgu.ac.il
cd ~
git clone <this-repo-url> agentwarden-core      # first time only
# or, if already cloned:
cd ~/agentwarden-core && git pull
```

### 3. Transfer training data (from your dev machine — NOT the cluster)

`data/router_training/` is gitignored, so step 2's clone does **not** bring
`sample.jsonl` over — this is the "data problem" flagged explicitly. Don't
try to regenerate it on the cluster instead: `router_training/build_dataset.py`'s
paraphrase bucket is non-deterministic (a fresh run produces a *different*
18-example bucket each time — see that script's own docstring), so
regenerating would silently diverge from the dataset already tracked as
reviewed in `docs/v2/RECONCILED_STATE_v0.2.md` §8. scp the exact reviewed
file instead:

```bash
# from your dev machine, in this repo
ssh <you>@slurm.bgu.ac.il "mkdir -p ~/agentwarden-core/data/router_training"
scp data/router_training/sample.jsonl data/router_training/sample_manifest.json \
    <you>@slurm.bgu.ac.il:~/agentwarden-core/data/router_training/
```

Both `train_pilot.sbatch` and `train_pilot.py` check for this file explicitly
and exit fast with a clear error (not a silent no-op, not a crash mid-run) if
it's missing — you'll see it immediately in `squeue`/the job's `.err` log/the
failure email rather than discovering it after a wasted allocation.

### 4. Create the conda environment (manager node, once)

```bash
cd ~/agentwarden-core
bash hpc/setup_env.sh
```

Takes a few minutes (downloads torch + friends). Re-run only if you want a
clean rebuild (it refuses to overwrite an existing env — see the script).

### 5. Create the log directory (once)

```bash
mkdir -p ~/agentwarden-core/hpc/logs
```

Slurm needs this to exist before it can write `--output`/`--error` there.

### 6. Submit the job

**Conda must be deactivated first** — the cluster requires this at submit
time, even though the job script itself activates the env once it's running
on the compute node:

```bash
conda deactivate
cd ~/agentwarden-core
sbatch hpc/train_pilot.sbatch
```

To use more than the default 40 steps:

```bash
conda deactivate
MAX_STEPS=100 sbatch hpc/train_pilot.sbatch
```

### 7. Check status

```bash
squeue --me                # PD = pending, R = running, gone = finished/failed
jobstats <jobid>           # per-job resource usage (mem/GPU actually used vs. requested)
```

While it's running:

```bash
tail -f hpc/logs/agentwarden-pilot-<jobid>.out
```

### 8. After it finishes

Check the log for the final lines (`Training finished in ...s`, `Final adapter
saved to ...`), then confirm the artifact landed on home storage:

```bash
ls -la ~/agentwarden-core/data/router_training/PILOT_UNREVIEWED_DATA_checkpoint/
```

If the job was killed (timeout, preemption, OOM) before finishing, check the
same directory anyway — checkpoints are mirrored there every 10 steps during
training, not only at the end (see the "Data problem" note below and the
docstring in `router_training/train_pilot.py`), so a killed job still leaves
something to resume from. Re-submitting (`sbatch hpc/train_pilot.sbatch`
again) will auto-resume from the latest checkpoint it finds, whether that's
on scratch or on the home-storage mirror.

---

## How checkpointing works on the cluster (so a killed job doesn't lose everything)

This is the same problem the local dev run hit (killed at step 25/40, lost
all progress because nothing had been saved yet) — `train_pilot.py` is
adapted so it can't repeat that on the cluster:

- Frequent checkpoints (every 10 steps) write to `$SLURM_SCRATCH_DIR` —
  fast node-local storage, keeps repeated small writes off shared home
  storage.
- **After every one of those saves**, the checkpoint is also copied to home
  storage (`data/router_training/PILOT_UNREVIEWED_DATA_checkpoint/`) — not
  only at the very end. Scratch is wiped when the job's node allocation
  ends, and a hard OOM-kill is a SIGKILL that can't be trapped for a
  graceful "copy on the way out" — so the only way to guarantee progress
  survives a hard kill is to keep home storage current continuously, not
  just at a clean exit.
- The final trained adapter (`model.save_pretrained`) always targets home
  storage directly regardless of scratch.
- On resume, the script checks scratch first (has full optimizer state),
  then falls back to the home-storage mirror if scratch is gone (e.g. a
  fresh job on a different node after the previous one was killed).

---

## Troubleshooting

- **Job stays PENDING in `squeue --me`**: likely a partition mismatch. Run
  `sinfo -o "%P %G"` to find the GPU partition's name and add
  `#SBATCH --partition=<name>` to `train_pilot.sbatch`.
- **Job fails immediately with "no training data"**: you skipped step 3, or
  scp'd to the wrong path. Re-check with
  `ls ~/agentwarden-core/data/router_training/sample.jsonl` on the manager
  node.
- **No email arrives**: check you actually replaced `CHANGE_ME@post.bgu.ac.il`
  in `train_pilot.sbatch` with your real address.
- **`sbatch` itself rejects the submission**: almost certainly the conda-not-
  deactivated requirement — run `conda deactivate` and try again.
