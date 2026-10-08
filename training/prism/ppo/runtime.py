"""Same-runtime deterministic execution and full learner RNG capture."""
import os
import platform
import random

import numpy as np
import torch

from .contract import exact, integer


def configure(device, cpu_threads):
    integer(cpu_threads, 1, 64, "cpu_threads")
    if device not in ("cpu", "cuda"):
        raise ValueError("device must be explicitly cpu or cuda")
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable; no fallback")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    if os.environ["CUBLAS_WORKSPACE_CONFIG"] not in (":4096:8", ":16:8"):
        raise ValueError("unsupported cuBLAS workspace")
    torch.set_num_threads(cpu_threads)
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    return {"device": device, "cpu_threads": cpu_threads, "python": platform.python_version(),
            "torch": str(torch.__version__), "numpy": np.__version__, "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
            "platform": platform.platform(), "machine": platform.machine(),
            "dtype": "float32", "amp": False, "tf32": False, "batch_shape": "singleton",
            "cublas_workspace": os.environ["CUBLAS_WORKSPACE_CONFIG"]}


def seed_all(seed):
    integer(seed, 0, 2**63 - 1, "seed")
    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)


def capture_rng():
    return {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state(),
            "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_initialized() else []}


def restore_rng(value):
    exact(value, {"python", "numpy", "torch", "cuda"}, "RNG state")
    random.setstate(value["python"])
    np.random.set_state(value["numpy"])
    torch.set_rng_state(value["torch"].cpu())
    if value["cuda"]:
        if not torch.cuda.is_available() or len(value["cuda"]) != torch.cuda.device_count():
            raise ValueError("CUDA RNG/runtime mismatch")
        torch.cuda.set_rng_state_all([v.cpu() for v in value["cuda"]])
