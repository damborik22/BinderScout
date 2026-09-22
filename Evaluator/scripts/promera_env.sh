# Source this to run Promera on DGX Spark (aarch64 / GB10 / sm_121).
# The hard-won combo: torch 2.9.0+cu130 (CUDA-13 NVRTC knows sm_121; the PyPI-pinned
# 2.9.0+cu128 fails with `nvrtc: invalid --gpu-architecture`) + LD_LIBRARY_PATH exposing
# the cu12 NVIDIA libs so cuequivariance's cu12 kernels (libcue_ops.so → libcublas.so.12)
# load alongside torch's cu13 runtime. Both CUDA runtimes coexist in one process.
_PROM_ENV="${PROMERA_ENV:-binder-eval-promera}"
source "$(conda info --base)/etc/profile.d/conda.sh"; conda activate "$_PROM_ENV"
_SP=$(python -c "import site; print(site.getsitepackages()[0])")
_NVLIB=$(python -c "import glob,os,site; b=site.getsitepackages()[0]; print(':'.join(sorted(glob.glob(os.path.join(b,'nvidia','*','lib')))))")
export LD_LIBRARY_PATH="${_NVLIB}:${_SP}/cuequivariance_ops/lib:${LD_LIBRARY_PATH:-}"
_BM_ROOT="${BINDMASTER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export PROMERA_WEIGHTS="${PROMERA_WEIGHTS:-$_BM_ROOT/weights/promera/promera_2606.ckpt}"
# Triton 3.5 bundles a CUDA-12.8 ptxas (max sm_120) that errors on GB10 sm_121
# ("PTXAS error: Internal Triton PTX codegen error"). Point Triton at the system
# CUDA-13 ptxas, which supports sm_121.
if [ -x /usr/local/cuda/bin/ptxas ]; then export TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas; fi
