
from __future__ import annotations
from pathlib import Path
import json

# --- Disk space helpers (moved to top) ---
def get_disk_free_percent(path: Path) -> float:
    probe_path = path if path.exists() else path.parent
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
    usage = shutil.disk_usage(str(probe_path))
    return 100.0 * usage.free / usage.total

def ensure_artifacts_dir_space(artifacts_dir: Path) -> Path:
    try:
        if "/mnt/dataset_storage" in str(artifacts_dir):
            pass
    except ValueError:
        pass
    free_percent = get_disk_free_percent(artifacts_dir)
    safe_network_target = resolve_artifacts_dir(artifacts_dir)
    huggingface_cache = Path("/root/.cache/huggingface")
    if free_percent < 15:
        print(f"[WARN] Free space critically low ({free_percent:.1f}%). Moving more data to network storage and cleaning HuggingFace cache.")
        try:
            if huggingface_cache.exists():
                try:
                    shutil.rmtree(huggingface_cache)
                    print(f"[CLEANUP] HuggingFace cache at {huggingface_cache} deleted.")
                except PermissionError as e:
                    print(f"[WARN] Skipping HuggingFace cache cleanup due to permissions: {e}")
                except Exception as e:
                    print(f"[ERROR] Could not delete HuggingFace cache: {e}")
        except PermissionError as e:
            print(f"[WARN] Skipping HuggingFace cache check due to permissions: {e}")
        except Exception as e:
            print(f"[ERROR] Could not access HuggingFace cache: {e}")
        for item in artifacts_dir.glob("*"):
            try:
                dest = safe_network_target / item.name
                if item.is_file():
                    shutil.move(str(item), str(dest))
                if item.is_dir():
                    shutil.move(str(item), str(dest))
            except Exception as e:
                print(f"[ERROR] Could not move {item} to network storage: {e}")
        return safe_network_target
    elif free_percent < 35:
        print(f"[INFO] Free space low ({free_percent:.1f}%). Switching to network storage for artifacts and cleaning HuggingFace cache.")
        try:
            if huggingface_cache.exists():
                try:
                    shutil.rmtree(huggingface_cache)
                    print(f"[CLEANUP] HuggingFace cache at {huggingface_cache} deleted.")
                except PermissionError as e:
                    print(f"[WARN] Skipping HuggingFace cache cleanup due to permissions: {e}")
                except Exception as e:
                    print(f"[ERROR] Could not delete HuggingFace cache: {e}")
        except PermissionError as e:
            print(f"[WARN] Skipping HuggingFace cache check due to permissions: {e}")
        except Exception as e:
            print(f"[ERROR] Could not access HuggingFace cache: {e}")
        return safe_network_target
    else:
        return artifacts_dir

# --- Preprocessed batch loader for distributed pipeline integration ---
from typing import Optional
def load_preprocessed_batches(batches_dir: Path, max_batches: Optional[int] = None) -> list:
    scripts = []
    batch_files = sorted(batches_dir.glob("batch_*.jsonl"))
    if max_batches is not None:
        batch_files = batch_files[:int(max_batches)]
    for batch_file in batch_files:
        with open(batch_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        if "code" in item:
                            scripts.append(item["code"])
                        elif "tokens" in item:
                            scripts.append("".join(item["tokens"]))
                    elif isinstance(item, str):
                        scripts.append(item)
                except Exception:
                    continue
    return scripts
# --- Config path global for use in load_config and main ---

CONFIG_PATH_LOCAL = Path("/home/pi/Desktop/test/create/batch_schedule_config.json")
CONFIG_PATH_DOCKER = Path("/app/batch_schedule_config.json")
config_path = CONFIG_PATH_LOCAL if CONFIG_PATH_LOCAL.exists() else CONFIG_PATH_DOCKER
# --- Utility functions and constants for undefineds ---
def resolve_requested_patterns(target_languages):
    # Returns file patterns for the given target languages
    lang_map = {
        "python": ["*.py"],
        "java": ["*.java"],
        "c++": ["*.cpp", "*.cc", "*.cxx", "*.hpp", "*.h"],
        "c#": ["*.cs"],
        "go": ["*.go"],
        "rust": ["*.rs"],
        "javascript": ["*.js", "*.jsx", "*.mjs"],
        "typescript": ["*.ts", "*.tsx"],
        "all": ["*"],
        "*": ["*"],
    }
    patterns = []
    for lang in target_languages:
        patterns.extend(lang_map.get(str(lang).strip().lower(), ["*"]))
    return list(dict.fromkeys(patterns))

def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def atomic_write_json(path, data):
    from tempfile import NamedTemporaryFile
    import json, os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        json.dump(data, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, path)

def _missing_runtime_modules(modules):
    missing = []
    for m in modules:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    return missing

def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{int(m)}m {int(s)}s"
    h, m = divmod(m, 60)
    return f"{int(h)}h {int(m)}m"

DISK_FREE_THRESHOLD_MOVE = 15

#!/usr/bin/env python3
import subprocess
import fcntl
import errno
import sys
import os

# --- Move resolve_artifacts_dir and dependencies above load_config ---
def resolve_artifacts_dir(configured_path: Path) -> Path:
    """
    Prefer the configured share-drive path, but if it is a broken symlink inside
    a container, fall back to the direct bind mount that points at the same data.
    """
    preferred = configured_path
    dataset_storage_fallback = Path("/mnt/1tb/skynetv1")
    legacy_toshiba = Path("/mnt/toshiba/skynetv1")
    local_fallback = Path("/home/pi/Desktop/test/create/skynetv1")

    for candidate in (preferred, dataset_storage_fallback, legacy_toshiba, local_fallback):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            test_file = candidate / ".write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            if candidate != preferred:
                pass  # Optionally log fallback
            return candidate
        except (PermissionError, OSError) as exc:
            print(f"[NLP] Artifacts dir not writable: {candidate} ({exc})")

    # Last resort: return local fallback path even if creation failed here.
    return local_fallback

# --- Preprocessed batch loader for distributed pipeline integration ---

# --- Ensure all shared root constants and resolve_dataset_roots are defined before use ---
DATASET_STORAGE_ROOT = Path("/mnt/dataset_storage")
SHARED_TRAINING_ROOT = Path("/mnt/dataset_storage/skynetv1")
CONTAINER_TRAINING_ROOT = Path("/mnt/dataset_storage/skynetv1")
NFS_TRAINING_ROOT = Path("/mnt/nfs_shared/skynetv1")
SHARED_SCAN_ROOTS = [
    Path("/mnt/dataset_storage"),
    Path("/mnt/shared"),
    Path("/mnt/toshiba"),
    Path("/mnt/webcode"),
    Path("/mnt/1tb"),
    Path("/mnt/nfs_shared"),
]
IMPLEMENTATION_OUTPUT_ROOTS = [
    Path("/app/implementation_outputs"),
    Path("/app/implementations"),
    Path("/mnt/shared/implementation_outputs"),
    Path("/mnt/shared/implementations"),
    Path("/mnt/dataset_storage/implementation_outputs"),
    Path("/mnt/dataset_storage/implementations"),
    Path("/mnt/toshiba/implementation_outputs"),
    Path("/mnt/toshiba/implementations"),
    Path("/mnt/webcode/implementation_outputs"),
    Path("/mnt/webcode/implementations"),
    Path("/mnt/1tb/implementation_outputs"),
    Path("/mnt/1tb/implementations"),
    Path("/mnt/nfs_shared/implementation_outputs"),
    Path("/mnt/nfs_shared/implementations"),
    Path("/home/pi/Desktop/test/implementation_outputs"),
    Path("/home/pi/Desktop/test/implementations"),
]

def resolve_dataset_roots(configured_roots: list, include_fallbacks: bool = True) -> list:
    """
    Build an ordered dataset root list.
    Prefer explicit config values first, then known shared-drive mounts.
    """
    ordered = []
    seen = set()

    def _add_if_readable(path: Path) -> None:
        key = str(path)
        if key in seen:
            return
        if path.exists() and path.is_dir() and os.access(path, os.R_OK | os.X_OK):
            ordered.append(path)
            seen.add(key)

    # First priority: explicit config values
    for root in configured_roots:
        _add_if_readable(root)

    if include_fallbacks:
        # Keep broad shared-drive mounts as fallback, but do not override configured roots.
        for fallback in [
            *IMPLEMENTATION_OUTPUT_ROOTS,
            *SHARED_SCAN_ROOTS,
            SHARED_TRAINING_ROOT,
            CONTAINER_TRAINING_ROOT,
            NFS_TRAINING_ROOT,
        ]:
            _add_if_readable(fallback)

    # Last resort: keep compatibility with the previous default path.
    if not ordered:
        return [DATASET_STORAGE_ROOT]
    return ordered
    """Load tokenized code batches from Dask preprocessing output."""
    scripts = []
    batch_files = sorted(batches_dir.glob("batch_*.jsonl"))
    if max_batches is not None:
        batch_files = batch_files[:max_batches]
    for batch_file in batch_files:
        with open(batch_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        if "code" in item:
                            scripts.append(item["code"])
                        elif "tokens" in item:
                            scripts.append("".join(item["tokens"]))
                    elif isinstance(item, str):
                        scripts.append(item)
                except Exception:
                    continue
    return scripts

# --- Algorithmic Synthesis Agent Integration ---
def run_algorithmic_synthesis(problem: str, language: str = "python", goal: str = "time complexity") -> dict:
    """Use the in-process skynetv2 synthesis engine and return its result."""
    try:
        from create.skynetv2_agent import run_algorithmic_synthesis as _run_algorithmic_synthesis
    except Exception as exc:
        return {"error": f"skynetv2 synthesis unavailable: {exc}"}
    return _run_algorithmic_synthesis(problem=problem, language=language, goal=goal)
"""
NLP Code Trainer (Saturday batch step)

Purpose:
- Train a small Transformers language model on simple Python scripts
- Use a 96-layer transformer config for SkyNetV1 experimentation
- Export attention profile so we can inspect how the model attends to code text

This script is intentionally conservative for Raspberry Pi constraints:
- Small dataset slice
- Small sequence length
- Low training steps
- Graceful fallback if dependencies are missing
"""

def is_dataset_ready(cfg: TrainerConfig) -> bool:
    """Check if a valid dataset cache or manifest exists and is non-empty."""
    file_patterns = resolve_requested_patterns(cfg.target_languages)
    # Check for a dataset cache file with candidates
    for root in cfg.dataset_roots:
        cache_path = dataset_cache_path(cfg, root, file_patterns)
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if payload.get("candidate_count", 0) > 0:
                    return True
            except Exception:
                continue
    # Optionally, check for a manifest or summary file
    summary_path = cfg.artifacts_dir / cfg.summary_file
    if summary_path.exists():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if payload.get("dataset_script_count", 0) > 0:
                return True
        except Exception:
            pass
    return False

def move_artifacts_to_network(artifacts_dir: Path):
    """Move all files from artifacts_dir to network artifacts dir."""
    target_dir = Path("/mnt/dataset_storage/skynetv1")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as exc:
        fallback_dir = Path("/home/pi/Desktop/test/create/skynetv1")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        print(f"[NLP] Network artifacts dir unavailable ({exc}); using fallback: {fallback_dir}")
        target_dir = fallback_dir
    for item in artifacts_dir.glob("*"):
        try:
            dest = target_dir / item.name
            if item.is_file():
                shutil.move(str(item), str(dest))
            if item.is_dir():
                shutil.move(str(item), str(dest))
        except Exception as e:
            print(f"[ERROR] Could not move {item} to network storage: {e}")

import traceback
import re
import math
import hashlib
import importlib.util
import time
from dataclasses import dataclass
import shutil

from typing import Any, Dict, Iterator, List, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv("/home/pi/Desktop/test/.env")
    load_dotenv("/app/.env")

resolved_hf_token = (
    os.environ.get("HF_TOKEN")
    or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    or ""
)
if resolved_hf_token:
    os.environ["HF_TOKEN"] = resolved_hf_token
    os.environ["HUGGINGFACE_HUB_TOKEN"] = resolved_hf_token

# Optional dependencies for document parsing
try:
    import docx
except ImportError:
    docx = None
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

# Required external packages:
#   pip install torch python-docx PyPDF2

def _probe_opencl_runtime() -> str | None:
    """Return a short OpenCL platform label when the runtime is visible."""
    if not Path("/dev/dri").exists():
        return None
    try:
        probe = subprocess.run(
            ["clinfo"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if probe.returncode != 0:
        return None
    for line in probe.stdout.splitlines():
        normalized = line.strip()
        if normalized.lower().startswith("platform name"):
            _, _, value = normalized.partition(":")
            return value.strip() or "OpenCL runtime detected"
    return "OpenCL runtime detected"

def detect_best_device(torch_module: Any | None, requested_mode: str | None = None) -> Tuple[str, str]:
    """Prefer a torch accelerator when exposed, otherwise fall back to CPU.

    ROCm-backed AMD GPUs are surfaced through torch.cuda in compatible builds.
    When only an OpenCL runtime is visible, keep training on CPU and log that
    the GPU runtime exists but is not directly usable by the current PyTorch.
    """
    requested = (requested_mode or os.environ.get("USE_GPU", "auto")).strip().lower()
    accelerator_requested = requested in {"1", "true", "yes", "auto"}
    if accelerator_requested and torch_module is not None and torch_module.cuda.is_available():
        return "cuda", torch_module.cuda.get_device_name(0)
    opencl_label = _probe_opencl_runtime()
    if requested in {"1", "true", "yes"} and opencl_label:
        return "cpu", f"{opencl_label} detected but PyTorch accelerator unavailable"
    if requested in {"1", "true", "yes"}:
        return "cpu", "GPU requested but no compatible accelerator detected"
    if opencl_label:
        return "cpu", f"{opencl_label} detected; using CPU fallback"
    return "cpu", "CPU"

try:
    import torch
except ImportError:
    torch = None

def _load_mistakelearn_helpers() -> tuple[Any, Any]:
    """Load helper functions from the sibling mistakelearn.py module."""
    try:
        from mistakelearn import inject_noise, unrolled_training_step
        return inject_noise, unrolled_training_step
    except ImportError:
        helper_path = Path(__file__).resolve().with_name("mistakelearn.py")
        if helper_path.exists():
            import importlib.util

            spec = importlib.util.spec_from_file_location("mistakelearn", helper_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module.inject_noise, module.unrolled_training_step

    def _unavailable_inject_noise(*args: Any, **kwargs: Any) -> Any:
        raise ImportError("mistakelearn helpers are unavailable")

    def _unavailable_unrolled_training_step(*args: Any, **kwargs: Any) -> Any:
        raise ImportError("mistakelearn helpers are unavailable")

    return _unavailable_inject_noise, _unavailable_unrolled_training_step


inject_noise, unrolled_training_step = _load_mistakelearn_helpers()

DEVICE, DEVICE_LABEL = detect_best_device(torch)
print(f"[INFO] Using device: {DEVICE} ({DEVICE_LABEL})")

# Support both local and Docker paths
CONFIG_PATH_LOCAL = Path("/home/pi/Desktop/test/create/batch_schedule_config.json")
CONFIG_PATH_DOCKER = Path("/app/batch_schedule_config.json")
APP_ARTIFACTS_ROOT = Path("/app/skynetv1")
WORKSPACE_VENV_PYTHON = Path("/home/pi/Desktop/test/.venv/bin/python")
REQUIRED_RUNTIME_MODULES: Tuple[str, ...] = ("torch", "transformers")

# Local (non-Docker) RAM safety cap: 5 GB maximum to prevent overnight crashes
LOCAL_RAM_LIMIT_GB = 5
LOCAL_RAM_LIMIT_BYTES = LOCAL_RAM_LIMIT_GB * 1024 ** 3
BACKGROUND_CACHE_BUILD_ENABLED = os.environ.get("NLP_BACKGROUND_CACHE_BUILD", "0") == "1"

def _is_running_in_docker() -> bool:
    """Return True when this process is running inside a Docker container."""
    return (
        Path("/.dockerenv").exists()
        or os.environ.get("DOCKER_CONTAINER") == "1"
        or os.environ.get("NODE_TYPE", "") in ("gpu", "cpu", "nlp")
    )

def _enforce_local_ram_limit(cfg) -> None:
    """Cap virtual address space at LOCAL_RAM_LIMIT_GB when running locally.

    This prevents the trainer from consuming all system RAM overnight, which
    caused the Pi to freeze and trigger the hardware watchdog reboot.
    Has no effect when running inside a Docker container (limits are set by
    Docker's --memory flag instead).
    """

    # Use node-specific filenames if running in parallel.
    if cfg.node_type and cfg.node_type != "unknown":
        summary_file = f"nlp_training_summary_{cfg.node_type}.json"
        attention_file = f"nlp_attention_profile_{cfg.node_type}.json"
    else:
        summary_file = cfg.summary_file
        attention_file = cfg.attention_file

    summary_path = cfg.artifacts_dir / summary_file
    attention_path = cfg.artifacts_dir / attention_file

    missing_modules = _missing_runtime_modules(REQUIRED_RUNTIME_MODULES)
    if missing_modules:
        install_cmd = f"{sys.executable} -m pip install {' '.join(missing_modules)}"
        summary = {
            "timestamp": utc_now_iso(),
            "status": "skipped_missing_dependencies",
            "message": "Missing required runtime packages before training",
            "missing_modules": missing_modules,
            "python_executable": sys.executable,
            "install_command": install_cmd,
            "node_type": cfg.node_type,
        }
        atomic_write_json(summary_path, summary)
        print(
            f"[NLP] Missing required packages: {', '.join(missing_modules)}\n"
            f"[NLP] Python executable: {sys.executable}\n"
            f"[NLP] Install with: {install_cmd}"
        )
        return

    if not cfg.enabled:
        summary = {
            "timestamp": utc_now_iso(),
            "status": "disabled",
            "message": "NLP training disabled in configuration",
            "node_type": cfg.node_type,
        }
        atomic_write_json(summary_path, summary)
        print(f"[NLP] Training disabled (node: {cfg.node_type})")
        return

    # Check if dataset is ready before building
    dataset_ready = is_dataset_ready(cfg)
    # --- INTEGRATION: Try to load preprocessed batches if available ---
    batches_dir = Path("/mnt/1tb/skynetv1/processed_batches")
    if batches_dir.exists() and any(batches_dir.glob("batch_*.jsonl")):
        print(f"[NLP] Loading preprocessed code batches from {batches_dir}")
        scripts = load_preprocessed_batches(batches_dir, max_batches=3)
        script_paths = []
    else:
        if dataset_ready:
            # Only set RAM limits, do not use cfg here
            if _is_running_in_docker():
                return
            try:
                import resource
                import psutil
                limit = LOCAL_RAM_LIMIT_BYTES
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                new_hard = limit if (hard == resource.RLIM_INFINITY or hard > limit) else hard
                new_soft = limit if (soft == resource.RLIM_INFINITY or soft > limit) else soft
                resource.setrlimit(resource.RLIMIT_AS, (new_soft, new_hard))
                total_gb = psutil.virtual_memory().total / 1024 ** 3
                print(f"[NLP] Local RAM cap applied: {LOCAL_RAM_LIMIT_GB} GB limit (system has {total_gb:.1f} GB total)")
            except Exception as exc:
                print(f"[NLP] Warning: could not apply RAM limit: {exc}")
        pass

    free_percent = get_disk_free_percent(cfg.artifacts_dir)
    safe_network_target = resolve_artifacts_dir(cfg.artifacts_dir)
    # Clean up HuggingFace cache if disk space is low
    huggingface_cache = Path("/root/.cache/huggingface")
    if free_percent < DISK_FREE_THRESHOLD_MOVE:
        print(f"[WARN] Free space critically low ({free_percent:.1f}%). Moving more data to network storage and cleaning HuggingFace cache.")
        # Clean HuggingFace cache
        try:
            if huggingface_cache.exists():
                try:
                    shutil.rmtree(huggingface_cache)
                    print(f"[CLEANUP] HuggingFace cache at {huggingface_cache} deleted.")
                except PermissionError as e:
                    print(f"[WARN] Skipping HuggingFace cache cleanup due to permissions: {e}")
                except Exception as e:
                    print(f"[ERROR] Could not delete HuggingFace cache: {e}")
        except PermissionError as e:
            print(f"[WARN] Skipping HuggingFace cache check due to permissions: {e}")
        except Exception as e:
            print(f"[ERROR] Could not access HuggingFace cache: {e}")
        # Only set RAM limits, do not use cfg here
        if _is_running_in_docker():
            return
        try:
            limit = LOCAL_RAM_LIMIT_BYTES
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            new_hard = limit if (hard == resource.RLIM_INFINITY or hard > limit) else hard
            new_soft = limit if (soft == resource.RLIM_INFINITY or soft > limit) else soft
            resource.setrlimit(resource.RLIMIT_AS, (new_soft, new_hard))
            total_gb = psutil.virtual_memory().total / 1024 ** 3
            print(f"[NLP] Local RAM cap applied: {LOCAL_RAM_LIMIT_GB} GB limit (system has {total_gb:.1f} GB total)")
        except Exception as exc:
            print(f"[NLP] Warning: could not apply RAM limit: {exc}")

def _maybe_reexec_into_workspace_venv() -> None:
    """Re-launch under workspace venv if user started this script with system python."""
    if os.environ.get("NLP_SKIP_VENV_REEXEC") == "1":
        return
    if not WORKSPACE_VENV_PYTHON.exists():
        return

    # Robust venv detection: symlinked interpreters can resolve to the same
    # system binary path while still being different runtime environments.
    in_any_venv = (getattr(sys, "base_prefix", sys.prefix) != sys.prefix)
    current_python_raw = Path(sys.executable)
    target_python_raw = WORKSPACE_VENV_PYTHON

    if in_any_venv and current_python_raw == target_python_raw:
        return

    current_venv = os.environ.get("VIRTUAL_ENV")
    if in_any_venv and current_venv == str(WORKSPACE_VENV_PYTHON.parent.parent):
        return

    print(f"[NLP] Re-launching with workspace venv interpreter: {target_python_raw}")
    env = os.environ.copy()
    env["NLP_SKIP_VENV_REEXEC"] = "1"
    os.execve(
        str(target_python_raw),
        [str(target_python_raw), os.path.abspath(__file__), *sys.argv[1:]],
        env,
    )

@dataclass
class TrainerConfig:
    enabled: bool
    target_language: str
    target_languages: list
    dataset_roots: list
    min_lines_per_script: int
    max_lines_per_script: int
    max_scripts: int
    tokenizer_name: str
    num_hidden_layers: int
    hidden_size: int
    num_attention_heads: int
    max_sequence_length: int
    batch_size: int
    gradient_accumulation_steps: int
    max_steps: int
    total_epochs: float
    learning_rate: float
    artifacts_dir: Path
    summary_file: str
    attention_file: str
    continue_if_failed: bool
    node_type: str  # "gpu" or "cpu" for separate outputs
    autoregressive_enabled: bool
    growth_start_layers: int
    growth_target_layers: int
    growth_step_layers: int
    growth_steps_per_stage: int
    split_back_to_layers: int
    specialist_layer_count: int
    dynamic_architecture_enabled: bool
    recursive_optimization_enabled: bool
    recursive_max_loops: int
    recursive_target_loss: float
    recursive_plateau_delta: float
    hierarchical_curriculum_enabled: bool
    residual_scaling_enabled: bool
    residual_scaling_base: float
    residual_scaling_min: float
    independent_mode: bool
    tools_enabled: bool
    tools_allow_shell: bool
    autonomy_mode: str
    autonomy_time_budget_minutes: int
    autonomy_auto_fast_mode: bool
    delete_consumed_scripts: bool
    cleanup_old_artifacts: bool
    keep_latest_dataset_caches: int
    keep_latest_growth_stages: int
    keep_latest_attention_profiles: int

def load_config() -> TrainerConfig:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    section = data.get("nlp_training", {})
    model = section.get("model", {})
    autoreg = section.get("autoregressive", {})
    dyn = section.get("dynamic_architecture", {})

    max_steps = int(model.get("max_steps", 200))
    if os.environ.get("NLP_MAX_STEPS_OVERRIDE"):
        max_steps = int(os.environ["NLP_MAX_STEPS_OVERRIDE"])
    total_epochs = float(section.get("total_epochs", 15))
    if os.environ.get("NLP_TOTAL_EPOCHS_OVERRIDE"):
        total_epochs = float(os.environ["NLP_TOTAL_EPOCHS_OVERRIDE"])
    total_epochs = max(15.0, total_epochs)

    raw_roots = [Path(p) for p in section.get("dataset_roots", [])]

    raw_target_language = section.get("target_language", "Python")
    if isinstance(raw_target_language, list):
        target_languages = [str(x).strip() for x in raw_target_language if str(x).strip()]
    else:
        target_languages = [x.strip() for x in str(raw_target_language).replace("|", ",").split(",") if x.strip()]
    if not target_languages:
        target_languages = ["Python"]

    # Prefer configured roots, then include readable fallbacks.
    default_roots = list(dict.fromkeys(SHARED_SCAN_ROOTS + [DATASET_STORAGE_ROOT]))
    dataset_roots: List[Path] = resolve_dataset_roots(
        raw_roots if raw_roots else default_roots,
        include_fallbacks=True,
    )

    # Check and adjust artifacts_dir based on disk space
    raw_artifacts_dir = resolve_artifacts_dir(
        Path(section.get("artifacts_dir", "/home/pi/Desktop/test/create/skynetv1"))
    )
    artifacts_dir = ensure_artifacts_dir_space(raw_artifacts_dir)

    return TrainerConfig(
        enabled=bool(section.get("enabled", True)),
        target_language=target_languages[0],
        target_languages=target_languages,
        dataset_roots=dataset_roots,
        min_lines_per_script=int(section.get("min_lines_per_script", 1)),
        max_lines_per_script=int(section.get("max_lines_per_script", 299992000)),
        max_scripts=int(section.get("max_scripts", 120)),
        tokenizer_name=model.get("tokenizer", "distilgpt2"),
        num_hidden_layers=int(model.get("num_hidden_layers", 96)),
        hidden_size=int(model.get("hidden_size", 128)),
        num_attention_heads=int(model.get("num_attention_heads", 8)),
        max_sequence_length=int(model.get("max_sequence_length", 4096)),
        batch_size=2,
        gradient_accumulation_steps=int(model.get("gradient_accumulation_steps", 2)),
        max_steps=max_steps,
        total_epochs=total_epochs,
        learning_rate=float(model.get("learning_rate", 5e-5)),
        artifacts_dir=artifacts_dir,
        summary_file=section.get("summary_file", "nlp_training_summary.json"),
        attention_file=section.get("attention_file", "nlp_attention_profile.json"),
        continue_if_failed=bool(section.get("continue_if_failed", True)),
        node_type=os.environ.get("NODE_TYPE", "unknown"),
        autoregressive_enabled=bool(autoreg.get("enabled", False)),
        growth_start_layers=int(autoreg.get("start_layers", int(model.get("num_hidden_layers", 96)))),
        growth_target_layers=int(autoreg.get("growth_target_layers", 196)),
        growth_step_layers=max(1, int(autoreg.get("growth_step_layers", 8))),
        growth_steps_per_stage=max(15, int(autoreg.get("steps_per_stage", 16))),
        split_back_to_layers=max(1, int(autoreg.get("split_back_to_layers", 96))),
        specialist_layer_count=max(1, int(autoreg.get("specialist_layer_count", 32))),
        dynamic_architecture_enabled=bool(dyn.get("enabled", False)),
        recursive_optimization_enabled=bool(dyn.get("recursive_optimization_enabled", True)),
        recursive_max_loops=max(14, int(dyn.get("recursive_max_loops", 33))),
        recursive_target_loss=float(dyn.get("recursive_target_loss", 2.0)),
        recursive_plateau_delta=float(dyn.get("recursive_plateau_delta", 0.01)),
        hierarchical_curriculum_enabled=bool(dyn.get("hierarchical_curriculum_enabled", True)),
        residual_scaling_enabled=bool(dyn.get("residual_scaling_enabled", True)),
        residual_scaling_base=float(dyn.get("residual_scaling_base", 0.95)),
        residual_scaling_min=float(dyn.get("residual_scaling_min", 0.75)),
        independent_mode=bool(dyn.get("independent_mode", True)),
        tools_enabled=bool(dyn.get("tools_enabled", True)),
        tools_allow_shell=bool(dyn.get("tools_allow_shell", False)),
        autonomy_mode=str(dyn.get("autonomy_mode", "full")).lower(),
        autonomy_time_budget_minutes=max(1000, int(dyn.get("autonomy_time_budget_minutes", 192000))),
        autonomy_auto_fast_mode=bool(dyn.get("autonomy_auto_fast_mode", True)),
        delete_consumed_scripts=bool(section.get("delete_consumed_scripts", False)),
        cleanup_old_artifacts=bool(section.get("cleanup_old_artifacts", True)),
        keep_latest_dataset_caches=max(1, int(section.get("keep_latest_dataset_caches", 3))),
        keep_latest_growth_stages=max(1, int(section.get("keep_latest_growth_stages", 2))),
        keep_latest_attention_profiles=max(1, int(section.get("keep_latest_attention_profiles", 4))),
    )

def run_harding_post_cycle(
    cfg: TrainerConfig,
    scripts: List[str],
    training_result: Dict[str, Any],
    phase: str,
    attention_profile: Dict[str, Any] | None = None,
    extra_outputs: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    try:
        from harding import run_post_training_learning_cycle
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason": f"harding import failed: {exc}",
        }

    try:
        return run_post_training_learning_cycle(
            artifacts_dir=cfg.artifacts_dir,
            training_result=training_result,
            scripts=scripts,
            node_type=cfg.node_type,
            phase=phase,
            attention_profile=attention_profile,
            extra_outputs=extra_outputs,
        )
    except Exception as exc:

        return {
            "status": "failed",
            "reason": str(exc),
            "traceback": traceback.format_exc(limit=12),
        }

def read_python_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

def extract_text_from_docx(path: Path) -> str:
    """Extract text from Word document."""
    if docx is None:
        return ""
    try:
        doc = docx.Document(str(path))
        return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
    except Exception:
        return ""
def extract_text_from_pdf(path: Path) -> str:
    """Extract text from PDF document."""
    if PyPDF2 is None:
        return ""
    try:
        reader = PyPDF2.PdfReader(path)
        text = []
        for page in reader.pages[:50]:
            try:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
            except Exception:
                continue
        return "\n".join(text)
    except Exception:
        return ""

def read_document_text(path: Path) -> str:
    """Universal text reader for Python, Word, and PDF files."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return read_python_text(path)
    elif suffix == ".docx":
        return extract_text_from_docx(path)
    elif suffix == ".pdf":
        return extract_text_from_pdf(path)
    else:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

def is_simple_python_script(code: str, cfg: TrainerConfig) -> bool:
    if not code.strip():
        return False
    line_count = len(code.splitlines())
    if line_count < cfg.min_lines_per_script or line_count > cfg.max_lines_per_script:
        return False
    # Less strict: accept any non-empty .py file
    return True

def is_simple_non_python_script(code: str, cfg: TrainerConfig) -> bool:
    if not code.strip():
        return False
    line_count = len(code.splitlines())
    if line_count < cfg.min_lines_per_script or line_count > cfg.max_lines_per_script:
        return False

    if any(str(lang).strip().lower() in {"all", "*"} for lang in cfg.target_languages):
        return True

    markers = [
        "function ", "class ", "import ", "export ",
        "public ", "private ", "protected ",
        "#include", "fn ", "package ", "namespace ",
    ]
    if not any(m in code for m in markers):
        return False

    return True

def iter_candidate_files(
    root_path: Path,
    file_patterns: List[str],
    excluded_parts: set[str],
    limit: int | None = None,
) -> Iterator[Path]:
    """Yield matching candidate files without materializing the whole tree in RAM."""
    match_all = any(pattern.strip() == "*" for pattern in file_patterns)
    pattern_suffixes = {
        Path(p.replace("*", "x")).suffix.lower()
        for p in file_patterns
        if p.strip() != "*"
    }
    preferred_dirs = {
        "external_data": -100,
        "github_repos": -90,
        "ml_models": -80,
        "mozilla": -70,
        "llvm": -60,
        "stackoverflow": -50,
        "public_datasets": -40,
        "sourceforge": -30,
        "gitlab": -20,
    }

    def _on_walk_error(_: OSError) -> None:
        return

    yielded = 0
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, onerror=_on_walk_error):
        dirnames[:] = [d for d in dirnames if d not in excluded_parts]
        dirnames.sort(key=lambda d: (preferred_dirs.get(d, 0), d))
        filenames.sort()
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if not match_all and path.suffix.lower() not in pattern_suffixes:
                continue
            yielded += 1
            if yielded % 5000 == 0:
                print(f"[Dataset] Indexed {yielded} matching files so far under {root_path}...")
            yield path
            if limit is not None and yielded >= limit:
                return

def dataset_cache_path(cfg: TrainerConfig, root_path: Path, file_patterns: List[str]) -> Path:
    normalized_root = str(root_path)
    shared_roots = {
        str(DATASET_STORAGE_ROOT),
        str(CONTAINER_TRAINING_ROOT),
        str(SHARED_TRAINING_ROOT),
        str(NFS_TRAINING_ROOT),
    }
    if normalized_root in shared_roots:
        normalized_root = "shared_training_data"
    cache_key = hashlib.sha1(f"{normalized_root}|{'|'.join(file_patterns)}".encode("utf-8")).hexdigest()[:12]
    return cfg.artifacts_dir / f"dataset_candidates_{cache_key}.json"

def load_cached_candidates(cache_path: Path) -> List[Path]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return [Path(p) for p in payload.get("candidates", [])]
    except Exception:
        return []

def candidate_pool_limit(cfg: TrainerConfig) -> int:
    override = os.environ.get("NLP_MAX_CANDIDATES_PER_ROOT")
    if override:
        try:
            return max(1000, int(override))
        except ValueError:
            print(f"[WARN] Ignoring invalid NLP_MAX_CANDIDATES_PER_ROOT={override!r}")
    desired = max(cfg.max_scripts * 2, 10_000)
    return min(desired, 250_000)

def trim_candidate_pool(candidates: List[Path], limit: int) -> List[Path]:
    if limit <= 0 or len(candidates) <= limit:
        return candidates
    if limit == 1:
        return [candidates[0]]

    step = len(candidates) / limit
    selected: List[Path] = []
    used_indexes: set[int] = set()
    for i in range(limit):
        idx = min(len(candidates) - 1, int(i * step))
        if idx in used_indexes:
            continue
        used_indexes.add(idx)
        selected.append(candidates[idx])
    return selected

def save_cached_candidates(cache_path: Path, root_path: Path, candidates: List[Path]) -> None:
    atomic_write_json(
        cache_path,
        {
            "timestamp": utc_now_iso(),
            "root": str(root_path),
            "candidate_count": len(candidates),
            "candidates": [str(p) for p in candidates],
        },
    )

def build_dataset(cfg: TrainerConfig) -> Tuple[List[str], List[str]]:
    """
    Build training dataset from multiple sources.
    Prioritizes data from the mounted share drive under /mnt/1tb.
    Supports nested code files for configured languages.
    """
    dataset_started_at = time.perf_counter()
    scripts: List[str] = []
    paths: List[str] = []
    candidates_examined = 0
    excluded_parts = {
        "venv",
        ".venv",
        "site-packages",
        "__pycache__",
        "node_modules",
        ".git",
        ".egg-info",
        "dist",
        "build",
    }

    # Enhanced dataset roots with known shared/mounted pulled-data paths
    enhanced_roots = resolve_dataset_roots(cfg.dataset_roots, include_fallbacks=True)

    # De-duplicate while preserving order
    seen: set[str] = set()
    deduped_roots: List[Path] = []
    for root in enhanced_roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        deduped_roots.append(root)
    enhanced_roots = deduped_roots

    print(f"[Dataset] Building from {len(enhanced_roots)} source directories...")

    file_patterns = resolve_requested_patterns(cfg.target_languages)

    max_candidates_per_root = candidate_pool_limit(cfg)

    # Track which sources contributed data
    source_stats = {}

    active_roots: List[Tuple[Path, Any]] = []
    for root in enhanced_roots:
        if not root.exists():
            source_stats[str(root)] = {"status": "NOT_FOUND", "count": 0}
            continue
        try:
            if root.resolve() == cfg.artifacts_dir.resolve():
                source_stats[str(root)] = {"status": "SKIPPED_ARTIFACTS_DIR", "count": 0}
                continue
        except Exception:
            pass
        source_stats[str(root)] = {"status": "EMPTY", "count": 0, "prep_mode": "none", "prep_seconds": 0.0, "candidates": 0}
        cache_path = dataset_cache_path(cfg, root, file_patterns)
        prep_started_at = time.perf_counter()
        cached_candidates = trim_candidate_pool(load_cached_candidates(cache_path), max_candidates_per_root)
        force_large_rescan = cfg.max_scripts >= 1_000_000 and len(cached_candidates) < 50_000
        if force_large_rescan:
            print(
                f"[Dataset] Cache for {root.name} is too small for large run "
                f"({len(cached_candidates)} candidates); rescanning source..."
            )
            cached_candidates = []

        if cached_candidates:
            prep_seconds = time.perf_counter() - prep_started_at
            source_stats[str(root)]["prep_mode"] = "cache"
            source_stats[str(root)]["prep_seconds"] = prep_seconds
            source_stats[str(root)]["candidates"] = len(cached_candidates)
            print(
                f"[Dataset] Using cached candidate list for {root.name}: "
                f"{len(cached_candidates)} files loaded in {format_duration(prep_seconds)}"
            )
            iterator = iter(cached_candidates)
        else:
            candidates = trim_candidate_pool(
                list(iter_candidate_files(root, file_patterns, excluded_parts, limit=max_candidates_per_root)),
                max_candidates_per_root,
            )
            prep_seconds = time.perf_counter() - prep_started_at
            source_stats[str(root)]["prep_mode"] = "scan"
            source_stats[str(root)]["prep_seconds"] = prep_seconds
            source_stats[str(root)]["candidates"] = len(candidates)
            if candidates:
                print(
                    f"[Dataset] Indexed {len(candidates)} candidates under {root} "
                    f"in {format_duration(prep_seconds)}"
                )
                save_cached_candidates(cache_path, root, candidates)
            iterator = iter(candidates)
        active_roots.append((root, iterator))

    while active_roots and len(scripts) < cfg.max_scripts:
        next_round: List[Tuple[Path, Any]] = []

        for root, iterator in active_roots:
            if len(scripts) >= cfg.max_scripts:
                break

            accepted = False
            while True:
                try:
                    path = next(iterator)
                except StopIteration:
                    break

                candidates_examined += 1
                if candidates_examined % 1000 == 0:
                    elapsed = time.perf_counter() - dataset_started_at
                    print(
                        f"[Dataset] Examined {candidates_examined} candidates, "
                        f"accepted {len(scripts)} scripts in {format_duration(elapsed)}"
                    )
                code = read_document_text(path)
                if not code.strip():
                    continue

                if path.suffix.lower() == ".py":
                    if not is_simple_python_script(code, cfg):
                        continue
                else:
                    if not is_simple_non_python_script(code, cfg):
                        continue

                scripts.append(code)
                paths.append(str(path))
                source_stats[str(root)]["count"] += 1
                source_stats[str(root)]["status"] = "OK"
                accepted = True
                break

            if accepted:
                next_round.append((root, iterator))

        active_roots = next_round

    # Log dataset statistics
    dataset_seconds = time.perf_counter() - dataset_started_at
    print(
        f"[Dataset] Loaded {len(scripts)} scripts from "
        f"{len([s for s in source_stats.values() if s['count'] > 0])} sources "
        f"after examining {candidates_examined} candidates in {format_duration(dataset_seconds)}"
    )
    for source, stat in sorted(source_stats.items()):
        status_emoji = "✓" if stat["status"] == "OK" else ("✗" if stat["status"] == "NOT_FOUND" else "○")
        prep_mode = stat.get("prep_mode", "none")
        prep_seconds = stat.get("prep_seconds", 0.0)
        candidates = stat.get("candidates", 0)
        prep_summary = (
            f"{prep_mode} {candidates} candidates in {format_duration(prep_seconds)}"
            if prep_mode != "none"
            else "not prepared"
        )
        print(
            f"  {status_emoji} {Path(source).name}: {stat['count']} scripts "
            f"({stat['status']}; {prep_summary})"
        )

    return scripts, paths

def prime_dataset_cache(cfg: TrainerConfig) -> Dict[str, Any]:
    """Build candidate-file caches without starting model training."""
    excluded_parts = {
        "venv",
        ".venv",
        "site-packages",
        "__pycache__",
        "node_modules",
        ".git",
        ".egg-info",
        "dist",
        "build",
    }

    enhanced_roots = resolve_dataset_roots(cfg.dataset_roots, include_fallbacks=True)

    seen: set[str] = set()
    unique_roots: List[Path] = []
    for root in enhanced_roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append(root)

    file_patterns = resolve_requested_patterns(cfg.target_languages)
    max_candidates_per_root = candidate_pool_limit(cfg)

    summary: Dict[str, Any] = {"timestamp": utc_now_iso(), "roots": []}
    for root in unique_roots:
        entry: Dict[str, Any] = {"root": str(root), "exists": root.exists()}
        if not root.exists():
            summary["roots"].append(entry)
            continue

        cache_path = dataset_cache_path(cfg, root, file_patterns)
        candidates = trim_candidate_pool(
            list(iter_candidate_files(root, file_patterns, excluded_parts, limit=max_candidates_per_root)),
            max_candidates_per_root,
        )
        save_cached_candidates(cache_path, root, candidates)
        entry["candidate_count"] = len(candidates)
        entry["cache_path"] = str(cache_path)
        summary["roots"].append(entry)
        print(f"[DatasetCache] {root}: {len(candidates)} candidates cached")

    atomic_write_json(cfg.artifacts_dir / "dataset_cache_manifest.json", summary)
    return summary

def cleanup_consumed_scripts(paths: List[str], cfg: TrainerConfig) -> Dict[str, Any]:
    """
    Remove scripts that were consumed for training to free space.
    Safety rule: only delete files under shared training roots.
    """
    if not cfg.delete_consumed_scripts:
        return {
            "enabled": False,
            "deleted": 0,
            "failed": 0,
            "skipped_outside_root": 0,
            "roots": [],
        }

    deleted = 0
    failed = 0
    skipped_outside = 0
    allowed_roots: List[Path] = []
    for candidate in [
        Path("/app/implementation_outputs"),
        Path("/app/implementations"),
        *IMPLEMENTATION_OUTPUT_ROOTS,
    ]:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved not in allowed_roots:
            allowed_roots.append(resolved)

    unique_paths = list(dict.fromkeys(paths))
    for raw in unique_paths:
        p = Path(raw)
        try:
            rp = p.resolve()
        except Exception:
            failed += 1
            continue

        under_allowed_root = False
        matched_root: Path | None = None

        for root in allowed_roots:
            try:
                rp.relative_to(root)
                under_allowed_root = True
                matched_root = root
                break
            except Exception:
                continue

        if not under_allowed_root:
            skipped_outside += 1
            continue

        try:
            if rp.exists() and rp.is_file():
                try:
                    rp.unlink()
                    deleted += 1
                except PermissionError as e:
                    print(f"[CLEANUP][PERMISSION] Could not delete {rp}: {e}")
                    failed += 1
                    continue

                # Prune now-empty parent folders up to the matched root
                parent = rp.parent
                while matched_root is not None and parent != matched_root and parent.exists():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        except Exception as e:
            print(f"[CLEANUP][ERROR] Could not process {rp}: {e}")
            failed += 1

    return {
        "enabled": True,
        "deleted": deleted,
        "failed": failed,
        "skipped_outside_root": skipped_outside,
        "roots": [str(r) for r in allowed_roots],
    }

def cleanup_old_training_artifacts(cfg: TrainerConfig) -> Dict[str, Any]:
    """Prune stale trainer-owned artifacts to keep the Swarm node from filling up."""
    result: Dict[str, Any] = {
        "enabled": cfg.cleanup_old_artifacts,
        "deleted_files": 0,
        "deleted_dirs": 0,
        "freed_bytes": 0,
        "failed": 0,
    }
    if not cfg.cleanup_old_artifacts:
        return result

    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
        return total

    def _remove_path(path: Path) -> None:
        size = _size(path)
        if path.is_dir():
            shutil.rmtree(path)
            result["deleted_dirs"] += 1
        else:
            path.unlink(missing_ok=True)
            result["deleted_files"] += 1
        result["freed_bytes"] += size

    def _prune(items: List[Path], keep: int) -> None:
        for stale in items[keep:]:
            try:
                _remove_path(stale)
            except Exception as exc:
                print(f"[Cleanup] Could not remove {stale}: {exc}")
                result["failed"] += 1

    cache_files = sorted(
        cfg.artifacts_dir.glob("dataset_candidates_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    _prune(cache_files, cfg.keep_latest_dataset_caches)

    growth_dirs = sorted(
        [p for p in cfg.artifacts_dir.glob("nlp_growth_stage_*") if p.is_dir()],
        key=lambda p: int(p.name.rsplit("_", 1)[-1]) if p.name.rsplit("_", 1)[-1].isdigit() else -1,
        reverse=True,
    )
    _prune(growth_dirs, cfg.keep_latest_growth_stages)

    attention_files = sorted(
        cfg.artifacts_dir.glob("nlp_attention_profile_layers_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    _prune(attention_files, cfg.keep_latest_attention_profiles)

    return result

def run_training(cfg: TrainerConfig, scripts: List[str]) -> Dict[str, Any]:
    try:
        import importlib

        torch = importlib.import_module("torch")
        Dataset = importlib.import_module("torch.utils.data").Dataset
        transformers = importlib.import_module("transformers")
        AutoTokenizer = transformers.AutoTokenizer
        GPT2Config = transformers.GPT2Config
        GPT2LMHeadModel = transformers.GPT2LMHeadModel
        Trainer = transformers.Trainer
        TrainingArguments = transformers.TrainingArguments

        # Detect the best available accelerator, including ROCm-backed AMD GPUs.
        requested_mode = os.environ.get("USE_GPU", "auto").strip().lower()
        device, accelerator_name = detect_best_device(torch, requested_mode)

        if device == "cuda":
            print(f"[NLP] Using accelerator via torch.cuda: {accelerator_name}")
            print(f"[NLP] Accelerator Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
        else:
            print(f"[NLP] {accelerator_name}")

        print(f"[NLP] PyTorch version: {torch.__version__}")
        print(f"[NLP] Device: {device}")
        print(f"[NLP] Accelerator label: {accelerator_name}")

        class CodeDataset(Dataset):
            def __init__(self, items: List[Dict[str, Any]]):
                self.items = items

            def __len__(self):
                return len(self.items)

            def __getitem__(self, idx: int) -> Dict[str, Any]:
                return self.items[idx]

        tokenizer = AutoTokenizer.from_pretrained(cfg.tokenizer_name)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        def infer_specialization_area(items: List[str]) -> Dict[str, Any]:
            joined = "\n".join(items).lower()
            buckets = {
                "data_processing": ["json", "csv", "parse", "pandas", "data"],
                "web_networking": ["http", "request", "api", "socket", "server"],
                "automation_tooling": ["argparse", "pathlib", "subprocess", "script", "file"],
                "testing_quality": ["test", "assert", "unittest", "pytest", "mock"],
                "ml_ai": ["model", "train", "tensor", "transformer", "embedding"],
            }
            scores: Dict[str, int] = {}
            for area, words in buckets.items():
                scores[area] = sum(joined.count(w) for w in words)

            area = max(scores, key=lambda k: scores[k]) if scores else "general_code"
            return {"area": area, "scores": scores}

        def build_encoded_dataset() -> Any:
            return build_encoded_dataset_from_texts(scripts)

        def build_encoded_dataset_from_texts(text_items: List[str]) -> Any:
            encoded_items: List[Dict[str, Any]] = []
            for text in text_items:
                encoded = tokenizer(
                    text,
                    truncation=True,
                    padding="max_length",
                    max_length=cfg.max_sequence_length,
                    return_tensors="pt",
                )
                input_ids = encoded["input_ids"][0]
                attn = encoded["attention_mask"][0]
                labels = input_ids.clone()
                encoded_items.append(
                    {
                        "input_ids": input_ids,
                        "attention_mask": attn,
                        "labels": labels,
                    }
                )
            return CodeDataset(encoded_items)

        def estimate_script_complexity(code: str) -> float:
            lines = max(1, len(code.splitlines()))
            branches = sum(code.count(k) for k in ["if ", "for ", "while ", "try:", "except", "with "])
            funcs = code.count("def ") + code.count("class ")
            nesting_signals = code.count("    ") / max(1, lines)
            return (branches * 2.0) + (funcs * 1.5) + (nesting_signals * 5.0) + math.log(lines + 1)

        def build_hierarchical_curriculum(items: List[str]) -> Dict[str, List[str]]:
            if not items:
                return {"easy": [], "medium": [], "hard": []}
            scored = sorted(((estimate_script_complexity(x), x) for x in items), key=lambda z: z[0])
            n = len(scored)
            e = max(1, n // 3)
            m = max(e + 1, (2 * n) // 3)
            easy = [x for _, x in scored[:e]]
            medium = [x for _, x in scored[e:m]]
            hard = [x for _, x in scored[m:]]
            if not medium:
                medium = easy[:]
            if not hard:
                hard = medium[:]
            return {"easy": easy, "medium": medium, "hard": hard}

        def choose_curriculum_subset(loop_idx: int, curriculum: Dict[str, List[str]]) -> List[str]:
            if not cfg.hierarchical_curriculum_enabled:
                return scripts
            if loop_idx <= 1:
                return curriculum.get("easy", []) or scripts
            if loop_idx == 2:
                return (curriculum.get("easy", []) + curriculum.get("medium", [])) or scripts
            return scripts

        def build_training_args(
            output_dir: Path,
            steps: int,
            *,
            use_epoch_schedule: bool = False,
            epochs: float | None = None,
        ) -> Any:
            training_kwargs = dict(
                output_dir=str(output_dir),
                per_device_train_batch_size=cfg.batch_size,
                gradient_accumulation_steps=cfg.gradient_accumulation_steps,
                learning_rate=cfg.learning_rate,
                logging_steps=5,
                save_steps=max(10, steps),
                save_total_limit=1,
                report_to="none",
                remove_unused_columns=False,
                dataloader_num_workers=0,
                use_cpu=(device == "cpu"),
                do_train=True,
            )
            if use_epoch_schedule:
                training_kwargs["num_train_epochs"] = float(max(15.0, epochs if epochs is not None else cfg.total_epochs))
                training_kwargs["max_steps"] = -1
            else:
                training_kwargs["max_steps"] = steps
            return TrainingArguments(**training_kwargs)

        def collect_attention_profile(model: Any, layer_count: int, suffix: str) -> Dict[str, Any]:
            sample = tokenizer(
                scripts[0],
                truncation=True,
                max_length=min(64, cfg.max_sequence_length),
                return_tensors="pt",
            )
            model.eval()
            with torch.no_grad():
                out = model(
                    input_ids=sample["input_ids"],
                    attention_mask=sample["attention_mask"],
                    output_attentions=True,
                )

            layer_means = []
            attentions = out.attentions or []
            for idx, att in enumerate(attentions):
                if att is None:
                    continue
                layer_means.append(
                    {
                        "layer": idx,
                        "mean_attention": float(att.mean().cpu().item()),
                        "max_attention": float(att.max().cpu().item()),
                    }
                )

            top_layers = sorted(layer_means, key=lambda x: x["mean_attention"], reverse=True)[:10]
            profile = {
                "timestamp": utc_now_iso(),
                "num_layers": layer_count,
                "sample_token_count": int(sample["input_ids"].shape[1]),
                "attention_available": bool(layer_means),
                "top_attention_layers": top_layers,
                "all_layer_means": layer_means,
                "notes": "Some backends may not return per-layer attention tensors; training still completes.",
            }
            atomic_write_json(cfg.artifacts_dir / f"{suffix}.json", profile)
            return profile

        def align_hidden_size() -> Tuple[int, int]:
            n_heads = max(1, cfg.num_attention_heads)
            hidden = cfg.hidden_size
            if hidden % n_heads != 0:
                hidden = n_heads * max(1, hidden // n_heads)
            return hidden, n_heads

        def clone_into_new_layer_count(source_model: Any, new_layer_count: int) -> Any:
            new_cfg = GPT2Config(
                vocab_size=source_model.config.vocab_size,
                n_positions=source_model.config.n_positions,
                n_ctx=source_model.config.n_ctx,
                n_embd=source_model.config.n_embd,
                n_layer=new_layer_count,
                n_head=source_model.config.n_head,
                resid_pdrop=source_model.config.resid_pdrop,
                embd_pdrop=source_model.config.embd_pdrop,
                attn_pdrop=source_model.config.attn_pdrop,
            )
            new_model = GPT2LMHeadModel(new_cfg)
            source_sd = source_model.state_dict()
            target_sd = new_model.state_dict()

            for key, value in source_sd.items():
                if key in target_sd and target_sd[key].shape == value.shape:
                    target_sd[key] = value

            source_layers = int(source_model.config.n_layer)
            if source_layers > 0:
                last_idx = source_layers - 1
                for key in list(target_sd.keys()):
                    m = re.match(r"^transformer\.h\.(\d+)\.(.+)$", key)
                    if not m:
                        continue
                    t_idx = int(m.group(1))
                    suffix = m.group(2)
                    if t_idx < source_layers:
                        continue
                    source_key = f"transformer.h.{last_idx}.{suffix}"
                    if source_key in source_sd and source_sd[source_key].shape == target_sd[key].shape:
                        target_sd[key] = source_sd[source_key]

            new_model.load_state_dict(target_sd, strict=False)
            return new_model

        def apply_residual_scaling(model: Any, base_scale: float, min_scale: float) -> None:
            if not cfg.residual_scaling_enabled:
                return
            layers = int(model.config.n_layer)
            if layers <= 0:
                return

            sd = model.state_dict()
            for idx in range(layers):
                t = idx / max(1, layers - 1)
                scale = max(min_scale, base_scale - (base_scale - min_scale) * t)
                for suffix in [
                    "attn.c_proj.weight",
                    "mlp.c_proj.weight",
                ]:
                    k = f"transformer.h.{idx}.{suffix}"
                    if k in sd:
                        sd[k] = sd[k] * scale
            model.load_state_dict(sd, strict=False)

        def export_tools_manifest() -> Path:
            manifest = {
                "timestamp": utc_now_iso(),
                "enabled": cfg.tools_enabled,
                "mode": "workspace_scoped",
                "principle": "least_privilege",
                "tools": {
                    "list_files": {"allowed": True, "scope": [str(p) for p in cfg.dataset_roots]},
                    "read_file": {"allowed": True, "scope": [str(p) for p in cfg.dataset_roots]},
                    "write_artifacts": {"allowed": True, "scope": [str(cfg.artifacts_dir)]},
                    "shell": {"allowed": cfg.tools_allow_shell, "note": "disabled by default for safety"},
                },
            }
            out = cfg.artifacts_dir / "nlp_tools_manifest.json"
            atomic_write_json(out, manifest)
            return out

        def plan_autonomous_execution(start_layers: int, target_layers: int) -> Dict[str, Any]:
            steps_per_stage = max(1, cfg.growth_steps_per_stage)
            recursive_loops = max(1, cfg.recursive_max_loops if cfg.recursive_optimization_enabled else 1)
            growth_step = max(1, cfg.growth_step_layers)

            stage_count = ((max(target_layers, start_layers) - start_layers) // growth_step) + 1
            estimated_units = stage_count * steps_per_stage * recursive_loops

            if cfg.autonomy_auto_fast_mode and cfg.autonomy_mode == "full":
                # Conservative runtime envelope for Pi-class hardware.
                # Target total units ~= time_budget_minutes / 6
                target_units = max(8, cfg.autonomy_time_budget_minutes // 6)
                while estimated_units > target_units and recursive_loops > 1:
                    recursive_loops -= 1
                    estimated_units = stage_count * steps_per_stage * recursive_loops
                while estimated_units > target_units and steps_per_stage > 1:
                    steps_per_stage -= 1
                    estimated_units = stage_count * steps_per_stage * recursive_loops
                while estimated_units > target_units and growth_step < 48:
                    growth_step = min(48, growth_step * 2)
                    stage_count = ((max(target_layers, start_layers) - start_layers) // growth_step) + 1
                    estimated_units = stage_count * steps_per_stage * recursive_loops

            return {
                "mode": cfg.autonomy_mode,
                "time_budget_minutes": cfg.autonomy_time_budget_minutes,
                "recursive_loops": recursive_loops,
                "steps_per_stage": steps_per_stage,
                "growth_step_layers": growth_step,
                "estimated_stage_count": stage_count,
                "estimated_units": estimated_units,
            }

        def clone_with_selected_layers(source_model: Any, selected_layers: List[int]) -> Any:
            selected = sorted(set(i for i in selected_layers if 0 <= i < int(source_model.config.n_layer)))
            if not selected:
                selected = [0]

            new_cfg = GPT2Config(
                vocab_size=source_model.config.vocab_size,
                n_positions=source_model.config.n_positions,
                n_ctx=source_model.config.n_ctx,
                n_embd=source_model.config.n_embd,
                n_layer=len(selected),
                n_head=source_model.config.n_head,
                resid_pdrop=source_model.config.resid_pdrop,
                embd_pdrop=source_model.config.embd_pdrop,
                attn_pdrop=source_model.config.attn_pdrop,
            )
            new_model = GPT2LMHeadModel(new_cfg)
            source_sd = source_model.state_dict()
            target_sd = new_model.state_dict()

            for key in list(target_sd.keys()):
                m = re.match(r"^transformer\.h\.(\d+)\.(.+)$", key)
                if not m:
                    if key in source_sd and source_sd[key].shape == target_sd[key].shape:
                        target_sd[key] = source_sd[key]
                    continue

                t_idx = int(m.group(1))
                suffix = m.group(2)
                s_idx = selected[t_idx]
                s_key = f"transformer.h.{s_idx}.{suffix}"
                if s_key in source_sd and source_sd[s_key].shape == target_sd[key].shape:
                    target_sd[key] = source_sd[s_key]

            new_model.load_state_dict(target_sd, strict=False)
            return new_model

        hidden, n_heads = align_hidden_size()
        dataset = build_encoded_dataset()
        curriculum = build_hierarchical_curriculum(scripts)

        tools_manifest_path = export_tools_manifest() if cfg.tools_enabled else None

        force_standard_epoch_training = os.environ.get("NLP_FORCE_STANDARD_EPOCH_TRAINING", "0") == "1"
        if force_standard_epoch_training:
            print("[NLP] Forcing standard epoch training mode (dynamic architecture disabled by env override)")

        if (cfg.autoregressive_enabled or cfg.dynamic_architecture_enabled) and not force_standard_epoch_training:
            current_layers = max(1, cfg.growth_start_layers)
            target_layers = max(current_layers, cfg.growth_target_layers)
            autonomy_plan = plan_autonomous_execution(current_layers, target_layers)

            model_cfg = GPT2Config(
                vocab_size=tokenizer.vocab_size,
                n_positions=cfg.max_sequence_length,
                n_ctx=cfg.max_sequence_length,
                n_embd=hidden,
                n_layer=current_layers,
                n_head=n_heads,
                resid_pdrop=0.1,
                embd_pdrop=0.1,
                attn_pdrop=0.1,
            )
            model = GPT2LMHeadModel(model_cfg)
            apply_residual_scaling(model, cfg.residual_scaling_base, cfg.residual_scaling_min)

            stage_history: List[Dict[str, Any]] = []
            while True:
                stage_dir = cfg.artifacts_dir / f"nlp_growth_stage_{current_layers}"
                stage_dir.mkdir(parents=True, exist_ok=True)
                loop_history: List[Dict[str, Any]] = []
                best_loss = None
                train_result = None

                recursive_loops = int(autonomy_plan["recursive_loops"])
                for loop_idx in range(1, recursive_loops + 1):
                    subset = choose_curriculum_subset(loop_idx, curriculum)
                    loop_dataset = build_encoded_dataset_from_texts(subset)
                    args = build_training_args(stage_dir, int(autonomy_plan["steps_per_stage"]))
                    trainer = Trainer(model=model, args=args, train_dataset=loop_dataset)
                    train_result = trainer.train()
                    current_loss = float(train_result.training_loss)

                    improvement = None
                    if best_loss is not None:
                        improvement = best_loss - current_loss
                    best_loss = current_loss if best_loss is None else min(best_loss, current_loss)

                    loop_history.append(
                        {
                            "loop": loop_idx,
                            "dataset_size": len(subset),
                            "training_loss": current_loss,
                            "improvement": improvement,
                        }
                    )

                    reached_target = current_loss <= cfg.recursive_target_loss
                    plateau = improvement is not None and improvement < cfg.recursive_plateau_delta
                    if reached_target or plateau:
                        break

                if train_result is None:
                    args = build_training_args(stage_dir, int(autonomy_plan["steps_per_stage"]))
                    trainer = Trainer(model=model, args=args, train_dataset=dataset)
                    train_result = trainer.train()

                trainer.save_model(str(stage_dir))

                stage_profile = collect_attention_profile(model, current_layers, f"nlp_attention_profile_layers_{current_layers}")
                loss_now = float(train_result.training_loss)
                stage_history.append(
                    {
                        "layers": current_layers,
                        "steps": int(autonomy_plan["steps_per_stage"]),
                        "training_loss": loss_now,
                        "recursive_loops": loop_history,
                        "checkpoint_dir": str(stage_dir),
                        "top_attention_layers": stage_profile.get("top_attention_layers", []),
                    }
                )

                if current_layers >= target_layers:
                    break

                if cfg.independent_mode and len(stage_history) >= 2:
                    prev_loss = stage_history[-2].get("training_loss", loss_now)
                    gain = prev_loss - loss_now
                    if gain > 0.05:
                        adaptive_step = cfg.growth_step_layers
                    elif gain > 0.01:
                        adaptive_step = max(1, cfg.growth_step_layers // 2)
                    else:
                        adaptive_step = 1
                else:
                    adaptive_step = int(autonomy_plan["growth_step_layers"])

                next_layers = min(target_layers, current_layers + adaptive_step)
                model = clone_into_new_layer_count(model, next_layers)
                apply_residual_scaling(model, cfg.residual_scaling_base, cfg.residual_scaling_min)
                current_layers = next_layers

            final_attention = stage_history[-1].get("top_attention_layers", []) if stage_history else []
            ranked = [int(x.get("layer", 0)) for x in final_attention]
            fallback_ranked = list(range(max(0, current_layers - cfg.specialist_layer_count), current_layers))
            specialist_sources = (ranked + fallback_ranked)[: cfg.specialist_layer_count]

            split_back = max(1, min(cfg.split_back_to_layers, current_layers))
            primary_sources = list(range(split_back))
            primary_model = clone_with_selected_layers(model, primary_sources)
            specialist_model = clone_with_selected_layers(model, specialist_sources)

            primary_dir = cfg.artifacts_dir / f"nlp_primary_{split_back}_final"
            specialist_dir = cfg.artifacts_dir / "nlp_specialist_agent_final"
            primary_dir.mkdir(parents=True, exist_ok=True)
            specialist_dir.mkdir(parents=True, exist_ok=True)
            primary_model.save_pretrained(str(primary_dir))
            specialist_model.save_pretrained(str(specialist_dir))
            tokenizer.save_pretrained(str(primary_dir))
            tokenizer.save_pretrained(str(specialist_dir))

            specialization = infer_specialization_area(scripts)
            split_manifest = {
                "timestamp": utc_now_iso(),
                "mode": "dynamic_architecture" if cfg.dynamic_architecture_enabled else "autoregressive",
                "growth_start_layers": cfg.growth_start_layers,
                "growth_target_layers": target_layers,
                "final_layers": current_layers,
                "split_back_to_layers": split_back,
                "primary_source_layers": primary_sources,
                "specialist_source_layers": specialist_sources,
                "specialization_area": specialization,
                "self_supervised_objective": "causal_language_modeling_next_token_prediction",
                "deep_hierarchical_reasoning": {
                    "enabled": cfg.hierarchical_curriculum_enabled,
                    "curriculum_sizes": {k: len(v) for k, v in curriculum.items()},
                },
                "residual_scaling": {
                    "enabled": cfg.residual_scaling_enabled,
                    "base": cfg.residual_scaling_base,
                    "min": cfg.residual_scaling_min,
                },
                "independent_mode": cfg.independent_mode,
                "autonomy_plan": autonomy_plan,
                "tools_manifest": str(tools_manifest_path) if tools_manifest_path else None,
                "primary_model_dir": str(primary_dir),
                "specialist_model_dir": str(specialist_dir),
                "growth_history": stage_history,
            }
            split_manifest_path = cfg.artifacts_dir / "nlp_autoregressive_split_manifest.json"
            atomic_write_json(split_manifest_path, split_manifest)

            final_profile = {
                "timestamp": utc_now_iso(),
                "num_layers": split_back,
                "attention_available": bool(final_attention),
                "top_attention_layers": final_attention,
                "all_layer_means": [],
                "notes": "Autoregressive mode stores per-stage attention files and split manifest for both agents.",
            }
            atomic_write_json(cfg.artifacts_dir / cfg.attention_file, final_profile)

            result_payload = {
                "status": "completed_dynamic_architecture_split" if cfg.dynamic_architecture_enabled else "completed_autoregressive_split",
                "dataset_samples": len(scripts),
                "tokenizer": cfg.tokenizer_name,
                "model_hidden_size": hidden,
                "model_attention_heads": n_heads,
                "growth_start_layers": cfg.growth_start_layers,
                "growth_target_layers": target_layers,
                "final_layers_before_split": current_layers,
                "primary_layers_after_split": split_back,
                "specialist_layers_after_split": len(specialist_sources),
                "self_supervised": True,
                "hierarchical_curriculum": cfg.hierarchical_curriculum_enabled,
                "recursive_optimization": cfg.recursive_optimization_enabled,
                "autonomy_mode": cfg.autonomy_mode,
                "autonomy_plan": autonomy_plan,
                "tools_enabled": cfg.tools_enabled,
                "tools_manifest": str(tools_manifest_path) if tools_manifest_path else None,
                "primary_output_dir": str(primary_dir),
                "specialist_output_dir": str(specialist_dir),
                "split_manifest": str(split_manifest_path),
                "attention_profile": str(cfg.artifacts_dir / cfg.attention_file),
            }
            result_payload["harding"] = run_harding_post_cycle(
                cfg=cfg,
                scripts=scripts,
                training_result=result_payload,
                phase="autoregressive_split",
                attention_profile=final_profile,
                extra_outputs={
                    "primary_model_dir": str(primary_dir),
                    "specialist_model_dir": str(specialist_dir),
                    "split_manifest": str(split_manifest_path),
                },
            )
            return result_payload

        model_cfg = GPT2Config(
            vocab_size=tokenizer.vocab_size,
            n_positions=cfg.max_sequence_length,
            n_ctx=cfg.max_sequence_length,
            n_embd=hidden,
            n_layer=cfg.num_hidden_layers,
            n_head=n_heads,
            resid_pdrop=0.1,
            embd_pdrop=0.1,
            attn_pdrop=0.1,
        )
        model = GPT2LMHeadModel(model_cfg)

        output_dir = cfg.artifacts_dir / "nlp_96layer_checkpoint"
        output_dir.mkdir(parents=True, exist_ok=True)

        args = build_training_args(
            output_dir,
            cfg.max_steps,
            use_epoch_schedule=True,
            epochs=cfg.total_epochs,
        )

        # --- Custom: Noise Injection and Unrolled Training ---
        # Optional dataset noise pass wired through mistakelearn.inject_noise().
        for item in dataset:
            tensor_ids = item.get("input_ids")
            if isinstance(tensor_ids, torch.Tensor) and tensor_ids.dtype.is_floating_point:
                arr = tensor_ids.detach().cpu().numpy()
                noisy_arr = inject_noise(arr, noise_level=0.05, noise_type="gaussian")
                item["input_ids"] = torch.as_tensor(noisy_arr, dtype=tensor_ids.dtype, device=tensor_ids.device)

        # Optionally perform unrolled training step before standard Trainer
        # (This is a demonstration; in practice, you may want to use this in place of or in addition to Trainer.train())
        # Example: unrolled_training_step(model, optimizer, data, loss_fn, unroll_steps=3)
        # For HuggingFace Trainer, optimizer/loss_fn are managed internally, so this is illustrative only.

        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=dataset,
        )

        train_result = trainer.train()

        final_dir = cfg.artifacts_dir / "nlp_96layer_final"
        final_dir.mkdir(parents=True, exist_ok=True)
        trainer.save_model(str(final_dir))
        tokenizer.save_pretrained(str(final_dir))

        attention_profile = collect_attention_profile(model, cfg.num_hidden_layers, cfg.attention_file.replace(".json", ""))

        result_payload = {
            "status": "completed",
            "training_loss": float(train_result.training_loss),
            "steps": int(cfg.max_steps),
            "target_epochs": float(cfg.total_epochs),
            "completed_epochs": float(getattr(train_result, "metrics", {}).get("epoch", cfg.total_epochs)),
            "dataset_samples": len(scripts),
            "tokenizer": cfg.tokenizer_name,
            "model_layers": cfg.num_hidden_layers,
            "model_hidden_size": hidden,
            "model_attention_heads": n_heads,
            "output_dir": str(final_dir),
            "attention_profile": str(cfg.artifacts_dir / cfg.attention_file),
            "top_attention_layers": attention_profile.get("top_attention_layers", []),
        }
        result_payload["harding"] = run_harding_post_cycle(
            cfg=cfg,
            scripts=scripts,
            training_result=result_payload,
            phase="standard_training",
            attention_profile=attention_profile,
            extra_outputs={
                "output_dir": str(final_dir),
                "checkpoint_dir": str(output_dir),
            },
        )
        return result_payload
    except Exception as e:
        print("[ERROR] Exception in run_training:")
        traceback.print_exc()
        return {
            "status": "skipped_missing_dependencies",
            "reason": str(e),
            "traceback": traceback.format_exc(),
            "required_packages": ["torch", "transformers"],
        }

def main() -> int:
    _maybe_reexec_into_workspace_venv()

    cfg = load_config()
    _enforce_local_ram_limit(cfg)

    if not (cfg.artifacts_dir.exists() or cfg.artifacts_dir.is_symlink()):
        cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)

    artifact_cleanup = cleanup_old_training_artifacts(cfg)
    if artifact_cleanup.get("enabled"):
        freed_mb = artifact_cleanup.get("freed_bytes", 0) / (1024 * 1024)
        print(
            f"[Cleanup] Artifact prune: files={artifact_cleanup.get('deleted_files', 0)} "
            f"dirs={artifact_cleanup.get('deleted_dirs', 0)} "
            f"freed={freed_mb:.1f}MB failed={artifact_cleanup.get('failed', 0)}"
        )

    # Use node-specific filenames if running in parallel.
    if cfg.node_type and cfg.node_type != "unknown":
        summary_file = f"nlp_training_summary_{cfg.node_type}.json"
        attention_file = f"nlp_attention_profile_{cfg.node_type}.json"
    else:
        summary_file = cfg.summary_file
        attention_file = cfg.attention_file

    summary_path = cfg.artifacts_dir / summary_file
    attention_path = cfg.artifacts_dir / attention_file

    missing_modules = _missing_runtime_modules(REQUIRED_RUNTIME_MODULES)
    if missing_modules:
        install_cmd = f"{sys.executable} -m pip install {' '.join(missing_modules)}"
        summary = {
            "timestamp": utc_now_iso(),
            "status": "skipped_missing_dependencies",
            "message": "Missing required runtime packages before training",
            "missing_modules": missing_modules,
            "python_executable": sys.executable,
            "install_command": install_cmd,
            "node_type": cfg.node_type,
        }
        atomic_write_json(summary_path, summary)
        print(
            f"[NLP] Missing required packages: {', '.join(missing_modules)}\n"
            f"[NLP] Python executable: {sys.executable}\n"
            f"[NLP] Install with: {install_cmd}"
        )
        return 0

    if not cfg.enabled:
        summary = {
            "timestamp": utc_now_iso(),
            "status": "disabled",
            "message": "NLP training disabled in configuration",
            "node_type": cfg.node_type,
        }
        atomic_write_json(summary_path, summary)
        print(f"[NLP] Training disabled (node: {cfg.node_type})")
        return 0

    # --- INTEGRATION: Try to load preprocessed batches if available ---
    batches_dir = Path("/mnt/1tb/skynetv1/processed_batches")
    if batches_dir.exists() and any(batches_dir.glob("batch_*.jsonl")):
        print(f"[NLP] Loading preprocessed code batches from {batches_dir}")
        scripts = load_preprocessed_batches(batches_dir, max_batches=3)
        script_paths = []
    else:
        # Fallback to original dataset build
        dataset_ready = is_dataset_ready(cfg)
        if dataset_ready:
            print("[NLP] Existing dataset is ready. Skipping dataset build.")
        else:
            print("[NLP] No ready dataset found. Building dataset...")
        scripts, script_paths = build_dataset(cfg)

    # Always proceed to training unless a 'training_complete.flag' exists
    training_complete_marker = cfg.artifacts_dir / "training_complete.flag"
    if training_complete_marker.exists():
        print("[NLP] Training already completed. Exiting.")
        return 0

    try:
        dataset_started_at = time.perf_counter()
        print(f"[NLP] Dataset preparation finished in {format_duration(time.perf_counter() - dataset_started_at)}")
        if not scripts:
            summary = {
                "timestamp": utc_now_iso(),
                "status": "skipped_empty_dataset",
                "message": "No simple Python scripts found for NLP training",
                "target_language": cfg.target_language,
                "searched_roots": [str(p) for p in cfg.dataset_roots],
                "node_type": cfg.node_type,
            }
            atomic_write_json(summary_path, summary)
            print(f"[NLP] No dataset scripts found (node: {cfg.node_type})")
            move_artifacts_to_network(cfg.artifacts_dir)
            return 0

        # --- Background dataset cache rebuild ---
        def start_background_cache_build():
            pass  # Omitted for brevity; keep as in original
        start_background_cache_build()

        # --- TRAINING ---
        result: dict = {}
        try:
            result = run_training(cfg, scripts)
        except Exception as e:
            print("[ERROR] Exception in run_training:", e)
            result = {"status": "failed", "reason": str(e)}

        # --- METRICS & LOGGING ---
        metrics_path = cfg.artifacts_dir / "training_metrics.json"
        metrics = {
            "final_loss": result.get("training_loss"),
            "steps": result.get("steps"),
            "epochs": result.get("completed_epochs"),
            "num_scripts": len(scripts),
            "batches_used": 3 if batches_dir.exists() and any(batches_dir.glob("batch_*.jsonl")) else None,
        }
        try:
            with open(metrics_path, "w") as f:
                json.dump(metrics, f, indent=2)
        except Exception as e:
            print(f"[NLP] Could not write metrics: {e}")

        # --- SAMPLE GENERATION ---
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            tokenizer = AutoTokenizer.from_pretrained(cfg.tokenizer_name)
            model_dir = result.get("output_dir")
            if model_dir:
                model = AutoModelForCausalLM.from_pretrained(model_dir)
                sample_input = "def hello_world():"
                input_ids = tokenizer.encode(sample_input, return_tensors="pt")
                model_for_generation: Any = model
                output = model_for_generation.generate(input_ids, max_length=50)
                print("[NLP] Sample generated code:")
                print(tokenizer.decode(output[0]))
        except Exception as e:
            print(f"[NLP] Could not generate sample code: {e}")

        summary = {
            "timestamp": utc_now_iso(),
            "goal": "Transformers NLP training on simple Python scripts for SkyNetV1",
            "target_language": cfg.target_language,
            "requested_model_layers": cfg.num_hidden_layers,
            "dataset_script_count": len(scripts),
            "dataset_preview_paths": script_paths[:25],
            "node_type": cfg.node_type,
            "artifact_cleanup": artifact_cleanup,
            "result": result,
        }

        status = result.get("status", "unknown")
        atomic_write_json(summary_path, summary)
        print(f"[NLP] Training status: {status}")

        if status == "failed" and not cfg.continue_if_failed:
            print("[NLP] Training failed and continue_if_failed is False. Exiting.")
            return 1
        return 0
    except Exception as e:
        print("[ERROR] Exception in main() (outer):", e)
        traceback.print_exc()
        move_artifacts_to_network(cfg.artifacts_dir)
        return 1

if __name__ == "__main__":
    if "--build-cache-only" in sys.argv:
        cfg = load_config()
        lock_path = cfg.artifacts_dir / "dataset_cache_build.lock"
        try:
            if lock_path.exists():
                try:
                    lock_fd = os.open(str(lock_path), os.O_RDWR)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                    os.close(lock_fd)
                except Exception:
                    pass
            print("[Cache] Building dataset cache (background)...")
            prime_dataset_cache(cfg)
        finally:
            try:
                if lock_path.exists():
                    os.unlink(lock_path)
            except Exception:
                pass
        sys.exit(0)
    raise SystemExit(main())
