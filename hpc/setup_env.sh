#!/bin/bash
# Run ONCE on the manager (login) node — NOT as a Slurm job. Environment
# creation needs outbound network access to fetch packages, which the
# manager node has and compute nodes are not guaranteed to.
#
# Usage:
#   ssh <you>@slurm.bgu.ac.il
#   cd ~/agentwarden-core        # wherever you cloned the repo
#   bash hpc/setup_env.sh
#
# Versions are pinned to exactly what was verified working (import +
# actual CUDA op, not just torch.cuda.is_available()) during this
# pilot's development. torch==2.10.0's supported compute-capability list
# (sm_75/80/86/90/100/120) includes RTX 3090's sm_86 directly — checked
# against this exact build's own reported support list, not assumed.
set -euo pipefail

module load anaconda

ENV_NAME="agentwarden-pilot"
PYTHON_VERSION="3.11"

if conda env list | grep -q "^${ENV_NAME} "; then
    echo "Env '${ENV_NAME}' already exists — remove it first if you want a clean rebuild:"
    echo "  conda env remove -n ${ENV_NAME}"
    exit 1
fi

conda create -y -n "$ENV_NAME" python="$PYTHON_VERSION"
source activate "$ENV_NAME"

pip install --no-cache-dir \
    torch==2.10.0 \
    transformers==5.17.0 \
    peft==0.20.0 \
    accelerate==1.15.0 \
    bitsandbytes==0.50.2 \
    datasets==5.0.0 \
    huggingface_hub==1.23.0

echo
echo "Environment '${ENV_NAME}' ready."
echo "IMPORTANT: the cluster requires conda deactivated before you submit a job."
echo "  conda deactivate"
echo "  sbatch hpc/train_pilot.sbatch"
