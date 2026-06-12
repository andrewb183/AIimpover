#!/usr/bin/env python3
import asyncio
import json
import os
import gc
import importlib
from pathlib import Path
from itertools import count
import time
from tempfile import NamedTemporaryFile
from tqdm import tqdm
import psutil  # optional: monitor RAM
import requests  # health pings
import socket
import subprocess
import fcntl  # file locking
import signal
import sys
import hashlib
from datetime import datetime
from urllib.parse import urlparse

# Add portable paths for mk14 import (works on pi, pi1, and Docker/NFS mounts)
for _p in [
    '/mnt/shared/create',
    '/mnt/shared/oldtimes/create',
    '/mnt/shared/nfs_shared/oldtimes/create',
    '/home/pi1/Desktop/test/nfs_shared/oldtimes/create',
    '/oldtimes',
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
from mk14 import CodeImplementer as Mk14Implementer

# Import path manager for dual-location (1TB + local) file access
try:
    from path_manager import PathManager, get_output_path, get_ideas_log_path, get_qa_issue_path, get_incomplete_code_log_path, get_worker_status_path, get_retry_queue_path
    HAS_PATH_MANAGER = True
except ImportError:
    HAS_PATH_MANAGER = False
    tqdm.write("⚠️  path_manager not available - using local paths")

# Import config and Redis for Swarm
try:
    from config_loader import ConfigLoader
    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False
    tqdm.write("⚠️  config_loader not available - using fallback defaults")

HAS_REDIS = False

# Import node bootstrap for GPU detection
try:
    from node_bootstrap import register_node_labels, label_swarm_node, detect_amd_gpu
    HAS_NODE_BOOTSTRAP = True
except ImportError:
    HAS_NODE_BOOTSTRAP = False
    tqdm.write("⚠️  node_bootstrap not available - GPU detection disabled")

# Import escalating retry system for incomplete code handling
try:
    from escalating_retry_system import escalate_retry_for_project, LearningFixDatabase
    HAS_ESCALATION = True
except ImportError:
    HAS_ESCALATION = False
    tqdm.write("⚠️  escalating_retry_system not available - incomplete code will use basic routing")

# Import escalation limiter to prevent infinite loops
try:
    from escalation_limiter import EscalationLimiter, RootCauseAnalyzer, AutoFileLinker
    ESCALATION_LIMITER = EscalationLimiter()
    HAS_ESCALATION_LIMITER = True
except ImportError:
    HAS_ESCALATION_LIMITER = False
    ESCALATION_LIMITER = None
    tqdm.write("⚠️  escalation_limiter not available - infinite loop protection disabled")

# -------------------- Config & Swarm Setup --------------------
# Load config from Docker Swarm config or local fallback
if HAS_CONFIG:
    CONFIG = ConfigLoader.load_config()
    REDIS_CONFIG = ConfigLoader.get_section("redis") or {}
    NODE_CONFIG = ConfigLoader.get_section("node") or {}
    REHYDRATION_CONFIG = ConfigLoader.get_section("rehydration") or {}
    USE_REDIS = bool(REDIS_CONFIG.get("host") and REHYDRATION_CONFIG.get("enabled", True))
    GPU_CONFIG = ConfigLoader.get_section("gpu") or {}
    MODEL_CONFIG = ConfigLoader.get_section("models") or {}
    TIMEOUT_CONFIG = ConfigLoader.get_section("timeouts") or {}
else:
    CONFIG = {}
    REDIS_CONFIG = {}
    NODE_CONFIG = {}
    REHYDRATION_CONFIG = {}
    USE_REDIS = False
    GPU_CONFIG = {}
    MODEL_CONFIG = {}
    TIMEOUT_CONFIG = {}

# Initialize Redis client if available
REDIS_CLIENT = None
if USE_REDIS:
    try:
        redis_module = importlib.import_module("redis")
        HAS_REDIS = True
        REDIS_CLIENT = redis_module.Redis(
            host=REDIS_CONFIG.get("host", "redis"),
            port=REDIS_CONFIG.get("port", 6379),
            db=REDIS_CONFIG.get("db", 0),
            decode_responses=True,
            socket_connect_timeout=REDIS_CONFIG.get("socket_connect_timeout", 5),
            socket_keepalive=True,
        )
        # Test connection
        REDIS_CLIENT.ping()
        tqdm.write("✅ Redis connected")
    except ImportError:
        tqdm.write("⚠️  redis not available - falling back to file-based queues")
        HAS_REDIS = False
        REDIS_CLIENT = None
        USE_REDIS = False
    except Exception as e:
        tqdm.write(f"⚠️  Redis connection failed: {e} - falling back to file-based queues")
        REDIS_CLIENT = None
        USE_REDIS = False

# Node bootstrap - register this node if on Swarm
if HAS_NODE_BOOTSTRAP and NODE_CONFIG.get("autolabel"):
    try:
        hostname = socket.gethostname()
        gpu_present = detect_amd_gpu(GPU_CONFIG)
        tqdm.write(f"🖥️  Node: {hostname}, GPU: {'Yes' if gpu_present else 'No'}")
        if REDIS_CLIENT:
            labels = register_node_labels(REDIS_CLIENT, None, hostname, CONFIG)
            if labels:
                label_swarm_node(hostname, labels)
                tqdm.write(f"✅ Node registered in Redis and Swarm")
    except Exception as e:
        tqdm.write(f"⚠️  Node bootstrap failed: {e}")

NUM_WORKERS = 7                       # modest async bump for better throughput without overrunning Pi memory
JOB_QUEUE = asyncio.PriorityQueue(maxsize=30)  # absorb small bursts from idea generators without dropping fast tasks
SLOW_QUEUE = asyncio.PriorityQueue(maxsize=100)  # give heavy work more headroom so it doesn't stall enqueueing
SLOW_TASK_LOCK = asyncio.Lock()                 # serialize slow tasks
IMPLEMENTATIONS_DIR = "./implementations"  # where JSON tasks land (legacy local)

# Primary output directories - Use path_manager for 1TB + local dual-location
if HAS_PATH_MANAGER:
    OUTPUT_PROJECT_DIR = str(get_output_path())  # 1TB mount
    IDEAS_LOG_PATH = get_ideas_log_path()
    QA_ISSUE_PATH = get_qa_issue_path()
    INCOMPLETE_CODE_LOG = get_incomplete_code_log_path()
else:
    # Fallback to local paths if path_manager not available
    OUTPUT_PROJECT_DIR = "./implementation_outputs"
    IDEAS_LOG_PATH = Path(__file__).with_name("ideas_log.json")
    QA_ISSUE_PATH = Path(__file__).with_name("QAissue.json")
    INCOMPLETE_CODE_LOG = Path(__file__).with_name("incomplete_code_log.json")

RAM_THRESHOLD_MB = 16000              # optional: max RAM before pausing queue
CHECK_RAM_INTERVAL = 5                # seconds - avoid hammering psutil in the worker loop
IDLE_GRACE_SECONDS = 10               # seconds to wait after queue is empty before shutting down
REDIS_IDEA_BATCH_SIZE = 5             # batch a few Redis dequeues per poll to reduce queue latency

# Heavy projects that timeout on Raspberry Pi
HEAVY_PROJECT_PATTERNS = {
    "compression", "encryption", "image_processing", "video",
    "machine_learning", "neural_network", "deep_learning",
    "sorting_network", "huffman", "lz77", "deflate",
    "rsa", "aes", "sha", "md5", "hash",
    "ocr", "face_recognition", "object_detection",
    "3d_", "graphics", "rendering", "ray_tracing",
}

def should_skip_heavy_project(idea: dict) -> bool:
    """Check if project is too heavy for Raspberry Pi to complete in time."""
    title = (idea.get("title") or "").lower()
    language = (idea.get("language") or "python").lower()

    # Skip heavy projects with heavy languages
    if language in {"c++", "rust", "java"}:
        for pattern in HEAVY_PROJECT_PATTERNS:
            if pattern in title:
                return True

    return False

# Per-language timeout configuration (in seconds)
# Fast languages get 5-10 min caps; heavy get 30-120 min
LANGUAGE_TIMEOUT_SECONDS = {
    "python": 5 * 60,         # 5 minutes - fast, test-friendly
    "javascript": 5 * 60,     # 5 minutes - fast, test-friendly
    "go": 8 * 60,             # 8 minutes - moderate compilation (reduced for RPi)
    "c#": 10 * 60,            # 10 minutes - .NET builds on RPi (reduced)
    "java": 12 * 60,          # 12 minutes - JVM startup on RPi (reduced)
    "c++": 15 * 60,           # 15 minutes - heavy compilation on RPi (reduced from 60)
    "rust": 20 * 60,          # 20 minutes - Rust on RPi (reduced from 120)
}
WORKER_TIMEOUT_SECONDS = 3 * 60      # 3 minutes - kill stuck workers faster

IDEA_LOG_LOCK = asyncio.Lock()
QA_ISSUE_LOCK = asyncio.Lock()
INCOMPLETE_LOG_LOCK = asyncio.Lock()  # lock for incomplete code log
SEQ = count()  # monotonic sequence to break priority ties
WORKER_TASKS = {}                     # track worker asyncio tasks for timeout management

# Status file - use path_manager for 1TB mount
if HAS_PATH_MANAGER:
    STATUS_FILE = get_worker_status_path()
else:
    STATUS_FILE = Path(__file__).with_name("worker2_status.json")

STATUS_WRITE_MIN_INTERVAL = int(os.environ.get("WORKER2_STATUS_MIN_INTERVAL", "30"))  # 30 seconds - keep monitor fresh
_LAST_STATUS_WRITE = 0.0
IDEAS_LOG_LAST_SIZE = 0               # track number of ideas processed (count)
QA_ISSUE_LAST_SIZE = 0               # track number of QA issues processed (count)
IDEAS_LOG_LAST_MTIME = 0             # track file modification time for polling
QA_ISSUE_LAST_MTIME = 0              # track file modification time for polling

# Escalating retry system initialization
LEARNING_DB = LearningFixDatabase() if HAS_ESCALATION else None  # track learned fixes

# Model health + prioritization
DEFAULT_MODEL_ENDPOINTS = {
    "qwen2.5-coder": "http://localhost:11435",
    "deepseek-r1": "http://localhost:11437",
}
CONFIG_MODEL_ENDPOINTS = (MODEL_CONFIG.get("endpoints") or {}) if isinstance(MODEL_CONFIG, dict) else {}
MODEL_ENDPOINTS = {
    "qwen2.5-coder": os.environ.get("OLLAMA_QWEN_ENDPOINT") or CONFIG_MODEL_ENDPOINTS.get("qwen2.5-coder") or DEFAULT_MODEL_ENDPOINTS["qwen2.5-coder"],
    "deepseek-r1": os.environ.get("OLLAMA_DEEPSEEK_ENDPOINT") or CONFIG_MODEL_ENDPOINTS.get("deepseek-r1") or DEFAULT_MODEL_ENDPOINTS["deepseek-r1"],
}
# Initialize as True - will be checked by monitor_models()
MODEL_HEALTH = {"qwen2.5-coder": True, "deepseek-r1": True}
PREFERRED_MODEL = None  # set to "deepseek-r1" when it becomes healthy
COMPLEXITY_THRESHOLD = int(os.environ.get("WORKER2_COMPLEXITY_THRESHOLD", "2500"))

# Concurrency throttling for same-project escalations
# Track how many workers are currently processing variations of the same base project
ACTIVE_BASE_PROJECTS = {}  # {base_project_name: count}
MAX_CONCURRENT_SAME_PROJECT = 3  # Max 3 workers on same failed project

# Worker status tracking for monitor
WORKER_STATUS = {
    i: {
        "status": "idle",
        "task": None,
        "started_at": None,
        "preferred_model": None,
        "language": "python",  # Track task language for per-language timeout
        "last_completed": None,
    }
    for i in range(NUM_WORKERS)  # Initialize for all workers (6, not 2)
}

async def _is_port_open(port: int, timeout: float = 1.5) -> bool:
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: _sync_port_check(port, timeout))
    except Exception:
        return False

def _sync_endpoint_check(endpoint: str, timeout: float = 1.5) -> bool:
    """Auto-generated docstring."""
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

async def _is_endpoint_open(endpoint: str, timeout: float = 1.5) -> bool:
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: _sync_endpoint_check(endpoint, timeout))
    except Exception:
        return False

async def _ping_model(model: str, endpoint: str) -> bool:
    try:
        loop = asyncio.get_running_loop()
        def _req():
            """Auto-generated docstring."""
            return requests.post(
                f"{endpoint}/api/generate",
                json={"model": model, "prompt": "ping", "stream": False, "options": {"num_predict": 1}},
                timeout=5,
            )
        resp = await loop.run_in_executor(None, _req)
        return resp.status_code == 200
    except Exception:
        return False

def select_model_for_worker(worker_id: int):
    """Assign models per worker.

    worker0: deepseek-r1 if healthy else qwen
    worker1+: qwen if healthy else deepseek
    """
    deepseek_ok = MODEL_HEALTH.get("deepseek-r1")
    qwen_ok = MODEL_HEALTH.get("qwen2.5-coder")

    if worker_id == 0:
        if deepseek_ok:
            return "deepseek-r1"
        if qwen_ok:
            return "qwen2.5-coder"
        return None

    # others prefer qwen
    if qwen_ok:
        return "qwen2.5-coder"
    if deepseek_ok:
        return "deepseek-r1"
    return None

def estimate_task_complexity(idea: dict) -> int:
    """Rough complexity score based on input size and language."""
    title = (idea.get("title") or "")
    description = (idea.get("description") or "")
    code = (idea.get("code") or "")
    sample_code = (idea.get("sample_code") or idea.get("example_code") or "")
    language = (idea.get("language") or "python").lower()

    score = len(title) + len(description) + len(code) + len(sample_code)
    if idea.get("is_escalated_retry"):
        score += 800
    if language in {"c++", "rust", "java", "c#", "go"}:
        score += 400
    return score

def select_model_for_idea(worker_id: int, idea: dict):
    """Route tasks to qwen or deepseek based on complexity and overrides."""
    forced = idea.get("force_model")
    if forced and MODEL_HEALTH.get(forced):
        return forced

    complexity = estimate_task_complexity(idea)
    deepseek_ok = MODEL_HEALTH.get("deepseek-r1")
    qwen_ok = MODEL_HEALTH.get("qwen2.5-coder")

    if complexity >= COMPLEXITY_THRESHOLD:
        if deepseek_ok:
            return "deepseek-r1"
        if qwen_ok:
            return "qwen2.5-coder"
        return None

    # Low complexity: prefer qwen for speed
    if qwen_ok:
        return "qwen2.5-coder"
    if deepseek_ok:
        return "deepseek-r1"
    return select_model_for_worker(worker_id)

def get_timeout_for_language(language: str) -> int:
    """Get per-language timeout in seconds.

    Fast languages (Python/JS) get 10 min; heavy get 30-120 min.
    """
    lang_lower = language.lower() if language else "python"
    return LANGUAGE_TIMEOUT_SECONDS.get(lang_lower, WORKER_TIMEOUT_SECONDS)

def update_status_file():
    """Write current queue and worker status to file for monitor."""
    try:
        global _LAST_STATUS_WRITE
        now = time.time()
        if STATUS_WRITE_MIN_INTERVAL > 0 and (now - _LAST_STATUS_WRITE) < STATUS_WRITE_MIN_INTERVAL:
            return

        # Get queue items (can't iterate PriorityQueue directly, so approximate)
        status_data = {
            "timestamp": time.time(),
            "queue_size": JOB_QUEUE.qsize(),
            "slow_queue_size": SLOW_QUEUE.qsize(),
            "workers": WORKER_STATUS.copy(),
            "model_health": MODEL_HEALTH.copy(),
            "preferred_model": PREFERRED_MODEL
        }
        _write_atomic_json(STATUS_FILE, status_data)
        _LAST_STATUS_WRITE = now
    except Exception:
        pass  # Don't crash if status update fails

def _write_atomic_json(path: Path, data):
    """Write JSON atomically (temp file + fsync + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None

    try:
        with NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as tmp:
            json.dump(data, tmp, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_name = tmp.name

        os.replace(temp_name, path)
    except Exception:
        # Silently fail - don't crash the worker
        pass
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except Exception:
                pass

def _read_json_locked(path: Path, default=None):
    """Read JSON file with exclusive lock to prevent concurrent access corruption.

    Supports dual-location reading: tries primary (1TB), then fallback (local).
    """
    # If path_manager available, check all possible locations
    if HAS_PATH_MANAGER and not path.exists():
        # Try to find file in fallback locations
        filename = path.name
        for alt_path in PathManager.get_all_locations(filename):
            if alt_path.exists():
                path = alt_path
                break

    if not path.exists():
        return default if default is not None else []

    try:
        with open(path, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared lock for reading
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        tqdm.write(f"⚠️ Error reading {path}: {e}")
        return default if default is not None else []

async def _atomic_update_json(path: Path, lock: asyncio.Lock, update_fn):
    """Threaded atomic update of a JSON file guarded by an asyncio lock."""
    async with lock:
        async def _update():
            try:
                current = _read_json_locked(path, [])
                new_data = await update_fn(current)
                _write_atomic_json(path, new_data)
                return None
            except Exception as e:
                return e

        err = await _update()
        if err:
            raise err

def detect_incomplete_code(code: str, language: str) -> bool:
    """Detect if code has TODO/unfinished markers indicating incomplete generation.

    Returns True if code is incomplete and should be flagged for regeneration.
    """
    if not code:
        return False

    incomplete_markers = [
        "# TODO",
        "// TODO",
        "/* TODO",
        "# FIXME",
        "// FIXME",
        "Complete implementation",
        "based on title requirements",
        "Your implementation here",
        "Add your code here",
        "SyntaxError:",  # Generated code with syntax errors
    ]

    code_lower = code.lower()
    for marker in incomplete_markers:
        if marker.lower() in code_lower:
            return True

    return False

async def log_incomplete_code(idea: dict, code: str, error_msg: str = ""):
    """Log incomplete/broken code to incomplete_code_log.json for manual review and fix attempts."""
    async def _log(current):
        entry = {
            "title": idea.get("title", "Unknown"),
            "language": idea.get("language", "unknown"),
            "detected_at": time.time(),
            "error": error_msg,
            "code_preview": code[:200] if code else "",  # First 200 chars
            "code_length": len(code) if code else 0,
            "retry_count": idea.get("retry_count", 0),
        }

        # Add to log
        if not isinstance(current, list):
            current = []

        # Check if already logged
        existing = [e for e in current if e.get("title") == entry["title"]]
        if not existing:
            current.append(entry)
            tqdm.write(f"📋 Logged incomplete code for '{entry['title']}' - will attempt regeneration")

        return current

    try:
        await _atomic_update_json(INCOMPLETE_CODE_LOG, INCOMPLETE_LOG_LOCK, _log)
    except Exception as e:
        tqdm.write(f"⚠️ Could not log incomplete code: {e}")

async def route_to_regeneration(idea: dict, code: str, error_msg: str):
    """Route incomplete code through escalating retry system for intelligent regeneration.

    CRITICAL CHANGES:
    1. Check escalation limiter - prevent infinite loops (max 8 attempts per project)
    2. Detect root cause issues that can't be fixed
    3. Auto-create missing files (HTML, CSS, config) needed for QA
    4. Abandon hopeless projects instead of flooding queue
    """
    project_title = idea.get("title", "Unknown")
    language = idea.get("language", "javascript")
    attempts = idea.get("attempts", 0)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 1: CHECK ESCALATION LIMITER (PREVENT INFINITE LOOPS)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if HAS_ESCALATION_LIMITER and ESCALATION_LIMITER:
        should_escalate, reason = ESCALATION_LIMITER.should_escalate(project_title)

        if not should_escalate:
            tqdm.write(f"🛑 ESCALATION LIMIT: {reason}")
            ESCALATION_LIMITER.mark_abandoned(project_title, reason)

            # Log to abandoned projects file
            async def _log_abandoned(current):
                if not isinstance(current, list):
                    current = []
                current.append({
                    'project': project_title,
                    'reason': reason,
                    'abandoned_at': datetime.now().isoformat(),
                    'attempts': attempts
                })
                return current

            try:
                await _atomic_update_json(
                    Path('implementation_outputs/abandoned_projects.json'),
                    asyncio.Lock(),
                    _log_abandoned
                )
            except Exception:
                pass

            return  # STOP - don't escalate further

        tqdm.write(f"✅ Escalation allowed: {reason}")

        # Log this error
        ESCALATION_LIMITER.log_error(project_title, error_msg, f"L{attempts % 4 + 1}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 2: DETECT UNFIXABLE ROOT CAUSES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    root_cause_analysis = RootCauseAnalyzer.analyze(error_msg, language, attempts)

    if root_cause_analysis['is_unfixable']:
        tqdm.write(f"🚨 ROOT CAUSE DETECTED: {root_cause_analysis['pattern']}")
        tqdm.write(f"   {root_cause_analysis['recommendation']}")

        ESCALATION_LIMITER.mark_abandoned(project_title, f"Root cause: {root_cause_analysis['pattern']}")
        return  # STOP - this project has a fundamental flaw

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 3: AUTO-CREATE MISSING FILES FOR QA
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    needed_files = AutoFileLinker.analyze_needs(project_title, code, language)

    if needed_files:
        tqdm.write(f"📁 Auto-creating {len(needed_files)} missing files for QA:")

        project_dir = Path(f'implementation_outputs/{project_title}')
        created = AutoFileLinker.create_missing_files(project_dir, needed_files, code)

        for file_name in created:
            tqdm.write(f"   ✅ Created: {file_name}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 4: ESCALATE WITH LIMITED RETRIES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if HAS_ESCALATION and LEARNING_DB:
        try:
            # Prepare error log for escalation context
            error_log = [
                {
                    "type": "incomplete_code",
                    "message": error_msg,
                    "code_length": len(code),
                    "detected_at": time.time(),
                }
            ]

            # Use escalating retry system (LIMITED to 8 variations instead of 20)
            escalated_ideas = escalate_retry_for_project(
                project_title,
                error_log,
                idea,
                LEARNING_DB
            )

            if escalated_ideas:
                # LIMIT: Only use first 2 escalations to prevent queue flooding
                escalated_ideas = escalated_ideas[:2]

                async def _add_escalated(current):
                    if not isinstance(current, list):
                        current = []

                    for escalated_idea in escalated_ideas:
                        # Check if already in queue
                        if not any(i.get("title") == escalated_idea.get("title") for i in current):
                            current.append(escalated_idea)

                    return current

                await _atomic_update_json(QA_ISSUE_PATH, QA_ISSUE_LOCK, _add_escalated)
                tqdm.write(f"✅ Created {len(escalated_ideas)} limited escalated variations (max 2 to prevent queue flooding)")

                return  # Success - escalation handled

        except Exception as e:
            tqdm.write(f"⚠️  Escalation failed: {e}, falling back to basic routing")
            error_msg_enhanced = error_msg

            # STEP 2: Escalate with enhanced context
            tqdm.write(f"📈 Escalating '{project_title}' through 4-level strategy with root cause fixes...")

            # Prepare error log for escalation context
            error_log = [
                {
                    "type": "incomplete_code",
                    "message": error_msg_enhanced,
                    "code_length": len(code),
                    "detected_at": time.time(),
                }
            ]

            # STEP 3: Integrate think mode for aggressive escalation levels
            try:
                from think_mode_escalation import ThinkModeEscalation

                think_mode = ThinkModeEscalation()
                has_critical = any(i['severity'] == 'critical' for i in analysis_result.get('issues', []))

                # Mark escalated ideas with think mode preference
                escalation_meta = {
                    'use_think_mode_l3_l4': True,
                    'critical_issues_detected': has_critical,
                    'think_reason': 'Nuclear/Aggressive escalation with deep reasoning for broken code'
                }
                tqdm.write(f"  💭 Think mode enabled for L3-L4 (aggressive/nuclear escalation)")
            except Exception as e:
                tqdm.write(f"⚠️ Think mode integration failed: {e}")
                escalation_meta = {}

            # Use escalating retry system to generate 20 variations
            escalated_ideas = escalate_retry_for_project(
                project_title,
                error_log,
                idea,
                LEARNING_DB
            )

            if escalated_ideas:
                # Add escalated ideas to QA issue queue
                async def _add_escalated(current):
                    if not isinstance(current, list):
                        current = []

                    for escalated_idea in escalated_ideas:
                        # Add think mode metadata
                        escalated_idea.update(escalation_meta)

                        # Check if already in queue
                        if not any(i.get("title") == escalated_idea.get("title") for i in current):
                            current.append(escalated_idea)

                    return current

                await _atomic_update_json(QA_ISSUE_PATH, QA_ISSUE_LOCK, _add_escalated)
                tqdm.write(f"✅ Created {len(escalated_ideas)} escalated variations for '{project_title}':")

                # Show escalation levels with think mode indicator
                levels = {}
                for esc_idea in escalated_ideas:
                    level = esc_idea.get("escalation_level", "Unknown")
                    levels[level] = levels.get(level, 0) + 1

                for level, count in sorted(levels.items()):
                    think_indicator = "💭" if level in ["Aggressive", "Nuclear"] else "  "
                    tqdm.write(f"   {think_indicator} {level}: {count} variations")

                return  # Success - escalation handled

        except Exception as e:
            tqdm.write(f"⚠️  Escalation failed: {e}, falling back to basic routing")

    # Fallback: Basic regeneration routing (no escalation)
    async def _route(current):
        if not isinstance(current, list):
            current = []

        # Create basic regeneration task
        regen_task = {
            "title": project_title,
            "description": f"REGENERATE: Incomplete code detected - {error_msg}",
            "code": code,
            "language": idea.get("language", "javascript"),
            "error_type": "incomplete_code",
            "last_error": f"Code contains TODO markers or syntax errors: {error_msg}",
            "first_attempt": time.time(),
            "last_attempt": time.time(),
            "retry_count": 0,
            "escalation_level": "basic_retry",  # Mark as non-escalated
        }

        # Add to QA issue queue
        current.append(regen_task)
        tqdm.write(f"🔄 Routed '{project_title}' to basic regeneration queue")

        return current

    try:
        await _atomic_update_json(QA_ISSUE_PATH, QA_ISSUE_LOCK, _route)
    except Exception as e:
        tqdm.write(f"⚠️ Could not route to regeneration: {e}")

def should_skip_completed(idea) -> bool:
    """Skip task if project_metadata.json on Desktop shows completed."""
    title = idea.get("title")
    if not title:
        return False
    project_name = title.replace(' ', '_').lower()
    desktop_dir = Path.home() / "Desktop"
    meta_path = desktop_dir / project_name / "project_metadata.json"
    try:
        if meta_path.exists():
            with open(meta_path, "r") as f:
                data = json.load(f)
                if data.get("status") == "completed":
                    tqdm.write(f"⏭️ Skipping completed project {title} (metadata found)")
                    return True
    except Exception:
        return False
    return False

def should_use_slow_queue(idea) -> bool:
    """Determine if task needs heavy processing (goes to SLOW_QUEUE).

    Tasks go to SLOW_QUEUE if:
    - Language is non-Python/JS (will skip heavy testing)
    - Task requires heavy healing (large projects, complex apps)

    Fast tasks (Python/JS) stay in main queue.
    """
    language = idea.get('language', 'Python').lower()
    code = idea.get('code', '')

    # Non-Python/JS languages skip testing, so they're lighter and go to slow queue
    if language not in ('python', 'javascript'):
        return True

    # Large code or complex-looking tasks might need heavy healing
    if len(code) > 2000:  # arbitrary threshold for "large"
        return True

    # Default: fast queue
    return False

def _extract_idea_timestamp(idea: dict):
    """Extract best-effort timestamp for oldest-first ordering."""
    if not isinstance(idea, dict):
        return float("inf")

    for key in ("created_at", "timestamp", "first_attempt", "last_attempted", "skipped_at", "completed_at"):
        value = idea.get(key)
        if value is None:
            continue

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue

    return float("inf")

def sort_ideas_oldest_first(ideas):
    """Stable oldest-first ordering with index fallback for identical/missing timestamps."""
    if not isinstance(ideas, list):
        return []

    indexed = list(enumerate(ideas))
    indexed.sort(key=lambda pair: (_extract_idea_timestamp(pair[1]), pair[0]))
    return [idea for _, idea in indexed]

async def update_status_periodically(interval: int = 30):
    """Periodically update status file to keep monitor fresh with live elapsed times."""
    while True:
        try:
            await asyncio.sleep(interval)
            update_status_file()
        except Exception:
            pass

async def monitor_worker_timeouts(interval: int = 30):
    """Monitor workers for timeout and restart them.

    Timeout is per-language:
    - Python/JS: 10 min
    - Go/C#/Java: 30-45 min
    - C++: 60 min
    - Rust: 120 min
    """
    while True:
        try:
            await asyncio.sleep(interval)
            current_time = time.time()

            for worker_id, status in WORKER_STATUS.items():
                if status['status'] == 'working' and status['started_at']:
                    elapsed = current_time - status['started_at']
                    task_name = status.get('task', 'Unknown')
                    language = status.get('language', 'python')
                    timeout_seconds = get_timeout_for_language(language)

                    if elapsed > timeout_seconds:
                        tqdm.write(f"⏰ Worker {worker_id} TIMEOUT after {elapsed/60:.1f}min on '{task_name}' ({language})")
                        tqdm.write(f"   (limit: {timeout_seconds/60:.0f}min for {language})")

                        tqdm.write(f"   Cancelling stuck worker {worker_id}...")

                        # Cancel the worker task
                        if worker_id in WORKER_TASKS:
                            WORKER_TASKS[worker_id].cancel()
                            tqdm.write(f"   ✓ Worker {worker_id} cancelled, will restart automatically")

                        # Reset worker status
                        WORKER_STATUS[worker_id].update({
                            "status": "timeout_restart",
                            "task": None,
                            "started_at": None,
                            "preferred_model": None,
                            "last_completed": f"TIMEOUT: {task_name}",
                        })
                        update_status_file()

        except Exception as e:
            tqdm.write(f"⚠️ Worker timeout monitor error: {e}")

async def monitor_models(interval: int = 10):
    """Periodically check model endpoints and adjust prioritization without excessive polling.

    - Prints health status changes (OK/DOWN/BUSY)
    - Prefers deepseek-r1 when it becomes healthy
    - If port is open, model is healthy (skip expensive ping for speed)
    """
    global PREFERRED_MODEL
    while True:
        try:
            for model, endpoint in MODEL_ENDPOINTS.items():
                # Fast endpoint check only (skip ping to avoid timeout delays)
                healthy = await _is_endpoint_open(endpoint)

                prev = MODEL_HEALTH.get(model)
                MODEL_HEALTH[model] = healthy
                if prev is not None and prev != healthy:
                    status = "OK" if healthy else "DOWN"
                    tqdm.write(f"🩺 Model health: {model} → {status} ({endpoint})")

            # Prefer deepseek when it is healthy
            if MODEL_HEALTH.get("deepseek-r1"):
                if PREFERRED_MODEL != "deepseek-r1":
                    PREFERRED_MODEL = "deepseek-r1"
                    tqdm.write("🎗 Prioritizing deepseek-r1 (worker0) while others use qwen")
                    await reprioritize_queue(new_priority=0)
            else:
                if PREFERRED_MODEL is not None:
                    PREFERRED_MODEL = None
                    tqdm.write("🎗 Preference cleared; both workers use qwen")
        except Exception as e:
            tqdm.write(f"⚠️ Model monitor error: {e}")
        finally:
            await asyncio.sleep(interval)

async def run_mk14_implementation(idea, worker_id, model_override=None, prune_after=True):
    """Run mk14's CodeImplementer in a thread to avoid blocking the event loop.

    Progress is saved back to ideas_log.json, not to separate files.
    """

    def _execute():
        """Auto-generated docstring."""
        idea_with_output = dict(idea)
        idea_with_output.setdefault("output_dir", OUTPUT_PROJECT_DIR)
        # Route model based on task complexity unless overridden
        preferred = model_override or select_model_for_idea(worker_id, idea_with_output)
        if preferred:
            idea_with_output["preferred_model"] = preferred
        impl = Mk14Implementer(idea_with_output)
        return impl.implement()

    title = idea.get('title', 'unknown')
    try:
        result_path = await asyncio.to_thread(_execute)
        tqdm.write(
            f"✅ Worker {worker_id} finished {title}"
            + (f" [{model_override}]" if model_override else "")
            + f" → {result_path}"
        )

        # Check if generated code is incomplete
        code = idea.get("code", "")
        if detect_incomplete_code(code, idea.get("language", "javascript")):
            tqdm.write(f"⚠️ Detected incomplete code in '{title}' - logging for regeneration")
            await log_incomplete_code(idea, code, "Contains TODO markers or unfinished placeholders")
            await route_to_regeneration(idea, code, "Incomplete code generation - needs full regeneration")
            # Mark as attempted in ideas_log.json
            await mark_idea_attempted(title, "incomplete", model_override or "unknown")
            # DON'T prune - keep for retry
            return

        # Mark as completed in ideas_log.json
        await mark_idea_completed(title, result_path, model_override or "unknown")

        if prune_after:
            await prune_idea_from_log(title)
    except Exception as e:
        # Save failure state back to ideas_log.json
        await mark_idea_failed(title, str(e), model_override or "unknown")

        # Feed retry failures to NN training immediately
        if idea.get("is_retry"):
            language = idea.get("language", "unknown")
            attempt = idea.get("retry_count", 0)
            await feed_retry_to_nn(title, language, str(e), attempt)

        raise

async def run_slow_task_twice(idea, worker_id, main_pbar, worker_pbar):
    """Process a slow task serially twice: deepseek-r1 then qwen2.5-coder."""
    async with SLOW_TASK_LOCK:
        models = ["deepseek-r1", "qwen2.5-coder"]
        worker_pbar.reset(total=len(models))
        last_completed_model = None

        for idx, model in enumerate(models):
            # Skip unhealthy model but continue to next
            if not MODEL_HEALTH.get(model):
                tqdm.write(f"⏭️ Skipping {model} for {idea.get('title')} (model unhealthy)")
                worker_pbar.update(1)
                continue

            # Update status for this model run
            WORKER_STATUS[worker_id].update(
                {
                    "status": "working",
                    "task": idea.get('title', 'Unknown'),
                    "started_at": time.time(),
                    "preferred_model": model,
                }
            )
            update_status_file()

            try:
                await run_mk14_implementation(
                    idea,
                    worker_id,
                    model_override=model,
                    prune_after=(idx == len(models) - 1),  # prune after final run
                )
                last_completed_model = model
            except Exception as e:
                tqdm.write(f"✗ Worker {worker_id} error on {model}: {e}")
            finally:
                worker_pbar.update(1)

        # Only count once on the main progress bar (task-level)
        main_pbar.update(1)

        # Reset status to idle after both passes
        WORKER_STATUS[worker_id].update(
            {
                "status": "idle",
                "task": None,
                "started_at": None,
                "preferred_model": None,
                "last_completed": f"{idea.get('title', 'Unknown')} [{last_completed_model or 'skipped'}]",
            }
        )
        update_status_file()

async def enqueue_task(idea, priority: int = 5):
    title = idea.get('title', 'unknown')

    # Fast path for escalated retries - skip all validation checks for speed
    # (QAissue items are retry/escalation tasks, not new/completed/heavy)
    if idea.get('is_escalated_retry'):
        # Route directly to queue without checks
        if should_use_slow_queue(idea):
            try:
                await SLOW_QUEUE.put((priority, next(SEQ), idea))
            except asyncio.QueueFull:
                pass  # Silent fail for full queue
        else:
            await JOB_QUEUE.put((priority, next(SEQ), idea))
        update_status_file()
        return  # Fast return - minimal logging

    # Slow path for new ideas - full validation
    if should_skip_completed(idea):
        tqdm.write(f"⏭️ Skipping completed: {title}")
        return

    # Check if project is too heavy for Raspberry Pi
    if should_skip_heavy_project(idea):
        language = idea.get('language', 'unknown')
        tqdm.write(f"⏭️ Skipping heavy project '{title}' ({language}) - would timeout on Raspberry Pi")
        # Mark as skipped in ideas_log.json
        await mark_idea_skipped(title, "Heavy project - would timeout on RPi")
        return

    # Route to appropriate queue
    if should_use_slow_queue(idea):
        try:
            await SLOW_QUEUE.put((priority, next(SEQ), idea))
            tqdm.write(f"📦 Task '{title}' → SLOW_QUEUE")
        except asyncio.QueueFull:
            tqdm.write(f"⚠️ SLOW_QUEUE full, skipping task: {title}")
    else:
        await JOB_QUEUE.put((priority, next(SEQ), idea))
        tqdm.write(f"📦 Task '{title}' → JOB_QUEUE")

    update_status_file()  # Update monitor on queue change

async def reprioritize_queue(new_priority: int = 0):
    """Drain and re-queue pending tasks with higher priority when deepseek recovers."""
    drained = []
    try:
        while True:
            item = JOB_QUEUE.get_nowait()
            drained.append(item)
    except asyncio.QueueEmpty:
        pass

    for _, _, idea in drained:
        await enqueue_task(idea, priority=new_priority)

    if drained:
        tqdm.write(f"🎗 Reprioritized {len(drained)} pending task(s) for deepseek-r1")

async def prune_idea_from_log(title):
    """Remove completed ideas from ideas_log.json to avoid repeats."""

    if not title:
        return

    async def _prune_file(path: Path, lock: asyncio.Lock):
        async def _update(current):
            return [idea for idea in current if idea.get("title") != title]

        try:
            await _atomic_update_json(path, lock, _update)
            return True
        except Exception as e:
            tqdm.write(f"⚠️ Could not prune '{title}' from {path.name} ({e})")
            return False

    removed_main = await _prune_file(IDEAS_LOG_PATH, IDEA_LOG_LOCK)
    await _prune_file(QA_ISSUE_PATH, QA_ISSUE_LOCK)

    if removed_main:
        tqdm.write(f"🧹 Removed entries for '{title}' from queues")

async def mark_idea_completed(title, result_path, model_used):
    """Mark idea as completed in both ideas_log.json and QAissue.json."""
    if not title:
        return

    try:
        # Sanitize title for matching (same as mk14 does for folder names)
        sanitized_title = title.replace(' ', '_').lower()

        # Try to update ideas_log.json
        current = _read_json_locked(IDEAS_LOG_PATH, [])
        updated = False
        for idea in current:
            idea_title = idea.get("title", "")
            if idea_title == title or idea_title.replace(' ', '_').lower() == sanitized_title:
                idea["status"] = "completed"
                idea["result_path"] = result_path
                idea["completed_at"] = time.time()
                idea["model_used"] = model_used
                updated = True
                break

        if updated:
            _write_atomic_json(IDEAS_LOG_PATH, current)

        # Also try to update QAissue.json (retry queue)
        current_qa = _read_json_locked(QA_ISSUE_PATH, [])
        updated_qa = False
        for idea in current_qa:
            idea_title = idea.get("title", "")
            if idea_title == title or idea_title.replace(' ', '_').lower() == sanitized_title:
                idea["status"] = "completed"
                idea["result_path"] = result_path
                idea["completed_at"] = time.time()
                idea["model_used"] = model_used
                updated_qa = True
                break

        if updated_qa:
            _write_atomic_json(QA_ISSUE_PATH, current_qa)

        if updated or updated_qa:
            tqdm.write(f"✅ Marked '{title}' as completed")
    except Exception as e:
        tqdm.write(f"⚠️ Could not mark '{title}' completed: {e}")

async def mark_idea_attempted(title, status, model_used):
    """Mark idea as attempted in both ideas_log.json and QAissue.json."""
    if not title:
        return

    try:
        # Try ideas_log.json
        current = _read_json_locked(IDEAS_LOG_PATH, [])
        updated = False
        for idea in current:
            if idea.get("title") == title:
                idea["status"] = status
                idea["last_attempted"] = time.time()
                idea["last_model"] = model_used
                idea["attempts"] = idea.get("attempts", 0) + 1
                updated = True
                break

        if updated:
            _write_atomic_json(IDEAS_LOG_PATH, current)

        # Also try QAissue.json
        current_qa = _read_json_locked(QA_ISSUE_PATH, [])
        updated_qa = False
        for idea in current_qa:
            if idea.get("title") == title:
                idea["status"] = status
                idea["last_attempted"] = time.time()
                idea["last_model"] = model_used
                idea["attempts"] = idea.get("attempts", 0) + 1
                updated_qa = True
                break

        if updated_qa:
            _write_atomic_json(QA_ISSUE_PATH, current_qa)

        if updated or updated_qa:
            tqdm.write(f"📝 Marked '{title}' as {status}")
    except Exception as e:
        tqdm.write(f"⚠️ Could not mark '{title}' as attempted: {e}")

async def mark_idea_failed(title, error_msg, model_used):
    """Mark idea as failed in both ideas_log.json and QAissue.json."""
    if not title:
        return

    try:
        # Try ideas_log.json
        current = _read_json_locked(IDEAS_LOG_PATH, [])
        updated = False
        for idea in current:
            if idea.get("title") == title:
                idea["status"] = "failed"
                idea["last_error"] = error_msg[:200]
                idea["last_attempted"] = time.time()
                idea["last_model"] = model_used
                idea["attempts"] = idea.get("attempts", 0) + 1
                updated = True
                break

        if updated:
            _write_atomic_json(IDEAS_LOG_PATH, current)

        # Also try QAissue.json
        current_qa = _read_json_locked(QA_ISSUE_PATH, [])
        updated_qa = False
        for idea in current_qa:
            if idea.get("title") == title:
                idea["status"] = "failed"
                idea["last_error"] = error_msg[:200]
                idea["last_attempted"] = time.time()
                idea["last_model"] = model_used
                idea["attempts"] = idea.get("attempts", 0) + 1
                updated_qa = True
                break

        if updated_qa:
            _write_atomic_json(QA_ISSUE_PATH, current_qa)

        if updated or updated_qa:
            tqdm.write(f"❌ Marked '{title}' as failed")
    except Exception as e:
        tqdm.write(f"⚠️ Could not mark '{title}' as failed: {e}")

async def mark_idea_skipped(title, reason):
    """Mark idea as skipped in both ideas_log.json and QAissue.json."""
    if not title:
        return

    try:
        # Try ideas_log.json
        current = _read_json_locked(IDEAS_LOG_PATH, [])
        updated = False
        for idea in current:
            if idea.get("title") == title:
                idea["status"] = "skipped"
                idea["skip_reason"] = reason
                idea["skipped_at"] = time.time()
                updated = True
                break

        if updated:
            _write_atomic_json(IDEAS_LOG_PATH, current)

        # Also try QAissue.json
        current_qa = _read_json_locked(QA_ISSUE_PATH, [])
        updated_qa = False
        for idea in current_qa:
            if idea.get("title") == title:
                idea["status"] = "skipped"
                idea["skip_reason"] = reason
                idea["skipped_at"] = time.time()
                updated_qa = True
                break

        if updated_qa:
            _write_atomic_json(QA_ISSUE_PATH, current_qa)

        if updated or updated_qa:
            tqdm.write(f"⏭️ Marked '{title}' as skipped: {reason}")
    except Exception as e:
        tqdm.write(f"⚠️ Could not mark '{title}' as skipped: {e}")

async def feed_retry_to_nn(title: str, language: str, error_msg: str, attempt: int):
    """Immediately feed failed retry to NN training data."""
    try:
        nn_training_path = Path(__file__).parent / "nn_training_data.jsonl"

        sample = {
            'timestamp': time.time(),
            'stage': 'failed_retry',
            'language': language,
            'title': title[:60],
            'error_type': error_msg[:100] if error_msg else 'unknown',
            'attempt': attempt,
            'success': False,
        }

        nn_training_path.parent.mkdir(exist_ok=True)
        with open(nn_training_path, 'a') as f:
            f.write(json.dumps(sample) + '\n')

    except Exception as e:
        pass  # Silent fail for NN training logging

async def poll_ideas_log_changes():
    """
    Poll ideas_log.json for new entries instead of using FSE.
    This prevents file watcher race conditions that cause deadlocks.
    """
    global IDEAS_LOG_LAST_MTIME
    poll_interval = 1.5  # Check frequently enough to cut idle latency without busy-waiting

    while True:
        try:
            await asyncio.sleep(poll_interval)
            if not IDEAS_LOG_PATH.exists():
                continue

            # Check if file was modified (new ideas appended)
            try:
                current_mtime = IDEAS_LOG_PATH.stat().st_mtime
                if current_mtime != IDEAS_LOG_LAST_MTIME:
                    # File changed, reload it
                    await process_new_ideas_from_log()
                    IDEAS_LOG_LAST_MTIME = current_mtime
            except OSError:
                # File might be locked temporarily, skip this check
                pass

        except Exception as e:
            tqdm.write(f"⚠️ Ideas log polling error: {e}")
            await asyncio.sleep(5)

async def poll_qa_issues_changes():
    """
    Poll QAissue.json for new entries instead of using FSE.
    This prevents file watcher race conditions that cause deadlocks.
    """
    global QA_ISSUE_LAST_MTIME
    poll_interval = 1.5  # Keep QA retries flowing with the same low-latency cadence as ideas

    while True:
        try:
            await asyncio.sleep(poll_interval)
            if not QA_ISSUE_PATH.exists():
                continue

            # Check if file was modified (new QA issues appended)
            try:
                current_mtime = QA_ISSUE_PATH.stat().st_mtime
                if current_mtime != QA_ISSUE_LAST_MTIME:
                    # File changed, reload it
                    await process_new_qa_issues_from_log()
                    QA_ISSUE_LAST_MTIME = current_mtime
            except OSError:
                # File might be locked temporarily, skip this check
                pass

        except Exception as e:
            tqdm.write(f"⚠️ QA issues polling error: {e}")
            await asyncio.sleep(5)

async def poll_redis_ideas():
    """
    Poll Redis queue for new ideas published by outline service.
    This is the primary integration point for Swarm-based idea generation.
    """
    if not USE_REDIS or not REDIS_CLIENT:
        return  # Disabled or connection failed, skip

    poll_interval = 1.5  # Lower queue latency while staying cheap on Redis
    queue_key = "ideas:queue"
    processed_ids = set()  # Track processed ideas to avoid duplicates

    while True:
        try:
            await asyncio.sleep(poll_interval)

            dequeued_count = 0

            # Non-blocking pop from Redis queue in small batches
            try:
                while dequeued_count < REDIS_IDEA_BATCH_SIZE:
                    # Use rpop to get one idea at a time (FIFO order)
                    idea_json = await asyncio.to_thread(REDIS_CLIENT.rpop, queue_key)

                    if not idea_json:
                        break

                    idea = json.loads(idea_json)
                    idea_id = idea.get("id", hashlib.md5(idea_json.encode()).hexdigest()[:8])

                    # Avoid processing duplicates
                    if idea_id not in processed_ids:
                        processed_ids.add(idea_id)

                        # Enqueue for processing
                        priority = 0 if idea.get("language") in ["Python", "JavaScript"] else 1
                        await JOB_QUEUE.put((priority, time.time(), idea))
                        dequeued_count += 1

                if dequeued_count:
                    tqdm.write(f"✅ Dequeued {dequeued_count} idea(s) from Redis")

            except json.JSONDecodeError as e:
                tqdm.write(f"⚠️ Invalid JSON in Redis queue: {e}")
            except Exception as e:
                tqdm.write(f"⚠️ Redis queue poll error: {e}")
                await asyncio.sleep(5)

        except Exception as e:
            tqdm.write(f"⚠️ Redis polling fatal error: {e}")
            await asyncio.sleep(5)

async def forced_periodic_reload():
    """
    Force a full reload of ideas_log.json and QAissue.json every 5 minutes.
    This catches changes that mtime-based polling misses due to filesystem timing issues.
    Prevents workers from going idle with a full backlog.
    """
    reload_interval = 5 * 60  # 5 minutes

    while True:
        try:
            await asyncio.sleep(reload_interval)

            # Forced full reload
            ideas = load_ideas_from_log()
            qa_issues = load_qa_issues_from_log()
            new_count = len(ideas) + len(qa_issues)

            if new_count > JOB_QUEUE.qsize() + SLOW_QUEUE.qsize():
                tqdm.write(f"🔄 Periodic reload: found {new_count - JOB_QUEUE.qsize() - SLOW_QUEUE.qsize()} new items, requeuing...")
                await enqueue_tasks(ideas)
                if qa_issues:
                    await enqueue_tasks(qa_issues)

        except Exception as e:
            tqdm.write(f"⚠️ Forced reload error: {e}")
            await asyncio.sleep(30)

async def detect_stuck_workers():
    """
    Monitor for workers stuck idle with full queue.
    If all workers idle for >120s and ideas_log has >50 items, force a restart.
    """
    check_interval = 30  # Check every 30s
    last_active_time = time.time()

    while True:
        try:
            await asyncio.sleep(check_interval)

            # Count active workers
            active_count = sum(1 for w in WORKER_STATUS.values() if w.get('status') == 'working')
            ideas_count = 0
            if IDEAS_LOG_PATH.exists():
                ideas_count = len(json.loads(IDEAS_LOG_PATH.read_text()))

            if active_count == 0 and ideas_count > 50:
                elapsed = time.time() - last_active_time
                if elapsed > 120:
                    tqdm.write(f"🚨 Workers stuck idle for {elapsed:.0f}s with {ideas_count} ideas in queue!")
                    tqdm.write(f"🔄 Force-reloading queue...")
                    ideas = load_ideas_from_log()
                    qa_issues = load_qa_issues_from_log()
                    await enqueue_tasks(ideas)
                    if qa_issues:
                        await enqueue_tasks(qa_issues)
                    last_active_time = time.time()
            else:
                last_active_time = time.time()

        except Exception as e:
            tqdm.write(f"⚠️ Stuck detection error: {e}")
            await asyncio.sleep(30)

async def process_new_ideas_from_log():
    """Incrementally enqueue new ideas appended to ideas_log.json."""
    global IDEAS_LOG_LAST_SIZE
    try:
        async with IDEA_LOG_LOCK:
            if not IDEAS_LOG_PATH.exists():
                return
            ideas = await asyncio.to_thread(_read_json_locked, IDEAS_LOG_PATH, [])
            if not isinstance(ideas, list):
                return
            if len(ideas) <= IDEAS_LOG_LAST_SIZE:
                return
            new_items = ideas[IDEAS_LOG_LAST_SIZE:]
            IDEAS_LOG_LAST_SIZE = len(ideas)
            tqdm.write(f"ℹ️ Detected {len(new_items)} new ideas in ideas_log.json; enqueueing...")
            for idea in sort_ideas_oldest_first(new_items):
                prio = 0 if PREFERRED_MODEL == "deepseek-r1" else 5
                await enqueue_task(idea, priority=prio)
    except Exception as e:
        tqdm.write(f"⚠️ Failed processing ideas_log.json update: {e}")

async def process_new_qa_issues_from_log():
    """Incrementally enqueue new QA issues appended to QAissue.json."""
    global QA_ISSUE_LAST_SIZE
    try:
        async with QA_ISSUE_LOCK:
            if not QA_ISSUE_PATH.exists():
                return
            issues = await asyncio.to_thread(_read_json_locked, QA_ISSUE_PATH, [])
            if not isinstance(issues, list):
                return
            if len(issues) <= QA_ISSUE_LAST_SIZE:
                return
            new_items = issues[QA_ISSUE_LAST_SIZE:]
            QA_ISSUE_LAST_SIZE = len(issues)
            tqdm.write(f"ℹ️ Detected {len(new_items)} new items in QAissue.json; enqueueing...")
            for issue in sort_ideas_oldest_first(new_items):
                prio = 0 if PREFERRED_MODEL == "deepseek-r1" else 5
                await enqueue_task(issue, priority=prio)
    except Exception as e:
        tqdm.write(f"⚠️ Failed processing QAissue.json update: {e}")

async def poll_implementations_dir():
    """
    Poll implementations directory for new JSON task files.
    Legacy support for file-based task submission (now using ideas_log.json/QAissue.json).
    """
    poll_interval = 5  # Check every 5 seconds

    while True:
        try:
            await asyncio.sleep(poll_interval)

            if not Path(IMPLEMENTATIONS_DIR).exists():
                continue

            # Check for new JSON files
            for filename in os.listdir(IMPLEMENTATIONS_DIR):
                if filename.endswith(".json"):
                    filepath = os.path.join(IMPLEMENTATIONS_DIR, filename)
                    try:
                        with open(filepath, "r") as f:
                            data = json.load(f)

                        # Handle both single task and list of tasks
                        tasks = data if isinstance(data, list) else [data]

                        for task in tasks:
                            if task.get("title"):
                                prio = 0 if PREFERRED_MODEL == "deepseek-r1" else 5
                                await enqueue_task(task, priority=prio)

                        # Remove processed file
                        try:
                            os.remove(filepath)
                            tqdm.write(f"ℹ️ Processed and removed {filename}")
                        except OSError:
                            pass
                    except Exception as e:
                        tqdm.write(f"⚠️ Error processing {filename}: {e}")

        except Exception as e:
            tqdm.write(f"⚠️ Implementations dir polling error: {e}")
            await asyncio.sleep(10)

# -------------------- Worker --------------------
async def worker(worker_id, main_pbar):
    worker_pbar = tqdm(
        total=0,
        position=worker_id + 1,
        desc=f"Worker {worker_id}",
        leave=False,
        bar_format="{desc} |{bar}| {percentage:3.0f}% [{elapsed}<{remaining}] {postfix}"
    )

    while True:
        try:
            # Check main queue first; only use slow queue if main is empty
            is_slow = False
            idea = None

            try:
                _, _, idea = JOB_QUEUE.get_nowait()
            except asyncio.QueueEmpty:
                # Main queue empty; try slow queue
                try:
                    _, _, idea = SLOW_QUEUE.get_nowait()
                    tqdm.write(f"📦 Worker {worker_id} processing from SLOW_QUEUE: {idea.get('title', 'unknown')}")
                    is_slow = True
                except asyncio.QueueEmpty:
                    # Both queues empty; wait for task
                    # Prefer main queue, but accept from slow queue if available
                    try:
                        _, _, idea = await asyncio.wait_for(JOB_QUEUE.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        try:
                            _, _, idea = await asyncio.wait_for(SLOW_QUEUE.get(), timeout=1.0)
                            tqdm.write(f"📦 Worker {worker_id} processing from SLOW_QUEUE: {idea.get('title', 'unknown')}")
                            is_slow = True
                        except asyncio.TimeoutError:
                            await asyncio.sleep(0.5)  # Idle sleep
                            continue

            # Check if too many workers are processing variations of the same base project
            base_project = idea.get('base_project_name') or idea.get('original_project')
            if base_project and base_project in ACTIVE_BASE_PROJECTS:
                concurrent_count = ACTIVE_BASE_PROJECTS[base_project]
                if concurrent_count >= MAX_CONCURRENT_SAME_PROJECT:
                    # Too many workers on this project; requeue and skip
                    tqdm.write(f"⏸️  Worker {worker_id} skipping '{idea.get('title')}' - {concurrent_count} workers already on '{base_project}'")
                    await asyncio.sleep(2)  # Brief delay before requeuing
                    await enqueue_task(idea, priority=idea.get('priority', 5))
                    try:
                        JOB_QUEUE.task_done()
                    except ValueError:
                        pass
                    try:
                        SLOW_QUEUE.task_done()
                    except ValueError:
                        pass
                    continue

            # Track this base project
            if base_project:
                ACTIVE_BASE_PROJECTS[base_project] = ACTIVE_BASE_PROJECTS.get(base_project, 0) + 1

            # Update worker status
            preferred = select_model_for_worker(worker_id)
            language = idea.get('language', 'python').lower()
            WORKER_STATUS[worker_id].update(
                {
                    "status": "working",
                    "task": idea.get('title', 'Unknown'),
                    "started_at": time.time(),
                    "preferred_model": preferred,
                    "language": language,  # Track language for timeout checking
                }
            )
            update_status_file()

            # mk14 is synchronous, so track as a single-step task (fast) or two-step (slow)
            worker_pbar.reset(total=2 if is_slow else 1)
            worker_pbar.set_postfix_str(f"{idea.get('title', 'Task')} ({idea.get('language', 'lang')})")

            try:
                # Only require a title; language defaults to Python/JS when missing.
                missing = [key for key in ("title",) if key not in idea]
                if missing:
                    tqdm.write(f"✗ Worker {worker_id} skipped task missing {missing}: {idea}")
                    worker_pbar.reset(total=0)
                    JOB_QUEUE.task_done() if hasattr(JOB_QUEUE, '_unfinished_tasks') else None
                    SLOW_QUEUE.task_done() if hasattr(SLOW_QUEUE, '_unfinished_tasks') else None
                    continue

                if is_slow:
                    await run_slow_task_twice(idea, worker_id, main_pbar, worker_pbar)
                else:
                    await run_mk14_implementation(idea, worker_id)
                    worker_pbar.update(1)
                    main_pbar.update(1)
            except Exception as e:
                tqdm.write(f"✗ Worker {worker_id} error: {e}")
            finally:
                # Release base project tracking
                base_project = idea.get('base_project_name') if idea else None
                if not base_project and idea:
                    base_project = idea.get('original_project')
                if base_project and base_project in ACTIVE_BASE_PROJECTS:
                    ACTIVE_BASE_PROJECTS[base_project] = max(0, ACTIVE_BASE_PROJECTS[base_project] - 1)
                    if ACTIVE_BASE_PROJECTS[base_project] == 0:
                        del ACTIVE_BASE_PROJECTS[base_project]

                gc.collect()        # optional but safe
                worker_pbar.set_postfix_str("Idle")
                worker_pbar.reset(total=0)
                if not is_slow:
                    WORKER_STATUS[worker_id].update(
                        {
                            "status": "idle",
                            "task": None,
                            "started_at": None,
                            "preferred_model": None,
                            "last_completed": idea.get('title', 'Unknown'),
                        }
                    )
                    update_status_file()
                # Mark task as done in both queues (safe to call even if not from that queue)
                try:
                    JOB_QUEUE.task_done()
                except ValueError:
                    pass
                try:
                    SLOW_QUEUE.task_done()
                except ValueError:
                    pass
        except asyncio.CancelledError:
            # Get the task name before resetting status
            timed_out_task = WORKER_STATUS[worker_id].get("task")

            tqdm.write(f"🔄 Worker {worker_id} cancelled due to timeout, restarting...")

            # Preserve timed-out work item so oldest jobs are retried before removal
            if timed_out_task:
                await mark_idea_failed(timed_out_task, "Worker timed out; kept in queue for retry", "timeout")
                tqdm.write(f"⏳ Kept timed-out task '{timed_out_task}' in queue for retry")

            # Reset worker status and continue loop (will restart automatically)
            WORKER_STATUS[worker_id].update({
                "status": "idle",
                "task": None,
                "started_at": None,
                "preferred_model": None,
            })
            update_status_file()
            await asyncio.sleep(1)  # Brief pause before restarting
            continue

# -------------------- RAM-aware task loader --------------------
async def enqueue_tasks(ideas):
    """
    Enqueue tasks from initial list - fast batch loading.
    RAM check removed to prevent startup bottleneck with large QAissue queues.
    """
    prio = 0 if PREFERRED_MODEL == "deepseek-r1" else 5

    # Batch enqueue without blocking - much faster for large queues
    for idea in sort_ideas_oldest_first(ideas):
        await enqueue_task(idea, priority=prio)

    if ideas:
        update_status_file()
        tqdm.write(f"✅ Enqueued {len(ideas)} tasks to worker queues")

def load_ideas_from_log():
    """Load ideas from ideas_log.json if present."""
    if not IDEAS_LOG_PATH.exists():
        return []
    try:
        ideas = _read_json_locked(IDEAS_LOG_PATH, [])
        return ideas if isinstance(ideas, list) else []
    except Exception as e:
        tqdm.write(f"⚠️ Failed to load ideas_log.json: {e}")
        return []

def load_qa_issues_from_log():
    """Load QA issues from QAissue.json if present."""
    if not QA_ISSUE_PATH.exists():
        return []
    try:
        issues = _read_json_locked(QA_ISSUE_PATH, [])
        return issues if isinstance(issues, list) else []
    except Exception as e:
        tqdm.write(f"⚠️ Failed to load QAissue.json: {e}")
        return []

# -------------------- Main Async Entry --------------------
async def run_workers():
    # Ensure input/output directories exist
    Path(IMPLEMENTATIONS_DIR).mkdir(exist_ok=True)
    Path(OUTPUT_PROJECT_DIR).mkdir(exist_ok=True)

    # Load existing JSON tasks
    ideas = []
    for filename in os.listdir(IMPLEMENTATIONS_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(IMPLEMENTATIONS_DIR, filename)
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        ideas.extend(data)
                    else:
                        ideas.append(data)
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            except Exception as e:
                tqdm.write(f"❌ Failed to load {filename}: {e}")

    # Load tasks from ideas_log.json
    ideas_from_log = load_ideas_from_log()
    if ideas_from_log:
        ideas.extend(ideas_from_log)
        tqdm.write(f"ℹ️ Loaded {len(ideas_from_log)} tasks from ideas_log.json")
    global IDEAS_LOG_LAST_SIZE, IDEAS_LOG_LAST_MTIME
    IDEAS_LOG_LAST_SIZE = len(ideas_from_log)  # Track count of processed ideas
    if IDEAS_LOG_PATH.exists():
        IDEAS_LOG_LAST_MTIME = IDEAS_LOG_PATH.stat().st_mtime  # Track mtime for polling

    # Load tasks from QAissue.json (retry_manager dedicated queue)
    qa_issues_from_log = load_qa_issues_from_log()
    if qa_issues_from_log:
        ideas.extend(qa_issues_from_log)
        tqdm.write(f"ℹ️ Loaded {len(qa_issues_from_log)} tasks from QAissue.json")
    global QA_ISSUE_LAST_SIZE, QA_ISSUE_LAST_MTIME
    QA_ISSUE_LAST_SIZE = len(qa_issues_from_log)  # Track count of processed items
    if QA_ISSUE_PATH.exists():
        QA_ISSUE_LAST_MTIME = QA_ISSUE_PATH.stat().st_mtime  # Track mtime for polling

    if not ideas:
        tqdm.write("⚠️ No tasks found initially.")

    # Main overall progress bar
    main_pbar = tqdm(
        total=len(ideas),
        position=0,
        desc="Overall Progress",
        bar_format="{desc} |{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
    )

    # Spawn workers and track them for timeout management
    global WORKER_TASKS
    workers = []
    for i in range(NUM_WORKERS):
        task = asyncio.create_task(worker(i, main_pbar))
        workers.append(task)
        WORKER_TASKS[i] = task

    # Start model health monitor
    monitor_task = asyncio.create_task(monitor_models())

    # Start worker timeout monitor
    timeout_monitor = asyncio.create_task(monitor_worker_timeouts())

    # Start periodic status updater (keeps monitor fresh)
    status_updater = asyncio.create_task(update_status_periodically())

    # Enqueue initial tasks
    await enqueue_tasks(ideas)

    # Start polling tasks instead of file watchers (prevents deadlock race conditions)
    polling_tasks = [
        asyncio.create_task(poll_implementations_dir()),
        asyncio.create_task(poll_ideas_log_changes()),
        asyncio.create_task(poll_qa_issues_changes()),
        asyncio.create_task(poll_redis_ideas()),  # Poll Redis queue for Swarm-published ideas
        asyncio.create_task(forced_periodic_reload()),  # Force reload every 5 min (catches mtime misses)
        asyncio.create_task(detect_stuck_workers()),    # Detect and recover from stuck idle state
    ]

    try:
        while True:
            await asyncio.sleep(1)
            # adjust main bar total for both queues
            main_pbar.total = main_pbar.n + JOB_QUEUE.qsize() + SLOW_QUEUE.qsize()
            main_pbar.refresh()
    except KeyboardInterrupt:
        tqdm.write("🛑 Shutting down...")
    finally:
        # Cancel all polling tasks
        for task in polling_tasks:
            task.cancel()
        # Cancel worker tasks
        for w in workers:
            w.cancel()
        # Cancel monitor tasks
        monitor_task.cancel()
        timeout_monitor.cancel()
        status_updater.cancel()
        # Wait for all to finish
        await asyncio.gather(*polling_tasks, *workers, monitor_task, timeout_monitor, status_updater, return_exceptions=True)
        main_pbar.close()

if __name__ == "__main__":
    asyncio.run(run_workers())
