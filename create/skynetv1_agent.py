from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import quote, urlparse
import json
import os
import random
import re
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from email.mime.text import MIMEText
from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory, url_for
from html import escape
from zoneinfo import ZoneInfo
import psutil
import requests
import smtplib
# --- Algorithmic Synthesis Agent Integration ---
def run_algorithmic_synthesis(problem: str, language: str = "python", goal: str = "time complexity") -> dict:
    """Use the in-process skynetv2 synthesis engine and return its result."""
    try:
        from create.skynetv2_agent import run_algorithmic_synthesis as _run_algorithmic_synthesis
    except Exception as exc:
        return {"error": f"skynetv2 synthesis unavailable: {exc}"}
    return _run_algorithmic_synthesis(problem=problem, language=language, goal=goal)

try:
    import stripe
except Exception:
    stripe = None

try:
    from pyngrok import ngrok
except Exception:
    ngrok = None

# Import delegation poller for Phase 1 & 2: Auto-run delegated chatbot jobs
try:
    from delegation_poller import start_delegation_poller, get_delegation_poller
except ImportError:
    def start_delegation_poller() -> Any:
        """Auto-generated docstring."""
        pass

    def get_delegation_poller() -> Any:
        """Auto-generated docstring."""
        return None

BASE_DIR = Path("/home/pi/Desktop/test/create")
LOG_FILE = BASE_DIR / "skynetv1_agent.log"
WEBSITE_STATE_FILE = BASE_DIR / "website_state.json"
TEMPLATE_FILE = BASE_DIR / "site_template.html"
TEMPLATE_BACKUP_FILE = BASE_DIR / "site_template.html.bak"
STATUS_TXT = BASE_DIR / "skynetv1_agent_status.txt"
TRAINING_STATUS = BASE_DIR / "training_status.json"
REGISTRY_FILE = BASE_DIR / "agent_registry.json"
REWRITE_QUEUE_FILE = BASE_DIR / "self_rewrite_backlog.json"
REWRITE_RULES_FILE = BASE_DIR / "self_rewrite_rules.json"
REWRITE_HISTORY_FILE = BASE_DIR / "self_rewrite_history.json"
GENERATED_FIXES_FILE = BASE_DIR / "generated_self_fixes.py"
FEEDBACK_ARCHIVE_FILE = BASE_DIR / "feedback_archive.json"
WEB_INTEL_FILE = BASE_DIR / "web_intelligence.json"
SITE_CONFIG_FILE = BASE_DIR / "site_config.json"

# --- Auto-detect available NFS/network mounts under /mnt/ and /mnt/1tb ---
def get_available_network_mounts():
    """
    Scan /mnt/ and /mnt/1tb for available network/NFS shares (directories).
    Returns a dict {mount_name: mount_path} for all detected shares.
    """
    roots = [Path("/mnt/"), Path("/mnt/1tb/")]
    exclude = {"proc", "sys", "dev", "tmp", "run", "cdrom", "media", "lost+found"}
    mounts = {}
    for root in roots:
        if not root.exists():
            continue
        for d in root.iterdir():
            if d.is_dir() and d.name not in exclude:
                mounts[d.name] = str(d.resolve())
    return mounts

# Example usage:
# available_mounts = get_available_network_mounts()
MARKET_DIR = BASE_DIR.parent / ".market"
MARKET_PROCESS_STATE_FILE = MARKET_DIR / "process_state.json"
MARKET_DASHBOARD_FILE = MARKET_DIR / "dashboard.md"
DASHBOARD_PUBLIC_URL_FILE = BASE_DIR.parent / "dashboard_public_url.txt"

def load_local_env_files():
    """Auto-generated docstring."""
    for env_path in [Path("/home/pi/Desktop/test/.env"), Path("/home/pi/Desktop/test/.env.local"), BASE_DIR / ".env"]:
        if not env_path.exists():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            continue

load_local_env_files()

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "andy.rbltn@gmail.com")
SUGGESTION_EMAIL = os.environ.get("SUGGESTION_EMAIL", "skynetreport1@gmail.com")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder")
ENABLE_NGROK = os.environ.get("ENABLE_NGROK", "1") != "0"
ENABLE_OLLAMA_TEMPLATE_EVOLUTION = os.environ.get("ENABLE_OLLAMA_TEMPLATE_EVOLUTION", "0") == "1"
NGROK_AUTH_TOKEN = os.environ.get("NGROK_AUTH_TOKEN")
NGROK_RESERVED_URL = os.environ.get("NGROK_RESERVED_URL", "").strip()
EMAIL_FAIL_COOLDOWN_SEC = int(os.environ.get("EMAIL_FAIL_COOLDOWN_SEC", "300"))
LOOP_INTERVAL = int(os.environ.get("SKYNET_LOOP_INTERVAL", "60"))
TRAINING_RESTART_COOLDOWN_SEC = int(os.environ.get("TRAINING_RESTART_COOLDOWN_SEC", "900"))
CHATBOT_UPFRONT_PAYMENT_RATIO = float(os.environ.get("CHATBOT_UPFRONT_PAYMENT_RATIO", "0.35"))
CHATBOT_UPFRONT_PAYMENT_MIN_USD = int(os.environ.get("CHATBOT_UPFRONT_PAYMENT_MIN_USD", "150"))
CHATBOT_FREE_PAYMENT_METHOD = os.environ.get("CHATBOT_FREE_PAYMENT_METHOD", "PLATFORM_ESCROW_MILESTONE")
CHATBOT_DEPOSIT_USD = float(os.environ.get("CHATBOT_DEPOSIT_USD", "5.0"))
CHATBOT_PAYMENT_CURRENCY = os.environ.get("CHATBOT_PAYMENT_CURRENCY", "usd").lower().strip() or "usd"
CHATBOT_PAYMENT_PROVIDER = os.environ.get("CHATBOT_PAYMENT_PROVIDER", "stripe").strip().lower() or "stripe"
CHATBOT_PROMO_PREFIX = os.environ.get("CHATBOT_PROMO_PREFIX", "FREE100").strip().upper() or "FREE100"
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
MARKET_AUTO_SUBMIT_ENABLED = os.environ.get("MARKET_AUTO_SUBMIT_ENABLED", "0") == "1"
MARKET_AUTO_SUBMIT_REQUIRE_CONFIRMATION = os.environ.get("MARKET_AUTO_SUBMIT_REQUIRE_CONFIRMATION", "0") == "1"
MARKET_AUTO_SUBMIT_ALLOWED_HOSTS = {"freelancer.com", "www.freelancer.com"}
MARKET_AUTO_SUBMIT_READY_STATUSES = {"SCORED", "SUBMITTED_PENDING_CLICK"}

if stripe is not None and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

DATASET_TARGET_GB = 150
EPOCH_TARGET = 200
LOSS_TARGET = 0.05
SITE_PORT = int(os.environ.get("SKYNET_SITE_PORT", "5050"))
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", NGROK_RESERVED_URL or f"http://127.0.0.1:{SITE_PORT}").rstrip("/")
SITE_TIMEZONE = ZoneInfo("America/New_York")
SITE_EVOLUTION_REFRESH_HOURS = max(1, int(os.environ.get("SITE_EVOLUTION_REFRESH_HOURS", "1")))
RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "1") != "0"
RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")))
RATE_LIMIT_MAX_REQUESTS = max(10, int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "120")))
ADMIN_API_KEY = os.environ.get("SKYNET_ADMIN_API_KEY", "")
_email_error_last_logged = {}
_last_training_restart_at = 0.0
_last_flask_restart_attempt = 0.0
_flask_restart_lock = threading.Lock()
_flask_restart_cooldown_sec = max(10, int(os.environ.get("FLASK_RESTART_COOLDOWN_SEC", "60")))
_rate_limit_lock = threading.Lock()
_rate_limit_buckets = defaultdict(deque)
_traffic_lock = threading.Lock()
_traffic_started_at = datetime.now(SITE_TIMEZONE).isoformat()
_traffic_totals = {
    "requests_total": 0,
    "blocked_rate_limited": 0,
}
_traffic_routes = defaultdict(int)
_traffic_status_codes = defaultdict(int)
_traffic_ips = defaultdict(int)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MODULE_BLUEPRINTS = [
    {
        "key": "llm_ai",
        "title": "LLM/AI Model Integration",
        "integrations": ["OpenAI", "local model", "Hugging Face"],
        "capabilities": ["fallback routing", "dynamic prompt routing", "model selection"],
    },
    {
        "key": "database_storage",
        "title": "Database/Storage",
        "integrations": ["SQLite", "PostgreSQL", "MongoDB", "SQLAlchemy"],
        "capabilities": ["local persistence", "schema migration", "state storage"],
    },
    {
        "key": "external_apis",
        "title": "External APIs",
        "integrations": ["weather", "news", "finance", "GitHub"],
        "capabilities": ["pluggable connectors", "endpoint retry", "self-update hooks"],
    },
    {
        "key": "task_scheduling",
        "title": "Task Scheduling/Automation",
        "integrations": ["APScheduler"],
        "capabilities": ["periodic jobs", "self-triggered jobs", "schedule tuning"],
    },
    {
        "key": "notifications",
        "title": "Notification Systems",
        "integrations": ["Twilio", "Telegram", "Discord", "Slack", "Teams"],
        "capabilities": ["channel retry", "delivery escalation", "multi-channel fallback"],
    },
    {
        "key": "replication_scaling",
        "title": "Self-Replication/Scaling",
        "integrations": ["Docker", "Kubernetes", "REST", "gRPC", "queue"],
        "capabilities": ["spawn workers", "agent messaging", "horizontal scaling hooks"],
    },
    {
        "key": "security_monitoring",
        "title": "Security/Monitoring",
        "integrations": ["Sentry", "Prometheus", "fail2ban"],
        "capabilities": ["error monitoring", "metrics", "ban-rule updates"],
    },
    {
        "key": "web_scraping",
        "title": "Web Scraping/Data Collection",
        "integrations": ["BeautifulSoup", "Scrapy"],
        "capabilities": ["data gathering", "selector adaptation", "scrape fix logging"],
    },
    {
        "key": "user_auth",
        "title": "User Authentication",
        "integrations": ["OAuth", "JWT"],
        "capabilities": ["user management", "secret rotation hooks", "provider failover"],
    },
    {
        "key": "voice_audio",
        "title": "Voice/Audio",
        "integrations": ["Whisper", "Azure Speech", "Google Speech"],
        "capabilities": ["speech-to-text", "text-to-speech", "provider selection"],
    },
    {
        "key": "agent_swarm",
        "title": "Self-Improving Agent Swarm",
        "integrations": ["worker roles", "backlog orchestration", "self-rewrite executor"],
        "capabilities": ["parallel task ownership", "rewrite proposals", "feedback-informed evolution"],
    },
]

def log_action(message):
    """Auto-generated docstring."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat()}] {message}"
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(message)

def send_email(subject, body, to_email):
    """Auto-generated docstring."""
    def log_email_error(error_message):
        """Auto-generated docstring."""
        now = time.time()
        last_logged = _email_error_last_logged.get(error_message, 0)
        if now - last_logged >= EMAIL_FAIL_COOLDOWN_SEC:
            _email_error_last_logged[error_message] = now
            log_action(f"Failed to send email to {to_email}: {error_message}")

    smtp_user = os.environ.get("GMAIL_USER") or os.environ.get("SMTP_USER")
    smtp_password = (
        os.environ.get("GMAIL_APP_PASSWORD")
        or os.environ.get("SMTP_PASSWORD")
        or os.environ.get("SMTP_PASS")
    )
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "1") != "0"
    from_addr = os.environ.get("SMTP_FROM", smtp_user or "skynetv1@localhost")

    if not smtp_user or not smtp_password:
        log_email_error(
            "SMTP credentials are not configured (set GMAIL_USER/GMAIL_APP_PASSWORD or SMTP_USER/SMTP_PASSWORD)"
        )
        return False

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_email
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if smtp_use_tls:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        log_action(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as exc:
        log_email_error(str(exc))
        return False

def send_chatbot_promo_email(entry):
    """Auto-generated docstring."""
    if not isinstance(entry, dict):
        return False

    request_id = str(entry.get("id", "")).strip()
    to_email = str(entry.get("contact", "")).strip()
    promo_code = str(((entry.get("promo") or {}).get("code") or "")).strip()
    if not request_id or not to_email or not promo_code:
        return False
    if not is_valid_contact_email(to_email):
        return False

    payment_url = f"{SITE_BASE_URL}/project-chat/payment?request_id={quote(request_id)}"
    subject = f"Your 100% Off Promo Code ({request_id})"
    body = "\n".join(
        [
            "Thanks for your project request.",
            "",
            f"Request ID: {request_id}",
            f"Promo code (100% off): {promo_code}",
            "",
            "Open your payment page and apply the promo code to waive all charges:",
            payment_url,
            "",
            "After applying the code, your request is eligible to move directly into build delegation.",
        ]
    )
    return send_email(subject, body, to_email)

class BaseModule:
    """Auto-generated docstring."""
    def __init__(self, blueprint):
        """Auto-generated docstring."""
        self.blueprint = blueprint

    def health_check(self):
        """Auto-generated docstring."""
        return True

    def self_heal(self):
        """Auto-generated docstring."""
        log_action(f"[{self.blueprint['title']}] Self-healing triggered.")

class DatabaseModule(BaseModule):
    """Auto-generated docstring."""
    pass

class LLMModule(BaseModule):
    """Auto-generated docstring."""
    pass

class ExternalAPIModule(BaseModule):
    """Auto-generated docstring."""
    pass

class SchedulerModule(BaseModule):
    """Auto-generated docstring."""
    pass

class NotificationModule(BaseModule):
    """Auto-generated docstring."""
    pass

class ReplicationModule(BaseModule):
    """Auto-generated docstring."""
    pass

class SecurityModule(BaseModule):
    """Auto-generated docstring."""
    pass

class ScraperModule(BaseModule):
    """Auto-generated docstring."""
    pass

class AuthModule(BaseModule):
    """Auto-generated docstring."""
    pass

class VoiceModule(BaseModule):
    """Auto-generated docstring."""
    pass

class GenericModule(BaseModule):
    """Auto-generated docstring."""
    pass

class SelfHealingManager:
    """Auto-generated docstring."""
    def __init__(self):
        """Auto-generated docstring."""
        self.modules = {}
        self.failure_log = []

    def register(self, name, module):
        """Auto-generated docstring."""
        self.modules[name] = module

    def monitor_and_heal(self):
        """Auto-generated docstring."""
        for name, module in self.modules.items():
            try:
                if not module.health_check():
                    self.log_failure(name, "Health check failed")
                    module.self_heal()
            except Exception as exc:
                self.log_failure(name, f"Exception: {exc}")
                try:
                    module.self_heal()
                except Exception as heal_exc:
                    self.log_failure(name, f"Self-heal failed: {heal_exc}")

    def log_failure(self, name, message):
        """Auto-generated docstring."""
        self.failure_log.append((name, message, datetime.now().isoformat()))
        log_action(f"[SelfHealingManager] {name} failure: {message}")
        queue_code_rewrite(
            reason=message,
            source=f"self_healing:{name}",
            severity="warning",
        )

    def email_report(self):
        """Auto-generated docstring."""
        if not self.failure_log:
            return
        summary = "\n".join(
            [
                f"Failures captured: {len(self.failure_log)}",
                "",
                *[f"{name}: {message} at {timestamp}" for name, message, timestamp in self.failure_log[-5:]],
            ]
        )
        send_email("skynetv1 Agent Self-Healing Report", summary, ADMIN_EMAIL)

def build_self_healing_manager():
    """Auto-generated docstring."""
    manager = SelfHealingManager()
    module_map = {
        "llm_ai": LLMModule,
        "database_storage": DatabaseModule,
        "external_apis": ExternalAPIModule,
        "task_scheduling": SchedulerModule,
        "notifications": NotificationModule,
        "replication_scaling": ReplicationModule,
        "security_monitoring": SecurityModule,
        "web_scraping": ScraperModule,
        "user_auth": AuthModule,
        "voice_audio": VoiceModule,
        "agent_swarm": GenericModule,
    }
    for blueprint in MODULE_BLUEPRINTS:
        module_cls = module_map.get(blueprint["key"], GenericModule)
        manager.register(blueprint["key"], module_cls(blueprint))
    return manager

def start_self_healing_manager(manager):
    """Auto-generated docstring."""
    def loop():
        """Auto-generated docstring."""
        while True:
            manager.monitor_and_heal()
            manager.email_report()
            time.sleep(60)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread

def read_json(path):
    """Auto-generated docstring."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        log_action(f"Failed to read {path}: {exc}")
        return None

def write_json(path, payload):
    """Auto-generated docstring."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, path)

def estimate_project_amount(project_text):
    """Auto-generated docstring."""
    message = str(project_text or "").strip()
    lowered = message.lower()
    base = 150

    keyword_weights = {
        "api": 100,
        "backend": 180,
        "frontend": 140,
        "react": 160,
        "database": 180,
        "postgres": 170,
        "auth": 140,
        "payment": 220,
        "chatbot": 240,
        "ai": 220,
        "automation": 130,
        "scraper": 120,
        "deploy": 180,
        "docker": 150,
        "admin": 140,
        "dashboard": 160,
        "mobile": 180,
    }

    score = base
    for key, weight in keyword_weights.items():
        if key in lowered:
            score += weight

    # Scale by project description length to account for scope detail.
    score += min(450, max(0, len(message) // 8))

    rounded = int(round(score / 25.0) * 25)
    low = max(100, int(round(rounded * 0.85 / 25.0) * 25))
    high = int(round(rounded * 1.2 / 25.0) * 25)
    return {
        "estimate_usd": rounded,
        "range_low_usd": low,
        "range_high_usd": high,
    }

def load_market_process_state():
    """Auto-generated docstring."""
    state = read_json(MARKET_PROCESS_STATE_FILE)
    if not isinstance(state, dict):
        state = {
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "cycle": {
                "state": "DISCOVERED",
                "sources": ["Website Chatbot Intake"],
                "discovered_count": 0,
                "approved_by_user": False,
            },
            "jobs": {},
            "ranked_queue": [],
            "chatbot_requests": [],
        }
    state.setdefault("cycle", {})
    state.setdefault("jobs", {})
    state.setdefault("ranked_queue", [])
    state.setdefault("chatbot_requests", [])
    if not isinstance(state.get("jobs"), dict):
        recovered_jobs = {}
        for job in (state.get("jobs") or []):
            if isinstance(job, dict) and job.get("id"):
                recovered_jobs[str(job.get("id"))] = job
        state["jobs"] = recovered_jobs
    if not isinstance(state.get("ranked_queue"), list):
        state["ranked_queue"] = []
    if not isinstance(state.get("chatbot_requests"), list):
        state["chatbot_requests"] = []
    payment_webhooks = state.get("payment_webhooks")
    if isinstance(payment_webhooks, list):
        state["payment_webhooks"] = {"processed_event_ids": payment_webhooks[-500:]}
    elif not isinstance(payment_webhooks, dict):
        state["payment_webhooks"] = {"processed_event_ids": []}
    else:
        state["payment_webhooks"].setdefault("processed_event_ids", [])
    auto_submit = state.setdefault("auto_submit", {})
    auto_submit.setdefault("enabled", MARKET_AUTO_SUBMIT_ENABLED)
    auto_submit.setdefault("platform_scope", ["Freelancer"])
    auto_submit.setdefault("require_final_confirmation", MARKET_AUTO_SUBMIT_REQUIRE_CONFIRMATION)
    auto_submit.setdefault("browser_tools_required", True)
    auto_submit.setdefault("last_run", "")
    auto_submit.setdefault("last_result", "not_run")

    cycle = state.setdefault("cycle", {})
    cycle.setdefault("auto_submit_enabled", bool(auto_submit.get("enabled", False)))

    for job in state.get("jobs", {}).values():
        if isinstance(job, dict):
            submit_execution = job.setdefault("submit_execution", {})
            submit_execution.setdefault("attempts", 0)
            submit_execution.setdefault("last_attempt_at", "")
            submit_execution.setdefault("last_result", "not_attempted")
            submit_execution.setdefault("page_url", "")
            submit_execution.setdefault("button_label", "")
    return state

def save_market_process_state(state):
    """Auto-generated docstring."""
    state["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    write_json(MARKET_PROCESS_STATE_FILE, state)

def _is_allowed_market_submit_host(page_url):
    """Auto-generated docstring."""
    try:
        host = (urlparse(str(page_url or "")).hostname or "").lower().strip()
        return host in MARKET_AUTO_SUBMIT_ALLOWED_HOSTS
    except Exception:
        return False

def _ranked_queue_contains_job(state, job_id):
    """Auto-generated docstring."""
    for item in state.get("ranked_queue", []):
        if isinstance(item, dict) and item.get("id") == job_id:
            return True
    return False

def can_auto_submit_market_job(state, job_id, page_url, browser_tools_ready=False, authenticated=False):
    """Auto-generated docstring."""
    job = state.get("jobs", {}).get(job_id)
    if not isinstance(job, dict):
        return False, "job_not_found"

    auto_submit = state.get("auto_submit", {}) if isinstance(state.get("auto_submit"), dict) else {}
    if not bool(auto_submit.get("enabled", False)):
        return False, "auto_submit_disabled"

    if not _ranked_queue_contains_job(state, job_id):
        return False, "rank_violation"

    if str(job.get("platform", "")).strip().lower() != "freelancer":
        return False, "page_mismatch"

    status = str(job.get("status", "")).upper().strip()
    if status not in MARKET_AUTO_SUBMIT_READY_STATUSES:
        return False, f"status_not_submit_ready:{status or 'UNKNOWN'}"

    if not _is_allowed_market_submit_host(page_url):
        return False, "page_mismatch"

    if not browser_tools_ready:
        return False, "browser_tools_unavailable"

    if not authenticated:
        return False, "not_authenticated"

    return True, "ok"

def record_market_submit_attempt(job_id, page_url, button_label, result_reason, details=None):
    """Auto-generated docstring."""
    state = load_market_process_state()
    jobs = state.setdefault("jobs", {})
    job = jobs.get(job_id)
    if not isinstance(job, dict):
        return False, "job_not_found"

    now = datetime.now(SITE_TIMEZONE)
    submit_execution = job.setdefault("submit_execution", {})
    submit_execution["attempts"] = int(submit_execution.get("attempts", 0)) + 1
    submit_execution["last_attempt_at"] = now.isoformat()
    submit_execution["last_result"] = str(result_reason or "unknown")
    submit_execution["page_url"] = str(page_url or "")
    submit_execution["button_label"] = str(button_label or "")
    if details:
        submit_execution["details"] = str(details)

    previous_status = str(job.get("status", "")).upper().strip()
    if result_reason == "clicked_confirmed":
        job["status"] = "SUBMITTED"
        job["next_action"] = "Await client reply and request funded first milestone"
    elif result_reason == "not_authenticated":
        # Recoverable: keep status at SUBMITTED_PENDING_CLICK so re-run after login works
        if previous_status != "SUBMITTED":
            pass  # Leave status unchanged
        job["next_action"] = "Log in to Freelancer then re-run auto-submit"
    elif result_reason == "browser_closed_during_login_wait":
        # Recoverable: user closed the window or display issue
        if previous_status != "SUBMITTED":
            pass  # Leave status unchanged
        job["next_action"] = "Re-run auto-submit; keep browser window open to log in"
    elif result_reason in {
        "browser_tools_unavailable",
        "page_mismatch",
        "missing_button",
        "form_mismatch",
        "rank_violation",
        "missing_bid_opener_button",
        "textarea_did_not_appear_after_click",
        "bid_opener_click_failed",
    }:
        if previous_status != "SUBMITTED":
            job["status"] = "BLOCKED_REVIEW"
        job["next_action"] = f"Resolve submit blocker: {result_reason}"

    job["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    auto_submit = state.setdefault("auto_submit", {})
    auto_submit["last_run"] = now.isoformat()
    auto_submit["last_result"] = f"{job_id}:{result_reason}"

    cycle = state.setdefault("cycle", {})
    cycle["state"] = str(job.get("status", cycle.get("state", "DISCOVERED")))
    cycle["auto_submit_last_result"] = auto_submit["last_result"]
    cycle["auto_submit_last_job_id"] = job_id

    history = state.setdefault("history", [])
    history.append(
        {
            "from": previous_status,
            "to": job.get("status"),
            "timestamp": now.isoformat(),
            "reason": f"market_auto_submit:{result_reason}",
            "job_id": job_id,
            "page_url": str(page_url or ""),
        }
    )
    state["history"] = history[-300:]

    save_market_process_state(state)
    sync_market_dashboard(state)
    return True, str(job.get("status", ""))

def render_chatbot_dashboard_block(requests):
    """Auto-generated docstring."""
    if not requests:
        return "No chatbot project requests submitted yet."
    lines = ["| Request ID | Status | Estimate (USD) | Last Update | Next Action |", "|---|---|---:|---|---|"]
    for item in requests[-10:][::-1]:
        lines.append(
            "| {id} | {status} | {estimate} ({low}-{high}) | {updated} | {next_action} |".format(
                id=item.get("id", ""),
                status=item.get("status", "DISCOVERED"),
                estimate=item.get("estimate_usd", 0),
                low=item.get("range_low_usd", 0),
                high=item.get("range_high_usd", 0),
                updated=item.get("last_update", ""),
                next_action=item.get("next_action", "Awaiting Market Agent triage"),
            )
        )
    return "\n".join(lines)

def sync_market_dashboard(state):
    """Auto-generated docstring."""
    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    existing = ""
    if MARKET_DASHBOARD_FILE.exists():
        existing = MARKET_DASHBOARD_FILE.read_text(encoding="utf-8")

    block = (
        "<!-- CHATBOT_REQUESTS_START -->\n"
        "\n"
        "## Chatbot Project Intake\n"
        "\n"
        "Requests submitted through the live site chatbot queue:\n"
        "\n"
        f"{render_chatbot_dashboard_block(state.get('chatbot_requests', []))}\n"
        "\n"
        "<!-- CHATBOT_REQUESTS_END -->"
    )

    start_marker = "<!-- CHATBOT_REQUESTS_START -->"
    end_marker = "<!-- CHATBOT_REQUESTS_END -->"
    if start_marker in existing and end_marker in existing:
        prefix = existing.split(start_marker, 1)[0].rstrip()
        suffix = existing.split(end_marker, 1)[1].lstrip()
        combined = f"{prefix}\n\n{block}\n\n{suffix}".strip() + "\n"
    elif existing.strip():
        combined = existing.rstrip() + "\n\n" + block + "\n"
    else:
        combined = "# Market Workflow Dashboard\n\n" + block + "\n"

    MARKET_DASHBOARD_FILE.write_text(combined, encoding="utf-8")

def calculate_chatbot_upfront_payment(estimate_usd):
    """Auto-generated docstring."""
    estimate_value = max(0, float(estimate_usd or 0))
    if CHATBOT_DEPOSIT_USD > 0:
        return float(round(CHATBOT_DEPOSIT_USD, 2))
    ratio_amount = float(round(estimate_value * CHATBOT_UPFRONT_PAYMENT_RATIO, 2))
    return float(max(CHATBOT_UPFRONT_PAYMENT_MIN_USD, ratio_amount))

def build_free_payment_setup_text(upfront_payment_required):
    """Auto-generated docstring."""
    return (
        f"Pay the upfront deposit (${upfront_payment_required:.2f}) to start the build. "
        "Use the payment page to complete checkout."
    )

def _money_to_cents(amount_usd):
    """Auto-generated docstring."""
    return max(50, int(round(float(amount_usd or 0) * 100)))

def _generate_default_promo_code(request_id):
    """Auto-generated docstring."""
    token = re.sub(r"[^A-Za-z0-9]", "", str(request_id or ""))[-8:]
    token = token.upper() or f"{random.randint(100000, 999999)}"
    return f"{CHATBOT_PROMO_PREFIX}-{token}"

def _apply_promo_defaults(record):
    """Auto-generated docstring."""
    promo = record.setdefault("promo", {})
    promo.setdefault("code", _generate_default_promo_code(record.get("id", "")))
    promo.setdefault("percent_off", 100)
    promo.setdefault("active", True)
    promo.setdefault("applied", False)
    promo.setdefault("applied_at", "")
    return promo

def _apply_payment_defaults(record):
    """Auto-generated docstring."""
    quote_total = float(record.get("estimate_usd", 0) or 0)
    deposit_usd = float(record.get("upfront_payment_required_usd", calculate_chatbot_upfront_payment(quote_total)) or 0)
    final_usd = max(0.0, round(quote_total - deposit_usd, 2))
    promo = _apply_promo_defaults(record)
    payment = record.setdefault("payment", {})
    payment.setdefault("provider", CHATBOT_PAYMENT_PROVIDER)
    payment.setdefault("currency", CHATBOT_PAYMENT_CURRENCY)
    payment.setdefault("total_amount_usd", round(quote_total, 2))
    payment.setdefault("deposit_amount_usd", round(deposit_usd, 2))
    payment.setdefault("final_amount_usd", final_usd)
    payment.setdefault("deposit_status", "UNPAID")
    payment.setdefault("final_status", "UNPAID" if final_usd > 0 else "NOT_REQUIRED")
    payment.setdefault("deposit_checkout_session_id", "")
    payment.setdefault("final_checkout_session_id", "")
    payment.setdefault("deposit_payment_intent_id", "")
    payment.setdefault("final_payment_intent_id", "")
    payment.setdefault("deposit_paid_at", "")
    payment.setdefault("awaiting_final_payment_at", "")
    payment.setdefault("final_paid_at", "")
    payment.setdefault("final_payment_reminder_sent_at", "")
    payment.setdefault("final_payment_reminder_count", 0)
    payment.setdefault("next_final_payment_reminder_at", "")
    payment.setdefault("promo_code", promo.get("code", ""))
    payment.setdefault("discount_percent", 0)
    payment.setdefault("discount_amount_usd", 0.0)
    payment.setdefault("discount_applied", False)
    payment.setdefault("events", [])
    record["upfront_payment_required_usd"] = payment["deposit_amount_usd"]
    return payment

def _record_payment_event(payment, event_id, event_type, stage, detail=""):
    """Auto-generated docstring."""
    events = list(payment.get("events") or [])
    events.append(
        {
            "event_id": event_id,
            "event_type": event_type,
            "stage": stage,
            "detail": detail,
            "timestamp": datetime.now(SITE_TIMEZONE).isoformat(),
        }
    )
    payment["events"] = events[-80:]

def _sync_job_payment_fields(job, request_or_payment):
    """Auto-generated docstring."""
    source = request_or_payment or {}
    payment = source.get("payment") if isinstance(source, dict) and isinstance(source.get("payment"), dict) else source
    if not isinstance(payment, dict):
        payment = {}
    job_payment = job.setdefault("payment", {})
    job_payment["provider"] = payment.get("provider", CHATBOT_PAYMENT_PROVIDER)
    job_payment["currency"] = payment.get("currency", CHATBOT_PAYMENT_CURRENCY)
    job_payment["total_amount_usd"] = payment.get("total_amount_usd", 0)
    job_payment["deposit_amount_usd"] = payment.get("deposit_amount_usd", 0)
    job_payment["deposit_status"] = payment.get("deposit_status", "UNPAID")
    job_payment["deposit_paid_at"] = payment.get("deposit_paid_at", "")
    job_payment["final_amount_usd"] = payment.get("final_amount_usd", 0)
    job_payment["final_status"] = payment.get("final_status", "UNPAID")
    job_payment["awaiting_final_payment_at"] = payment.get("awaiting_final_payment_at", "")
    job_payment["final_paid_at"] = payment.get("final_paid_at", "")
    job_payment["final_payment_reminder_sent_at"] = payment.get("final_payment_reminder_sent_at", "")
    job_payment["final_payment_reminder_count"] = payment.get("final_payment_reminder_count", 0)
    job_payment["next_final_payment_reminder_at"] = payment.get("next_final_payment_reminder_at", "")
    job_payment["promo_code"] = payment.get("promo_code", "")
    job_payment["discount_percent"] = payment.get("discount_percent", 0)
    job_payment["discount_amount_usd"] = payment.get("discount_amount_usd", 0)
    job_payment["discount_applied"] = payment.get("discount_applied", False)
    job_payment["events"] = list(payment.get("events") or [])

def apply_chatbot_promo_code(request_id, provided_code):
    """Auto-generated docstring."""
    state = load_market_process_state()
    index = _find_chatbot_request_index(state, request_id)
    if index is None:
        return False, "Request not found", ""

    entry = state["chatbot_requests"][index]
    payment = _apply_payment_defaults(entry)
    promo = _apply_promo_defaults(entry)

    expected = str(promo.get("code", "")).strip().upper()
    submitted = str(provided_code or "").strip().upper()
    if not submitted:
        return False, "Promo code is required", expected
    if submitted != expected:
        return False, "Promo code is invalid", expected
    if not bool(promo.get("active", True)):
        return False, "Promo code is not active", expected

    if bool(promo.get("applied", False)):
        return True, "Promo code already applied. Payments are waived.", expected

    now = datetime.now(SITE_TIMEZONE)
    original_total = float(payment.get("total_amount_usd", entry.get("estimate_usd", 0)) or 0)
    payment["promo_code"] = expected
    payment["discount_percent"] = 100
    payment["discount_amount_usd"] = round(original_total, 2)
    payment["discount_applied"] = True
    payment["deposit_amount_usd"] = 0.0
    payment["final_amount_usd"] = 0.0
    payment["deposit_status"] = "PAID"
    payment["final_status"] = "NOT_REQUIRED"
    payment["deposit_paid_at"] = now.isoformat()
    payment["awaiting_final_payment_at"] = ""
    payment["next_final_payment_reminder_at"] = ""

    promo["applied"] = True
    promo["applied_at"] = now.isoformat()

    entry["upfront_payment_required_usd"] = 0.0
    entry["upfront_payment_confirmed"] = True
    entry["verified_won"] = True
    entry["escrow_status"] = "DEPOSITED"
    entry["verified_at"] = entry.get("verified_at") or now.isoformat()
    entry["status"] = "VERIFIED_WON"
    entry["next_action"] = "Promo code applied (100% off). Build delegation can start immediately."
    entry["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    _record_payment_event(payment, f"promo:{expected}", "promo.applied", "deposit", "100% off")

    job = state.setdefault("jobs", {}).setdefault(request_id, {})
    job["status"] = entry["status"]
    job["escrow_status"] = entry["escrow_status"]
    job["verified_won"] = entry["verified_won"]
    job["upfront_payment_required_usd"] = 0.0
    job["upfront_payment_confirmed"] = True
    job["payment_method"] = entry.get("payment_method", "STRIPE_CHECKOUT")
    job["last_update"] = entry["last_update"]
    job["next_action"] = entry["next_action"]
    _sync_job_payment_fields(job, entry)

    cycle = state.setdefault("cycle", {})
    cycle["state"] = "VERIFIED_WON"
    cycle["last_verified_request_id"] = request_id
    cycle["last_verified_at"] = now.isoformat()

    save_market_process_state(state)
    sync_market_dashboard(state)
    return True, "Promo applied successfully. You now have 100% off.", expected

def _format_iso_timestamp(raw_value):
    """Auto-generated docstring."""
    if not raw_value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(raw_value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SITE_TIMEZONE)
        return dt.astimezone(SITE_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return str(raw_value)

def _find_payment_event_timestamp(payment, event_type, stage, detail_contains=""):
    """Auto-generated docstring."""
    for event in reversed(payment.get("events") or []):
        if str(event.get("event_type", "")) != str(event_type):
            continue
        if str(event.get("stage", "")) != str(stage):
            continue
        detail = str(event.get("detail", ""))
        if detail_contains and detail_contains not in detail:
            continue
        return event.get("timestamp")
    return ""

def render_payment_timeline(entry, payment):
    """Auto-generated docstring."""
    delivered = str(entry.get("status", "")).upper() in {"COMPLETED", "ARCHIVED"}
    milestones = [
        ("Request created", _format_iso_timestamp(entry.get("created_at")), True),
        (
            "Deposit checkout created",
            _format_iso_timestamp(_find_payment_event_timestamp(payment, "checkout.created", "deposit")),
            bool(payment.get("deposit_checkout_session_id") or _find_payment_event_timestamp(payment, "checkout.created", "deposit")),
        ),
        (
            "Deposit paid",
            _format_iso_timestamp(payment.get("deposit_paid_at") or _find_payment_event_timestamp(payment, "checkout.session.completed", "deposit", "paid")),
            str(payment.get("deposit_status", "")).upper() == "PAID",
        ),
        (
            "Awaiting final payment",
            _format_iso_timestamp(payment.get("awaiting_final_payment_at") or _find_payment_event_timestamp(payment, "job.awaiting_final_payment", "final")),
            bool(payment.get("awaiting_final_payment_at") or _find_payment_event_timestamp(payment, "job.awaiting_final_payment", "final")),
        ),
        (
            "Final checkout created",
            _format_iso_timestamp(_find_payment_event_timestamp(payment, "checkout.created", "final")),
            bool(payment.get("final_checkout_session_id") or _find_payment_event_timestamp(payment, "checkout.created", "final")),
        ),
        (
            "Final payment paid",
            _format_iso_timestamp(payment.get("final_paid_at") or _find_payment_event_timestamp(payment, "checkout.session.completed", "final", "paid")),
            str(payment.get("final_status", "")).upper() in {"PAID", "NOT_REQUIRED"},
        ),
        ("Delivery released", _format_iso_timestamp(entry.get("last_update") if delivered else ""), delivered),
    ]
    items_html = "".join(
        f"<li><strong>{escape(label)}</strong> - {escape(timestamp)}{' <span class=\'story-blurb\'>(complete)</span>' if complete else ''}</li>"
        for label, timestamp, complete in milestones
    )
    return f"<ol>{items_html}</ol>"

def render_payment_event_log(payment):
    """Auto-generated docstring."""
    events = list(reversed(payment.get("events") or []))
    if not events:
        return "<p class='story-blurb'>No payment or webhook events recorded yet.</p>"
    rows = "".join(
        "<tr>"
        f"<td>{escape(_format_iso_timestamp(event.get('timestamp')))}</td>"
        f"<td>{escape(str(event.get('stage', '')) or '-')}</td>"
        f"<td>{escape(str(event.get('event_type', '')) or '-')}</td>"
        f"<td>{escape(str(event.get('detail', '')) or '-')}</td>"
        f"<td>{escape(str(event.get('event_id', '')) or '-')}</td>"
        "</tr>"
        for event in events[:20]
    )
    return (
        "<table><thead><tr><th>Timestamp</th><th>Stage</th><th>Event</th><th>Detail</th><th>ID</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )

def _payment_state_for_request(state, request_id):
    """Auto-generated docstring."""
    index = _find_chatbot_request_index(state, request_id)
    if index is None:
        return None, None, None
    entry = state["chatbot_requests"][index]
    payment = _apply_payment_defaults(entry)
    job = state.setdefault("jobs", {}).setdefault(request_id, {})
    _sync_job_payment_fields(job, entry)
    return index, entry, payment

def create_stripe_checkout_session_for_request(request_id, stage="deposit"):
    """Auto-generated docstring."""
    if CHATBOT_PAYMENT_PROVIDER != "stripe":
        return None, "Unsupported payment provider"
    if stripe is None:
        return None, "Stripe SDK is not installed. Run: pip install stripe"
    if not STRIPE_SECRET_KEY:
        return None, "STRIPE_SECRET_KEY is not configured"

    state = load_market_process_state()
    _, entry, payment = _payment_state_for_request(state, request_id)
    if entry is None or payment is None:
        return None, "Request not found"

    stage_value = str(stage or "deposit").strip().lower()
    if stage_value not in {"deposit", "final"}:
        return None, "Invalid payment stage"

    if stage_value == "deposit":
        if payment.get("deposit_status") == "PAID":
            return None, "Deposit already paid"
        amount_usd = float(payment.get("deposit_amount_usd", 0) or 0)
    else:
        if payment.get("deposit_status") != "PAID":
            return None, "Deposit must be paid before final payment"
        if float(payment.get("final_amount_usd", 0) or 0) <= 0:
            return None, "No final payment required"
        if payment.get("final_status") == "PAID":
            return None, "Final payment already paid"
        amount_usd = float(payment.get("final_amount_usd", 0) or 0)

    if amount_usd <= 0:
        return None, f"No {stage_value} payment is required for this request"

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": CHATBOT_PAYMENT_CURRENCY,
                        "unit_amount": _money_to_cents(amount_usd),
                        "product_data": {
                            "name": f"Chatbot Build Request {stage_value.title()} Payment",
                            "description": f"Request {request_id}",
                        },
                    },
                    "quantity": 1,
                }
            ],
            success_url=(
                f"{SITE_BASE_URL}/project-chat/payment?request_id={quote(request_id)}&stage={stage_value}&status=success"
                "&session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{SITE_BASE_URL}/project-chat/payment?request_id={quote(request_id)}&stage={stage_value}&status=cancelled",
            customer_email=(entry.get("contact") or ""),
            metadata={
                "request_id": request_id,
                "payment_stage": stage_value,
                "source": "website_chatbot",
            },
        )
    except Exception as exc:
        return None, f"Stripe checkout creation failed: {exc}"

    if stage_value == "deposit":
        payment["deposit_checkout_session_id"] = session.id
    else:
        payment["final_checkout_session_id"] = session.id
    _record_payment_event(payment, f"checkout_session:{session.id}", "checkout.created", stage_value)

    now = datetime.now(SITE_TIMEZONE)
    entry["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    entry["next_action"] = f"Complete {stage_value} payment checkout"
    save_market_process_state(state)
    sync_market_dashboard(state)
    return session.url, None

def process_stripe_checkout_event(event):
    """Auto-generated docstring."""
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    obj = (event.get("data") or {}).get("object") or {}

    metadata = obj.get("metadata") or {}
    request_id = str(metadata.get("request_id") or "").strip()
    stage = str(metadata.get("payment_stage") or "").strip().lower()
    if not request_id or stage not in {"deposit", "final"}:
        return False, "missing metadata"

    state = load_market_process_state()
    webhooks = state.setdefault("payment_webhooks", {})
    processed_ids = list(webhooks.get("processed_event_ids") or [])
    if event_id and event_id in processed_ids:
        return True, "duplicate event"

    _, entry, payment = _payment_state_for_request(state, request_id)
    if entry is None or payment is None:
        return False, "request not found"

    payment_status = str(obj.get("payment_status") or "").lower()
    payment_intent = str(obj.get("payment_intent") or "")

    if event_type == "checkout.session.completed" and payment_status == "paid":
        now = datetime.now(SITE_TIMEZONE)
        if stage == "deposit":
            payment["deposit_status"] = "PAID"
            payment["deposit_payment_intent_id"] = payment_intent
            payment["deposit_paid_at"] = now.isoformat()
            entry["upfront_payment_confirmed"] = True
            entry["verified_won"] = True
            entry["escrow_status"] = "DEPOSITED"
            entry["verified_at"] = now.isoformat()
            entry["status"] = "VERIFIED_WON"
            entry["next_action"] = "Deposit paid. Triggering build delegation."
        else:
            payment["final_status"] = "PAID"
            payment["final_payment_intent_id"] = payment_intent
            payment["final_paid_at"] = now.isoformat()
            payment["next_final_payment_reminder_at"] = ""
            entry["final_payment_confirmed"] = True
            entry["final_payment_confirmed_at"] = now.isoformat()
            entry["next_action"] = "Final payment paid. Re-queueing delivery release."

        entry["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        _record_payment_event(payment, event_id or f"event:{now.timestamp()}", event_type, stage, "paid")

        if event_id:
            processed_ids.append(event_id)
            webhooks["processed_event_ids"] = processed_ids[-500:]

        save_market_process_state(state)
        sync_market_dashboard(state)

        if stage == "deposit":
            trigger_chatbot_build_now(request_id)
        else:
            trigger_chatbot_build_now(request_id)
        return True, "payment applied"

    _record_payment_event(payment, event_id or f"event:{time.time()}", event_type, stage, f"ignored:{payment_status}")
    if event_id:
        processed_ids.append(event_id)
        webhooks["processed_event_ids"] = processed_ids[-500:]
    save_market_process_state(state)
    sync_market_dashboard(state)
    return True, "event ignored"

def auto_promote_chatbot_request_for_build(request_id, proof=""):
    """Auto-generated docstring."""
    state = load_market_process_state()
    index = _find_chatbot_request_index(state, request_id)
    if index is None:
        return None, "Request not found"

    item = state["chatbot_requests"][index]
    if item.get("status") == "DISCOVERED":
        approve_chatbot_request(request_id)

    rank_chatbot_requests()

    state = load_market_process_state()
    index = _find_chatbot_request_index(state, request_id)
    if index is None:
        return None, "Request not found after ranking"

    item = state["chatbot_requests"][index]
    payment = _apply_payment_defaults(item)
    escrow_ok = str(item.get("escrow_status", "")).upper() in {"FUNDED", "DEPOSITED"}
    deposit_paid = str(payment.get("deposit_status", "UNPAID")).upper() == "PAID"
    if not (bool(item.get("verified_won")) and escrow_ok):
        if not deposit_paid:
            return None, "Blocked: deposit payment is not confirmed yet."
        verify_chatbot_request_award(
            request_id,
            proof=proof or f"Upfront payment confirmed via website intake at {datetime.now(SITE_TIMEZONE).isoformat()}",
        )

    return trigger_chatbot_build_now(request_id)
def queue_chatbot_project_request(message, contact="", upfront_payment_confirmed=False):
    """Auto-generated docstring."""
    cleaned_message = " ".join(str(message or "").split()).strip()
    if not cleaned_message:
        return None
    contact_value = str(contact or "").strip()
    if not is_valid_contact_email(contact_value):
        return None

    quote = estimate_project_amount(cleaned_message)
    upfront_payment_required = calculate_chatbot_upfront_payment(quote.get("estimate_usd", 0))
    state = load_market_process_state()
    timestamp = datetime.now(SITE_TIMEZONE)

    # Follow-up protection: keep the same request id when a client sends updates
    # for an existing chatbot job with the same contact email.
    def _active_chatbot_requests(items):
        """Auto-generated docstring."""
        active_statuses = {
            "DISCOVERED",
            "APPROVED",
            "SCORED",
            "SUBMITTED",
            "CLIENT_REPLIED",
            "AWARDED_PENDING_ESCROW",
            "VERIFIED_WON",
            "DELEGATED",
            "BUILDING",
            "TESTING",
            "BLOCKED",
            "COMPLETED",
        }
        return [
            i for i in items
            if i.get("source") == "website_chatbot"
            and str(i.get("status", "")).upper() in active_statuses
        ]

    existing = None
    requests = state.get("chatbot_requests", [])
    if contact_value:
        for item in reversed(requests):
            if item.get("source") == "website_chatbot" and str(item.get("contact", "")).strip() == contact_value:
                existing = item
                break
    if existing and existing.get("id"):
        request_id = existing["id"]
        _apply_promo_defaults(existing)
        existing["last_update"] = timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")
        existing_status = str(existing.get("status", "")).upper()
        if existing_status in {"DELEGATED", "BUILDING", "TESTING"}:
            existing["next_action"] = "Continue active build with latest client requirements"
        elif existing_status == "COMPLETED":
            existing["next_action"] = "Review follow-up request and queue revision work if needed"
        else:
            existing["status"] = "CLIENT_REPLIED"
            existing["next_action"] = "Continue build with latest client requirements and send checkpoint update"
        existing["last_client_message"] = cleaned_message
        existing["upfront_payment_required_usd"] = existing.get("upfront_payment_required_usd", upfront_payment_required)
        existing["payment_method"] = existing.get("payment_method", "STRIPE_CHECKOUT")
        existing_payment = _apply_payment_defaults(existing)
        if upfront_payment_confirmed:
            existing["upfront_payment_confirmed"] = True
            existing_payment["deposit_status"] = "PAID"
            if not existing.get("verified_won") and str(existing.get("escrow_status", "")).upper() not in {"FUNDED", "DEPOSITED"}:
                existing["verified_won"] = True
                existing["escrow_status"] = "DEPOSITED"
                existing["verified_at"] = timestamp.isoformat()
                existing["status"] = "VERIFIED_WON"
                existing["next_action"] = "Upfront payment confirmed. Auto-queueing build."
        elif str(existing.get("escrow_status", "")).upper() not in {"FUNDED", "DEPOSITED"}:
            existing["next_action"] = build_free_payment_setup_text(existing.get("upfront_payment_required_usd", upfront_payment_required))

        existing_context = list(existing.get("build_context") or [])
        existing_context.append(cleaned_message)
        existing["build_context"] = existing_context[-20:]

        jobs = state.setdefault("jobs", {})
        job = jobs.setdefault(request_id, {
            "platform": "Website Chatbot",
            "title": existing.get("title") or summarize_feedback_message(cleaned_message, limit=72),
            "url": "internal://website-chatbot-request",
            "status": existing.get("status") or "CLIENT_REPLIED",
            "escrow_status": existing.get("escrow_status", "MILESTONE_REQUIRED"),
            "verified_won": bool(existing.get("verified_won", False)),
        })
        if existing_status not in {"DELEGATED", "BUILDING", "TESTING", "COMPLETED"}:
            job["status"] = existing.get("status", "CLIENT_REPLIED")
        job["last_update"] = existing["last_update"]
        job["next_action"] = existing["next_action"]
        job["last_client_message"] = cleaned_message
        job["escrow_status"] = existing.get("escrow_status", job.get("escrow_status", "MILESTONE_REQUIRED"))
        job["verified_won"] = bool(existing.get("verified_won", job.get("verified_won", False)))
        job["upfront_payment_required_usd"] = existing.get("upfront_payment_required_usd", upfront_payment_required)
        job["upfront_payment_confirmed"] = bool(existing.get("upfront_payment_confirmed", False))
        job["payment_method"] = existing.get("payment_method", "STRIPE_CHECKOUT")
        _sync_job_payment_fields(job, existing)
        job_context = list(job.get("build_context") or [])
        job_context.append(cleaned_message)
        job["build_context"] = job_context[-20:]

        cycle = state.setdefault("cycle", {})
        cycle["state"] = "CLIENT_REPLIED"
        cycle["last_chatbot_request_at"] = timestamp.isoformat()

        save_market_process_state(state)
        sync_market_dashboard(state)
        return existing

    request_id = f"CHAT-{timestamp.strftime('%Y%m%d%H%M%S')}"

    entry = {
        "id": request_id,
        "source": "website_chatbot",
        "title": summarize_feedback_message(cleaned_message, limit=72),
        "request": cleaned_message,
        "contact": contact_value,
        "created_at": timestamp.isoformat(),
        "last_update": timestamp.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": "VERIFIED_WON" if upfront_payment_confirmed else "AWARDED_PENDING_ESCROW",
        "verified_won": bool(upfront_payment_confirmed),
        "escrow_status": "DEPOSITED" if upfront_payment_confirmed else "AWAITING_DEPOSIT",
        "upfront_payment_required_usd": upfront_payment_required,
        "upfront_payment_confirmed": bool(upfront_payment_confirmed),
        "payment_method": "STRIPE_CHECKOUT",
        "verified_at": timestamp.isoformat() if upfront_payment_confirmed else None,
        "next_action": (
            "Upfront payment confirmed. Auto-queueing build."
            if upfront_payment_confirmed
            else build_free_payment_setup_text(upfront_payment_required)
        ),
        "promo": {
            "code": _generate_default_promo_code(request_id),
            "percent_off": 100,
            "active": True,
            "applied": False,
            "applied_at": "",
        },
        **quote,
    }
    payment = _apply_payment_defaults(entry)
    if upfront_payment_confirmed:
        payment["deposit_status"] = "PAID"

    state["chatbot_requests"].append(entry)
    state["chatbot_requests"] = state["chatbot_requests"][-100:]

    state["jobs"][request_id] = {
        "platform": "Website Chatbot",
        "title": entry["title"],
        "url": "internal://website-chatbot-request",
        "status": entry["status"],
        "escrow_status": entry["escrow_status"],
        "verified_won": entry["verified_won"],
        "upfront_payment_required_usd": upfront_payment_required,
        "upfront_payment_confirmed": bool(upfront_payment_confirmed),
        "payment_method": "STRIPE_CHECKOUT",
        "last_update": entry["last_update"],
        "next_action": entry["next_action"],
        "quote": {
            "estimate_usd": entry["estimate_usd"],
            "range_low_usd": entry["range_low_usd"],
            "range_high_usd": entry["range_high_usd"],
        },
    }
    _sync_job_payment_fields(state["jobs"][request_id], entry)

    cycle = state.setdefault("cycle", {})
    cycle["state"] = entry["status"]
    cycle["sources"] = list(dict.fromkeys([*(cycle.get("sources") or []), "Website Chatbot Intake"]))
    cycle["discovered_count"] = int(cycle.get("discovered_count", 0)) + 1
    cycle["approved_by_user"] = bool(upfront_payment_confirmed)
    cycle["last_chatbot_request_at"] = timestamp.isoformat()

    save_market_process_state(state)
    sync_market_dashboard(state)
    return entry

def get_recent_chatbot_requests(limit=6):
    """Auto-generated docstring."""
    state = load_market_process_state()
    return list(reversed(state.get("chatbot_requests", [])[-limit:]))

def calculate_chatbot_win_score(entry):
    """Auto-generated docstring."""
    text = str(entry.get("request", "")).lower()
    estimate = int(entry.get("estimate_usd", 0) or 0)

    scope_clarity = min(25, 8 + min(17, len(text) // 18))
    time_to_value = 16 if any(k in text for k in ["fix", "small", "landing", "api", "automation"]) else 11
    risk_score = 14
    if any(k in text for k in ["payment", "auth", "security", "migration"]):
        risk_score -= 4
    if any(k in text for k in ["ai", "chatbot", "rag"]):
        risk_score -= 2
    risk_score = max(5, min(20, risk_score))
    friction = 13 if estimate <= 1500 else 9
    delivery_pattern_match = 15
    if any(k in text for k in ["react", "python", "scraper", "dashboard", "backend", "api"]):
        delivery_pattern_match += 4
    delivery_pattern_match = min(20, delivery_pattern_match)

    score = scope_clarity + time_to_value + risk_score + friction + delivery_pattern_match
    return {
        "score": int(max(0, min(100, score))),
        "breakdown": {
            "scope_clarity": scope_clarity,
            "time_to_value": time_to_value,
            "risk_complexity": risk_score,
            "buyer_friction": friction,
            "delivery_pattern_match": delivery_pattern_match,
        },
    }

def rank_chatbot_requests():
    """Auto-generated docstring."""
    state = load_market_process_state()
    requests = state.get("chatbot_requests", [])

    rankable_statuses = {
        "DISCOVERED",
        "APPROVED",
        "CLIENT_REPLIED",
        "AWARDED_PENDING_ESCROW",
        "VERIFIED_WON",
        "SCORED",
        "SUBMITTED_PENDING_CLICK",
    }

    scored_requests = []
    now = datetime.now(SITE_TIMEZONE)
    for item in requests:
        if not isinstance(item, dict):
            continue

        status = str(item.get("status", "")).upper().strip() or "DISCOVERED"
        if status not in rankable_statuses:
            continue

        score_info = calculate_chatbot_win_score(item)
        item["score"] = score_info["score"]
        item["score_breakdown"] = score_info["breakdown"]

        payment = _apply_payment_defaults(item)
        deposit_paid = str(payment.get("deposit_status", "UNPAID")).upper() == "PAID"

        if status in {"DISCOVERED", "APPROVED", "CLIENT_REPLIED"}:
            item["status"] = "SCORED"
            item["next_action"] = "Collect deposit payment and verify award status"
        elif status == "AWARDED_PENDING_ESCROW":
            item["status"] = "SCORED"
            item["next_action"] = "Await deposit payment confirmation"
        elif status == "VERIFIED_WON":
            item["next_action"] = (
                "Eligible for build delegation" if deposit_paid else "Await deposit payment confirmation"
            )

        item["last_ranked_at"] = now.isoformat()
        item["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        scored_requests.append(item)

    ranked = sorted(
        scored_requests,
        key=lambda req: (
            int(req.get("score", 0) or 0),
            int(req.get("estimate_usd", 0) or 0),
        ),
        reverse=True,
    )

    ranked_queue = []
    jobs = state.setdefault("jobs", {})
    for order, item in enumerate(ranked, start=1):
        request_id = item.get("id")
        if not request_id:
            continue

        queue_entry = {
            "id": request_id,
            "order": order,
            "score": int(item.get("score", 0) or 0),
            "title": item.get("title", "Chatbot Request"),
            "status": item.get("status", "SCORED"),
            "estimate_usd": int(item.get("estimate_usd", 0) or 0),
            "range_low_usd": int(item.get("range_low_usd", 0) or 0),
            "range_high_usd": int(item.get("range_high_usd", 0) or 0),
            "verified_won": bool(item.get("verified_won", False)),
            "escrow_status": item.get("escrow_status", "MILESTONE_REQUIRED"),
            "next_action": item.get("next_action", "Awaiting follow-up"),
            "ranked_at": now.isoformat(),
        }
        ranked_queue.append(queue_entry)

        job = jobs.setdefault(request_id, {})
        job.update(
            {
                "platform": "Website Chatbot",
                "title": item.get("title", "Chatbot Request"),
                "url": "internal://website-chatbot-request",
                "status": item.get("status", "SCORED"),
                "score": int(item.get("score", 0) or 0),
                "score_breakdown": dict(item.get("score_breakdown") or {}),
                "order": order,
                "escrow_status": item.get("escrow_status", "MILESTONE_REQUIRED"),
                "verified_won": bool(item.get("verified_won", False)),
                "last_update": item.get("last_update", now.strftime("%Y-%m-%d %H:%M:%S %Z")),
                "next_action": item.get("next_action", "Awaiting follow-up"),
                "quote": {
                    "estimate_usd": item.get("estimate_usd", 0),
                    "range_low_usd": item.get("range_low_usd", 0),
                    "range_high_usd": item.get("range_high_usd", 0),
                },
            }
        )
        _sync_job_payment_fields(job, item)

    state["ranked_queue"] = ranked_queue
    cycle = state.setdefault("cycle", {})
    cycle["state"] = "SCORED" if ranked_queue else cycle.get("state", "DISCOVERED")
    cycle["last_ranked_at"] = now.isoformat()
    cycle["ranked_count"] = len(ranked_queue)

    save_market_process_state(state)
    sync_market_dashboard(state)
    return ranked_queue

def verify_chatbot_request_award(request_id, proof=""):
    """Auto-generated docstring."""
    state = load_market_process_state()
    index = _find_chatbot_request_index(state, request_id)
    if index is None:
        return None

    now = datetime.now(SITE_TIMEZONE)
    item = state["chatbot_requests"][index]
    payment = _apply_payment_defaults(item)
    deposit_paid = str(payment.get("deposit_status", "UNPAID")).upper() == "PAID"

    item["verified_won"] = True
    item["verified_at"] = now.isoformat()
    item["verification_proof"] = str(proof or "verified via admin action").strip()
    item["escrow_status"] = "DEPOSITED" if deposit_paid else "FUNDED"
    item["status"] = "VERIFIED_WON"
    item["next_action"] = (
        "Eligible for build delegation" if deposit_paid else "Await deposit payment confirmation"
    )
    item["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    job = state.setdefault("jobs", {}).setdefault(request_id, {})
    job.update(
        {
            "platform": "Website Chatbot",
            "title": item.get("title", "Chatbot Request"),
            "url": "internal://website-chatbot-request",
            "status": "VERIFIED_WON",
            "verified_won": True,
            "verified_at": item["verified_at"],
            "verification_proof": item["verification_proof"],
            "escrow_status": item["escrow_status"],
            "upfront_payment_required_usd": item.get("upfront_payment_required_usd", 0),
            "upfront_payment_confirmed": bool(item.get("upfront_payment_confirmed", False)),
            "payment_method": item.get("payment_method", "STRIPE_CHECKOUT"),
            "last_update": item["last_update"],
            "next_action": item["next_action"],
            "quote": {
                "estimate_usd": item.get("estimate_usd", 0),
                "range_low_usd": item.get("range_low_usd", 0),
                "range_high_usd": item.get("range_high_usd", 0),
            },
        }
    )
    _sync_job_payment_fields(job, item)

    history = state.setdefault("history", [])
    history.append(
        {
            "from": "manual_or_pending",
            "to": "VERIFIED_WON",
            "timestamp": now.isoformat(),
            "reason": "verify_chatbot_request_award",
            "job_id": request_id,
            "proof": item["verification_proof"],
        }
    )
    state["history"] = history[-300:]

    cycle = state.setdefault("cycle", {})
    cycle["state"] = "VERIFIED_WON"
    cycle["last_verified_request_id"] = request_id
    cycle["last_verified_at"] = now.isoformat()

    save_market_process_state(state)
    sync_market_dashboard(state)
    return item

def _find_chatbot_request_index(state, request_id):
    """Auto-generated docstring."""
    requests = state.get("chatbot_requests", [])
    for index, item in enumerate(requests):
        if item.get("id") == request_id:
            return index
    return None

def approve_chatbot_request(request_id):
    """Auto-generated docstring."""
    state = load_market_process_state()
    index = _find_chatbot_request_index(state, request_id)
    if index is None:
        return None

    now = datetime.now(SITE_TIMEZONE)
    item = state["chatbot_requests"][index]
    item["status"] = "APPROVED"
    item["next_action"] = "Run automatic Phase 2.2 scoring and ranking"
    item["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    job = state.setdefault("jobs", {}).setdefault(request_id, {})
    job.update(
        {
            "platform": "Website Chatbot",
            "title": item.get("title", "Chatbot Request"),
            "url": "internal://website-chatbot-request",
            "status": "APPROVED",
            "escrow_status": item.get("escrow_status", "MILESTONE_REQUIRED"),
            "verified_won": bool(item.get("verified_won", False)),
            "last_update": item["last_update"],
            "next_action": item["next_action"],
            "quote": {
                "estimate_usd": item.get("estimate_usd", 0),
                "range_low_usd": item.get("range_low_usd", 0),
                "range_high_usd": item.get("range_high_usd", 0),
            },
        }
    )

    cycle = state.setdefault("cycle", {})
    cycle["state"] = "APPROVED"
    cycle["approved_by_user"] = True
    cycle["last_approved_request_id"] = request_id

    save_market_process_state(state)
    sync_market_dashboard(state)
    return item

def trigger_chatbot_build_now(request_id):
    """Auto-generated docstring."""
    state = load_market_process_state()
    index = _find_chatbot_request_index(state, request_id)
    if index is None:
        return None, "Request not found"

    item = state["chatbot_requests"][index]
    payment = _apply_payment_defaults(item)
    deposit_paid = str(payment.get("deposit_status", "UNPAID")).upper() == "PAID"
    verified_won = bool(item.get("verified_won"))
    escrow_ok = str(item.get("escrow_status", "")).upper() in {"FUNDED", "DEPOSITED"}
    if not deposit_paid:
        return None, "Blocked: deposit payment must be PAID via webhook before build can start."
    if not (verified_won and escrow_ok):
        return None, "Blocked: requires VERIFIED_WON status and FUNDED/DEPOSITED escrow."

    now = datetime.now(SITE_TIMEZONE)
    item["status"] = "DELEGATED"
    item["next_action"] = "Sub-agent build delegation queued"
    item["last_update"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    item["delegation"] = {
        "requested_at": now.isoformat(),
        "agent": "market",
        "description": "Build chatbot-origin project request",
        "prompt": item.get("request", ""),
        "status": "QUEUED_FOR_RUNSUBAGENT",
        "note": "RunSubagent execution is guarded and must be triggered only after verification.",
    }

    job = state.setdefault("jobs", {}).setdefault(request_id, {})
    job["status"] = "DELEGATED"
    job["last_update"] = item["last_update"]
    job["next_action"] = item["next_action"]
    job["delegation"] = item["delegation"]
    _sync_job_payment_fields(job, item)

    cycle = state.setdefault("cycle", {})
    cycle["state"] = "DELEGATED"
    cycle["last_delegated_request_id"] = request_id

    save_market_process_state(state)
    sync_market_dashboard(state)
    return item, None

def is_pid_running(pid):
    """Auto-generated docstring."""
    try:
        return bool(pid) and psutil.pid_exists(int(pid))
    except Exception:
        return False

def update_training_process_status(process_name, running, note=None):
    """Auto-generated docstring."""
    status = read_json(TRAINING_STATUS)
    if not status:
        return
    processes = status.setdefault("processes", {})
    process_entry = processes.setdefault(process_name, {})
    process_entry["running"] = bool(running)
    process_entry["last_verified_at"] = datetime.now().isoformat()
    if note:
        process_entry["note"] = note
    write_json(TRAINING_STATUS, status)

def maybe_restart_training(reason):
    """Auto-generated docstring."""
    global _last_training_restart_at
    now = time.time()
    if now - _last_training_restart_at < TRAINING_RESTART_COOLDOWN_SEC:
        log_action(f"Training restart skipped due to cooldown. Reason: {reason}")
        return False
    _last_training_restart_at = now
    log_action(f"Launching training restart in background. Reason: {reason}")
    subprocess.Popen(
        ["bash", "/home/pi/Desktop/test/restart_72hr_training.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return True

def load_registry_state():
    """Auto-generated docstring."""
    state = read_json(REGISTRY_FILE) or {}
    modules = state.get("modules", {})
    for blueprint in MODULE_BLUEPRINTS:
        modules.setdefault(
            blueprint["key"],
            {
                "title": blueprint["title"],
                "enabled": True,
                "status": "stubbed",
                "integrations": blueprint["integrations"],
                "capabilities": blueprint["capabilities"],
                "self_healing": True,
                "self_learning": True,
                "self_fixing": True,
            },
        )
    state["modules"] = modules
    state.setdefault("auto_apply_site_feedback", True)
    state.setdefault("rewrite_backlog_enabled", True)
    state.setdefault("last_updated", datetime.now().isoformat())
    return state

def save_registry_state(state):
    """Auto-generated docstring."""
    state["last_updated"] = datetime.now().isoformat()
    write_json(REGISTRY_FILE, state)

def ensure_registry_state():
    """Auto-generated docstring."""
    state = load_registry_state()
    save_registry_state(state)
    return state

def load_rewrite_backlog():
    """Auto-generated docstring."""
    backlog = read_json(REWRITE_QUEUE_FILE)
    if isinstance(backlog, list):
        return backlog
    return []

def save_rewrite_backlog(backlog):
    """Auto-generated docstring."""
    write_json(REWRITE_QUEUE_FILE, backlog[-100:])

def load_rewrite_rules():
    """Auto-generated docstring."""
    rules = read_json(REWRITE_RULES_FILE)
    if isinstance(rules, list):
        return rules
    return []

def save_rewrite_rules(rules):
    """Auto-generated docstring."""
    write_json(REWRITE_RULES_FILE, rules[-200:])
    render_generated_self_fixes(rules[-200:])

def load_rewrite_history():
    """Auto-generated docstring."""
    history = read_json(REWRITE_HISTORY_FILE)
    if isinstance(history, list):
        return history
    return []

def save_rewrite_history(history):
    """Auto-generated docstring."""
    write_json(REWRITE_HISTORY_FILE, history[-200:])

def render_generated_self_fixes(rules):
    """Auto-generated docstring."""
    lines = [
        '"""Auto-generated self-fix rules for skynetv1_agent."""',
        "",
        "REWRITE_RULES = [",
    ]
    for rule in rules[-200:]:
        lines.append(f"    {repr(rule)},")
    lines.extend(
        [
            "]",
            "",
            "def get_active_rules():",
            "    return REWRITE_RULES",
            "",
        ]
    )
    GENERATED_FIXES_FILE.write_text("\n".join(lines), encoding="utf-8")

def make_rewrite_fingerprint(reason, source):
    """Auto-generated docstring."""
    return f"{source}::{str(reason).strip().lower()}"

def load_feedback_archive():
    """Auto-generated docstring."""
    archive = read_json(FEEDBACK_ARCHIVE_FILE)
    if isinstance(archive, list):
        return archive
    return []

def save_feedback_archive(archive):
    """Auto-generated docstring."""
    write_json(FEEDBACK_ARCHIVE_FILE, archive[-365:])

def default_site_features():
    """Auto-generated docstring."""
    return {
        "background": False,
        "tabs": False,
        "signup": False,
        "saved_items": False,
        "recommendations": False,
        "doc2mp3": False,
        "custom_title": "Welcome to the skynetv1 Evolving Website",
        "custom_sections": [],
        "bg_color": "#e0eafc",
        "footer": "This site evolves based on feedback and error reports from visitors.",
        "form_label": "Share feedback or request a feature:",
        "custom_text": [],
    }

def default_site_config():
    """Auto-generated docstring."""
    return {
        "features": default_site_features(),
        "implemented_feedback": [],
        "adaptive_pages": [],
        "pending_downtime_requests": [],
        "last_implementation_at": "",
        "last_implementation_reason": "",
    }

def merge_site_features(base_features, updates):
    """Auto-generated docstring."""
    merged = default_site_features()
    if isinstance(base_features, dict):
        merged.update(base_features)

    for key in ["background", "tabs", "signup", "saved_items", "recommendations", "doc2mp3"]:
        merged[key] = bool(merged.get(key, False) or updates.get(key, False))

    for key in ["custom_title", "bg_color", "footer", "form_label"]:
        if updates.get(key):
            merged[key] = updates[key]

    for key in ["custom_sections", "custom_text"]:
        items = list(merged.get(key, []))
        for item in updates.get(key, []):
            if item and item not in items:
                items.append(item)
        merged[key] = items

    return merged

def load_site_config():
    """Auto-generated docstring."""
    config = default_site_config()
    loaded = read_json(SITE_CONFIG_FILE)
    if isinstance(loaded, dict):
        config.update({k: v for k, v in loaded.items() if k != "features"})
        config["features"] = merge_site_features(loaded.get("features", {}), {})
    return config

def save_site_config(config):
    """Auto-generated docstring."""
    write_json(SITE_CONFIG_FILE, config)

def slugify_text(value, fallback="request"):
    """Auto-generated docstring."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return cleaned or fallback

def dedupe_page_slug(slug, existing_pages):
    """Auto-generated docstring."""
    existing_slugs = {page.get("slug") for page in existing_pages if isinstance(page, dict)}
    if slug not in existing_slugs:
        return slug
    suffix = 2
    while f"{slug}-{suffix}" in existing_slugs:
        suffix += 1
    return f"{slug}-{suffix}"

def summarize_feedback_message(message, limit=180):
    """Auto-generated docstring."""
    cleaned = " ".join(str(message).split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rsplit(" ", 1)[0].strip()
    return (clipped or cleaned[:limit]).rstrip(".,;:") + "..."

def infer_page_title_from_message(message):
    """Auto-generated docstring."""
    lowered = message.lower()
    if "message" in lowered and "member" in lowered:
        return "Member Messaging"
    if "stock market" in lowered:
        return "Stock Market Deep Dive"
    if "canada" in lowered and "video" in lowered:
        return "Canada Video Briefing"
    if "sign" in lowered or "signup" in lowered or "sign up" in lowered or "account" in lowered:
        return "Account Access Guide"
    if "button" in lowered or "menu" in lowered or "page" in lowered:
        return "Navigation Upgrade"
    if "store" in lowered and "card" in lowered:
        return "Store Card Directory"
    words = [word for word in re.split(r"[^A-Za-z0-9]+", message) if word]
    if not words:
        return "Adaptive Request"
    return " ".join(words[:6]).title()

def infer_feedback_tags(message):
    """Auto-generated docstring."""
    lowered = message.lower()
    tags = []
    keyword_groups = [
        ("messaging", ["message", "chat", "member"]),
        ("account", ["account", "signup", "sign up", "sign", "login", "register"]),
        ("video", ["video", "youtube"]),
        ("audio", ["mp3", "audio", "download"]),
        ("news", ["story", "stock market", "news"]),
        ("navigation", ["button", "menu", "page", "redirect", "tab"]),
        ("directory", ["store", "list", "card"]),
        ("canada", ["canada"]),
    ]
    for tag, keywords in keyword_groups:
        if any(keyword in lowered for keyword in keywords):
            tags.append(tag)
    return tags or ["general"]

def build_adaptive_sections(message, title):
    """Auto-generated docstring."""
    lowered = message.lower()
    sections = []
    sections.append(
        {
            "heading": "Request Summary",
            "items": [
                summarize_feedback_message(message),
                "This page was generated automatically from visitor feedback and is now part of the live site.",
            ],
        }
    )

    if "message" in lowered and "member" in lowered:
        sections.append(
            {
                "heading": "Messaging Flow",
                "items": [
                    "A dedicated member-to-member messaging area should stay inside the site instead of sending people elsewhere.",
                    "The site should clearly show inbox, conversation list, and reply actions in one place.",
                    "Future enhancements can attach identity, notifications, and message history to saved profiles.",
                ],
            }
        )
    if "stock market" in lowered:
        sections.append(
            {
                "heading": "Coverage Direction",
                "items": [
                    "The site should expand stock-market stories with more context instead of only short blurbs.",
                    "Related market stories should be grouped together so visitors can keep reading from one place.",
                    "This request now has its own page so the topic stays visible between refresh cycles.",
                ],
            }
        )
    if "canada" in lowered and "video" in lowered:
        sections.append(
            {
                "heading": "Video Focus",
                "items": [
                    "A dedicated card should highlight videos specifically about what is happening in Canada.",
                    "The site can use the existing video feed plus this request page as a focused destination.",
                    "This request is now represented as a reusable content area instead of a one-off note.",
                ],
            }
        )
    if "sign" in lowered or "signup" in lowered or "sign up" in lowered or "account" in lowered:
        sections.append(
            {
                "heading": "Account Clarification",
                "items": [
                    "Visitors should be able to see where sign-up lives and what happens after an account is created.",
                    "This request becomes a visible guide page so account confusion stays addressed on the site.",
                    "The homepage personalization area can link people here when they ask about accounts.",
                ],
            }
        )
    if "button" in lowered or "menu" in lowered or "redirect" in lowered or "page" in lowered:
        sections.append(
            {
                "heading": "Navigation Behavior",
                "items": [
                    "Navigation should lead to dedicated pages with fuller details, not just jump to a card lower on the page.",
                    "This adaptive page is one of those dedicated destinations generated directly from feedback.",
                    "Future requests can produce additional detail pages with their own route and content blocks.",
                ],
            }
        )
    if "store" in lowered and "card" in lowered:
        sections.append(
            {
                "heading": "Directory Layout",
                "items": [
                    "Store-related cards should be grouped into a list or directory page instead of a single jump target.",
                    "This page keeps that request visible and ready for richer directory content later.",
                ],
            }
        )

    sections.append(
        {
            "heading": "Auto-Implemented Actions",
            "items": [
                f"Created a dedicated page for '{title}'.",
                "Added a persistent navigation destination for this request.",
                "Included the request in the adaptive content library so future refreshes keep it visible.",
            ],
        }
    )
    return sections

def build_adaptive_page_entry(message, existing_pages):
    """Auto-generated docstring."""
    title = infer_page_title_from_message(message)
    slug = dedupe_page_slug(slugify_text(title), existing_pages)
    sections = build_adaptive_sections(message, title)
    summary = summarize_feedback_message(message, limit=120)
    return {
        "slug": slug,
        "title": title,
        "summary": summary,
        "source_message": message,
        "intro": f"This page was generated from visitor feedback asking for: {summary}",
        "section": title,
        "tags": infer_feedback_tags(message),
        "sections": sections,
        "created_at": datetime.now(SITE_TIMEZONE).isoformat(),
    }

def merge_adaptive_pages(existing_pages, new_pages):
    """Auto-generated docstring."""
    merged = [page for page in existing_pages if isinstance(page, dict)]
    for new_page in new_pages:
        if not isinstance(new_page, dict):
            continue
        existing_index = next(
            (index for index, item in enumerate(merged) if item.get("source_message") == new_page.get("source_message")),
            None,
        )
        if existing_index is None:
            merged.append(new_page)
        else:
            new_page["slug"] = merged[existing_index].get("slug", new_page.get("slug"))
            merged[existing_index] = new_page
    return merged[-40:]

def merge_pending_downtime_requests(existing_requests, new_requests):
    """Auto-generated docstring."""
    merged = [item for item in existing_requests if isinstance(item, dict)]
    for new_item in new_requests:
        if not isinstance(new_item, dict):
            continue
        existing_index = next(
            (index for index, item in enumerate(merged) if item.get("source_message") == new_item.get("source_message")),
            None,
        )
        if existing_index is None:
            merged.append(new_item)
        else:
            merged[existing_index] = {**merged[existing_index], **new_item}
    return merged[-80:]

def get_adaptive_pages():
    """Auto-generated docstring."""
    config = load_site_config()
    return [page for page in config.get("adaptive_pages", []) if isinstance(page, dict)]

def get_pending_downtime_requests():
    """Auto-generated docstring."""
    config = load_site_config()
    return [item for item in config.get("pending_downtime_requests", []) if isinstance(item, dict)]

def render_adaptive_request_links(limit=8):
    """Auto-generated docstring."""
    pages = get_adaptive_pages()
    if not pages:
        return "<li>No adaptive request pages have been generated yet.</li>"
    return "".join(
        f"<li><a href=\"/requests/{page['slug']}\">{page['title']}</a><div class='story-blurb'>{page['summary']}</div></li>"
        for page in pages[-limit:]
    )

def build_pending_downtime_request(message, page_entry):
    """Auto-generated docstring."""
    return {
        "source_message": message,
        "page_slug": page_entry["slug"],
        "page_title": page_entry["title"],
        "summary": page_entry["summary"],
        "section": page_entry["section"],
        "queued_at": datetime.now(SITE_TIMEZONE).isoformat(),
        "status": "queued",
    }

def render_pending_downtime_links(limit=8):
    """Auto-generated docstring."""
    items = get_pending_downtime_requests()
    if not items:
        return "<li>No downtime-only requests are currently queued.</li>"
    return "".join(
        f"<li><strong>{item['page_title']}</strong><div class='story-blurb'>{item['summary']}</div></li>"
        for item in items[-limit:]
    )

def backfill_adaptive_pages_from_history():
    """Auto-generated docstring."""
    config = load_site_config()
    adaptive_pages = list(config.get("adaptive_pages", []))
    implemented_feedback = list(config.get("implemented_feedback", []))
    candidate_messages = []

    archive = load_feedback_archive()
    for archive_entry in archive:
        for submission in archive_entry.get("submissions", []):
            if submission.get("type") == "feedback" and submission.get("message", "").strip():
                candidate_messages.append(submission["message"].strip())

    current_state = load_website_state()
    for submission in current_state.get("submissions", []):
        if submission.get("type") == "feedback" and submission.get("message", "").strip():
            candidate_messages.append(submission["message"].strip())

    _, _, unmatched_messages = extract_feature_updates_from_messages(candidate_messages)
    new_pages = []
    changed = False

    for message in unmatched_messages:
        if any(page.get("source_message") == message for page in adaptive_pages + new_pages):
            continue
        page_entry = build_adaptive_page_entry(message, adaptive_pages + new_pages)
        new_pages.append(page_entry)
        implemented_feedback.append(
            {
                "implemented_at": datetime.now(SITE_TIMEZONE).isoformat(),
                "reason": "adaptive_history_backfill",
                "message": message,
                "applied": [
                    f"Created adaptive request page '{page_entry['title']}'",
                    "Recovered a previously unmatched feedback request from site history",
                ],
            }
        )
        config["features"] = merge_site_features(
            config.get("features", {}),
            {"custom_sections": [page_entry["section"]], "custom_text": [page_entry["summary"]]},
        )
        changed = True

    if changed:
        config["adaptive_pages"] = merge_adaptive_pages(adaptive_pages, new_pages)
        config["implemented_feedback"] = implemented_feedback[-50:]
        save_site_config(config)
        log_action(f"Adaptive request backfill created {len(new_pages)} page(s) from feedback history.")
    return len(new_pages)

def extract_feature_updates_from_messages(messages):
    """Auto-generated docstring."""
    updates = {
        "background": False,
        "tabs": False,
        "signup": False,
        "saved_items": False,
        "recommendations": False,
        "doc2mp3": False,
        "custom_title": "",
        "custom_sections": [],
        "bg_color": "",
        "footer": "",
        "form_label": "",
        "custom_text": [],
    }
    implementation_notes = []
    unmatched_messages = []

    for message in messages:
        lowered = message.lower().strip()
        applied = []

        if "background" in lowered or "theme" in lowered or "bg color" in lowered:
            updates["background"] = True
            applied.append("Enabled a custom background/theme track")
        if "tab" in lowered:
            updates["tabs"] = True
            applied.append("Enabled tabbed navigation")
        if "signup" in lowered or "sign up" in lowered or "sign-up" in lowered or "register" in lowered:
            updates["signup"] = True
            updates["saved_items"] = True
            updates["recommendations"] = True
            applied.append("Enabled a free sign-up experience")
            applied.append("Enabled saved items")
            applied.append("Enabled recommendations based on saved items")
        if "save things" in lowered or "save what they like" in lowered or "favorite" in lowered or "bookmark" in lowered:
            updates["saved_items"] = True
            applied.append("Enabled saved items")
        if "recommend" in lowered:
            updates["recommendations"] = True
            applied.append("Enabled recommendations based on saved items")
        if "mp3" in lowered and ("pdf" in lowered or "word" in lowered or "video" in lowered):
            updates["doc2mp3"] = True
            applied.append("Enabled media-to-MP3 workflow messaging")
        if lowered.startswith("title:"):
            updates["custom_title"] = message.split(":", 1)[1].strip()
            applied.append("Updated the site title")
        if lowered.startswith("add section:"):
            updates["custom_sections"].append(message.split(":", 1)[1].strip())
            applied.append("Added a custom section")
        if "color:" in lowered:
            updates["bg_color"] = message.split("color:", 1)[1].strip().split()[0]
            updates["background"] = True
            applied.append("Updated the site accent color")
        if lowered.startswith("footer:"):
            updates["footer"] = message.split(":", 1)[1].strip()
            applied.append("Updated the site footer message")
        if lowered.startswith("form label:"):
            updates["form_label"] = message.split(":", 1)[1].strip()
            applied.append("Updated the feedback form label")
        if lowered.startswith("add text:"):
            updates["custom_text"].append(message.split(":", 1)[1].strip())
            applied.append("Added custom text to the site")

        if applied:
            unique_applied = list(dict.fromkeys(applied))
            implementation_notes.append({"message": message, "applied": unique_applied})
        else:
            unmatched_messages.append(message)

    return updates, implementation_notes, unmatched_messages

def apply_feedback_to_site_config(submissions, reason):
    """Auto-generated docstring."""
    feedback_messages = [
        entry.get("message", "").strip()
        for entry in submissions
        if entry.get("type") == "feedback" and entry.get("message", "").strip()
    ]
    if not feedback_messages:
        return []

    updates, implementation_notes, unmatched_messages = extract_feature_updates_from_messages(feedback_messages)
    config = load_site_config()
    config["features"] = merge_site_features(config.get("features", {}), updates)
    adaptive_pages = list(config.get("adaptive_pages", []))
    pending_downtime_requests = list(config.get("pending_downtime_requests", []))
    implemented_feedback = list(config.get("implemented_feedback", []))
    implemented_at = datetime.now(SITE_TIMEZONE).isoformat()

    for note in implementation_notes:
        record = {
            "implemented_at": implemented_at,
            "reason": reason,
            "message": note["message"],
            "applied": note["applied"],
        }
        existing_index = next(
            (index for index, item in enumerate(implemented_feedback) if item.get("message") == note["message"]),
            None,
        )
        if existing_index is None:
            implemented_feedback.append(record)
        else:
            implemented_feedback[existing_index] = record

    adaptive_entries = []
    config["implemented_feedback"] = implemented_feedback[-50:]
    for message in unmatched_messages:
        page_entry = build_adaptive_page_entry(message, adaptive_pages + adaptive_entries)
        adaptive_entries.append(page_entry)
        pending_downtime_requests = merge_pending_downtime_requests(
            pending_downtime_requests,
            [build_pending_downtime_request(message, page_entry)],
        )
        config["implemented_feedback"].append(
            {
                "implemented_at": implemented_at,
                "reason": reason,
                "message": message,
                "applied": [
                    f"Created adaptive request page '{page_entry['title']}'",
                    "Queued the request for downtime site integration",
                ],
            }
        )

    config["implemented_feedback"] = config["implemented_feedback"][-50:]
    config["adaptive_pages"] = merge_adaptive_pages(adaptive_pages, adaptive_entries)
    config["pending_downtime_requests"] = pending_downtime_requests
    config["last_implementation_at"] = implemented_at
    config["last_implementation_reason"] = reason
    save_site_config(config)

    for message in unmatched_messages:
        queue_code_rewrite(
            reason=f"Unmapped site feedback requires a custom implementation: {message}",
            source="website:feedback_request",
            severity="medium",
        )

    return implementation_notes

def apply_pending_downtime_requests(reason):
    """Auto-generated docstring."""
    config = load_site_config()
    pending_requests = list(config.get("pending_downtime_requests", []))
    if not pending_requests:
        return []

    implemented_feedback = list(config.get("implemented_feedback", []))
    implemented_at = datetime.now(SITE_TIMEZONE).isoformat()
    promoted = []
    remaining = []

    for item in pending_requests:
        if item.get("status") not in {"queued", "pending"}:
            remaining.append(item)
            continue

        config["features"] = merge_site_features(
            config.get("features", {}),
            {
                "custom_sections": [item.get("section", item.get("page_title", "Adaptive Request"))],
                "custom_text": [item.get("summary", "")],
            },
        )
        implemented_feedback.append(
            {
                "implemented_at": implemented_at,
                "reason": reason,
                "message": item.get("source_message", ""),
                "applied": [
                    f"Promoted queued request '{item.get('page_title', 'Adaptive Request')}' into site content",
                    "Added the request summary during downtime refresh",
                ],
            }
        )
        promoted.append({**item, "status": "implemented", "implemented_at": implemented_at})

    config["implemented_feedback"] = implemented_feedback[-50:]
    config["pending_downtime_requests"] = remaining
    config["last_implementation_at"] = implemented_at
    config["last_implementation_reason"] = reason
    save_site_config(config)
    return promoted

def load_web_intelligence():
    """Auto-generated docstring."""
    intelligence = read_json(WEB_INTEL_FILE)
    if isinstance(intelligence, dict):
        return intelligence
    return {"ideas": [], "tech_stories": [], "video_inspiration": {}, "youtube_videos": []}

def save_web_intelligence(intelligence):
    """Auto-generated docstring."""
    write_json(WEB_INTEL_FILE, intelligence)

def fetch_feed_entries(feed_url, limit=5):
    """Auto-generated docstring."""
    response = requests.get(feed_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    root = ET.fromstring(response.text)
    entries = []

    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or item.findtext("published") or "").strip()
        description = (item.findtext("description") or "").strip()
        if not description:
            content_node = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
            description = (content_node.text or "").strip() if content_node is not None and content_node.text else ""
        if title and link:
            entries.append({"title": title, "url": link, "published": pub_date, "description": description})

    if not entries:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns)[:limit]:
            title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
            link_node = entry.find("atom:link", ns)
            link = link_node.attrib.get("href", "").strip() if link_node is not None else ""
            pub_date = (
                entry.findtext("atom:published", default="", namespaces=ns)
                or entry.findtext("atom:updated", default="", namespaces=ns)
            ).strip()
            description = (
                entry.findtext("atom:summary", default="", namespaces=ns)
                or entry.findtext("atom:content", default="", namespaces=ns)
            ).strip()
            if title and link:
                entries.append({"title": title, "url": link, "published": pub_date, "description": description})
    return entries

def fetch_hacker_news_stories(limit=5):
    """Auto-generated docstring."""
    ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=8).json()[:limit]
    stories = []
    for item_id in ids:
        item = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", timeout=8).json()
        if item and item.get("title") and item.get("url"):
            stories.append(
                {
                    "title": item["title"],
                    "url": item["url"],
                    "published": str(item.get("time", "")),
                    "description": item.get("text", ""),
                }
            )
    return stories

def strip_html_tags(text):
    """Auto-generated docstring."""
    cleaned = []
    inside = False
    for char in text:
        if char == "<":
            inside = True
            continue
        if char == ">":
            inside = False
            continue
        if not inside:
            cleaned.append(char)
    return " ".join("".join(cleaned).split())

def make_story_blurb(title, description, source):
    """Auto-generated docstring."""
    base = strip_html_tags(description or "")
    if base:
        clipped = base[:220].rsplit(" ", 1)[0]
        if len(base) > len(clipped):
            clipped += "..."
        return clipped
    return f"{source} is highlighting {title.lower()} as one of the notable tech stories in the current cycle."

def fetch_youtube_video_inspiration():
    """Auto-generated docstring."""
    video_url = "https://www.youtube.com/watch?v=97irLVqYJCI"
    meta = requests.get(
        f"https://www.youtube.com/oembed?url={video_url}&format=json",
        timeout=8,
        headers={"User-Agent": "Mozilla/5.0"},
    ).json()
    return {
        "source_url": video_url,
        "title": meta.get("title", ""),
        "author": meta.get("author_name", ""),
        "concepts": [
            "self-improving agent swarm",
            "parallel ownership of work",
            "automatic code rewrite backlog",
            "continuous system evolution",
        ],
        "implemented_adaptations": [
            "staged self-rewrite executor",
            "daily autonomous site evolution",
            "persistent module registry",
            "feedback and error intake with learned rules",
        ],
    }

def fetch_tech_youtube_videos():
    """Auto-generated docstring."""
    fallback_videos = [
        {
            "title": "I Built a Self-Improving Agent Swarm. It Rewrote Its Own Code.",
            "author": "Jaymin West",
            "url": "https://www.youtube.com/watch?v=97irLVqYJCI",
            "reason": "Agent architecture and self-improving systems inspiration.",
        },
        {
            "title": "Two Minute Papers",
            "author": "Two Minute Papers",
            "url": "https://www.youtube.com/@TwoMinutePapers",
            "reason": "Readable AI and graphics research coverage for tech-minded visitors.",
        },
        {
            "title": "Fireship",
            "author": "Fireship",
            "url": "https://www.youtube.com/@Fireship",
            "reason": "Fast software engineering, tooling, and tech-news explainers.",
        },
        {
            "title": "Theo - t3.gg",
            "author": "Theo - t3.gg",
            "url": "https://www.youtube.com/@t3dotgg",
            "reason": "Modern web engineering and product-building commentary.",
        },
    ]
    queries = [
        ("technology news", "Current tech-news coverage and commentary."),
        ("artificial intelligence", "Current AI videos and model updates."),
        ("web development", "Modern frontend and web engineering topics."),
    ]

    videos = []
    seen_urls = set()
    for query, reason in queries:
        try:
            search_url = "https://www.youtube.com/results?search_query=" + quote(query)
            text = requests.get(search_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"}).text
            match = re.search(r"var ytInitialData = (\{.*?\});", text)
            if not match:
                continue
            data = json.loads(match.group(1))
            for renderer in iter_video_renderers(data):
                video_id = renderer.get("videoId")
                title_runs = renderer.get("title", {}).get("runs", [])
                owner_runs = renderer.get("ownerText", {}).get("runs", [])
                title = "".join(run.get("text", "") for run in title_runs).strip()
                author = "".join(run.get("text", "") for run in owner_runs).strip() or "YouTube"
                url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
                if not title or not url:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                videos.append(
                    {
                        "title": title,
                        "author": author,
                        "url": url,
                        "reason": reason,
                    }
                )
                if len(videos) >= 8:
                    return videos
        except Exception as exc:
            log_action(f"YouTube search fetch failed for query '{query}': {exc}")

    return videos or fallback_videos

def iter_video_renderers(node):
    """Auto-generated docstring."""
    if isinstance(node, dict):
        if "videoRenderer" in node and isinstance(node["videoRenderer"], dict):
            yield node["videoRenderer"]
        for value in node.values():
            yield from iter_video_renderers(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_video_renderers(item)

def refresh_web_intelligence():
    """Auto-generated docstring."""
    intelligence = {
        "refreshed_at": datetime.now(SITE_TIMEZONE).isoformat(),
        "ideas": [],
        "tech_stories": [],
        "video_inspiration": {},
        "youtube_videos": [],
    }

    design_feeds = [
        ("Smashing Magazine", "https://www.smashingmagazine.com/feed/"),
    ]
    tech_feeds = [
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ]

    for source, url in design_feeds:
        try:
            for entry in fetch_feed_entries(url, limit=3):
                intelligence["ideas"].append(
                    {
                        "source": source,
                        "title": entry["title"],
                        "url": entry["url"],
                        "published": entry["published"],
                    }
                )
        except Exception as exc:
            log_action(f"Design idea fetch failed for {source}: {exc}")

    for source, url in tech_feeds:
        try:
            for entry in fetch_feed_entries(url, limit=4):
                intelligence["tech_stories"].append(
                    {
                        "source": source,
                        "title": entry["title"],
                        "url": entry["url"],
                        "published": entry["published"],
                        "blurb": make_story_blurb(entry["title"], entry.get("description", ""), source),
                    }
                )
        except Exception as exc:
            log_action(f"Tech story fetch failed for {source}: {exc}")

    try:
        for entry in fetch_hacker_news_stories(limit=4):
            intelligence["tech_stories"].append(
                {
                    "source": "Hacker News",
                    "title": entry["title"],
                    "url": entry["url"],
                    "published": entry["published"],
                    "blurb": make_story_blurb(entry["title"], entry.get("description", ""), "Hacker News"),
                }
            )
    except Exception as exc:
        log_action(f"Hacker News fetch failed: {exc}")

    try:
        intelligence["video_inspiration"] = fetch_youtube_video_inspiration()
    except Exception as exc:
        log_action(f"Video inspiration fetch failed: {exc}")

    intelligence["youtube_videos"] = fetch_tech_youtube_videos()

    intelligence["ideas"] = intelligence["ideas"][:8]
    intelligence["tech_stories"] = intelligence["tech_stories"][:10]
    save_web_intelligence(intelligence)
    return intelligence

def queue_code_rewrite(reason, source, severity="info"):
    """Auto-generated docstring."""
    backlog = load_rewrite_backlog()
    fingerprint = make_rewrite_fingerprint(reason, source)
    for item in backlog:
        if item.get("fingerprint") == fingerprint and item.get("status") in {"queued", "analyzing", "applied"}:
            return item
    entry = {
        "created_at": datetime.now().isoformat(),
        "reason": str(reason).strip(),
        "source": source,
        "severity": severity,
        "status": "queued",
        "fingerprint": fingerprint,
    }
    backlog.append(entry)
    save_rewrite_backlog(backlog)
    return entry

def slugify(text):
    """Auto-generated docstring."""
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "auto-fix"

def build_rewrite_candidate(entry):
    """Auto-generated docstring."""
    reason = entry.get("reason", "")
    source = entry.get("source", "unknown")
    lowered = reason.lower()
    action = "learn_error_signature"
    site_response = "A learned remediation rule has been added for this issue."
    remediation_steps = ["log", "monitor", "surface_to_site"]

    if "trainer" in lowered and "not running" in lowered:
        action = "restart_training_guard"
        site_response = "Training monitor now flags missing trainer PIDs for follow-up."
        remediation_steps = ["verify_pid", "queue_restart", "record_history"]
    elif "download rate" in lowered:
        action = "dataset_rate_guard"
        site_response = "Dataset pull slowdowns are now tracked as self-fix items."
        remediation_steps = ["monitor_rate", "queue_restart", "record_history"]
    elif "module" in lowered or "import" in lowered:
        action = "dependency_guard"
        site_response = "Dependency-related failures are now classified for remediation."
        remediation_steps = ["classify_dependency_issue", "record_history", "surface_to_site"]
    elif source == "website:error_report":
        action = "site_error_rule"
        site_response = "Website error reports now generate learned remediation rules automatically."
        remediation_steps = ["capture_error", "learn_rule", "record_history"]

    rule_id = slugify(f"{source}-{reason}")[:80]
    return {
        "rule_id": rule_id,
        "title": f"Auto fix for {source}",
        "source": source,
        "match_terms": sorted({token for token in lowered.replace(":", " ").split() if len(token) > 3})[:8],
        "action": action,
        "site_response": site_response,
        "remediation_steps": remediation_steps,
        "created_from": entry.get("created_at"),
        "fingerprint": entry.get("fingerprint") or make_rewrite_fingerprint(reason, source),
        "enabled": True,
    }

def validate_rewrite_candidate(candidate):
    """Auto-generated docstring."""
    required = {"rule_id", "title", "source", "action", "site_response", "remediation_steps", "fingerprint"}
    missing = sorted(required - set(candidate))
    if missing:
        return False, f"Missing candidate fields: {', '.join(missing)}"
    if not isinstance(candidate.get("remediation_steps"), list) or not candidate["remediation_steps"]:
        return False, "Candidate must include remediation steps"
    return True, "ok"

def apply_rewrite_candidate(entry, candidate):
    """Auto-generated docstring."""
    rules = load_rewrite_rules()
    history = load_rewrite_history()

    existing = next((rule for rule in rules if rule.get("fingerprint") == candidate["fingerprint"]), None)
    if existing:
        result = "reused_existing_rule"
        rule_id = existing["rule_id"]
    else:
        rules.append(candidate)
        save_rewrite_rules(rules)
        result = "created_new_rule"
        rule_id = candidate["rule_id"]

    history.append(
        {
            "processed_at": datetime.now().isoformat(),
            "entry": entry,
            "candidate": candidate,
            "result": result,
        }
    )
    save_rewrite_history(history)

    registry_state = ensure_registry_state()
    registry_state["last_rewrite_execution"] = {
        "processed_at": datetime.now().isoformat(),
        "result": result,
        "rule_id": rule_id,
        "source": entry.get("source"),
    }
    save_registry_state(registry_state)

    return {"result": result, "rule_id": rule_id}

def run_staged_self_rewrite_executor():
    """Auto-generated docstring."""
    backlog = load_rewrite_backlog()
    for entry in backlog:
        if entry.get("status") != "queued":
            continue

        entry["status"] = "analyzing"
        entry["analyzed_at"] = datetime.now().isoformat()
        save_rewrite_backlog(backlog)

        candidate = build_rewrite_candidate(entry)
        valid, validation_message = validate_rewrite_candidate(candidate)
        if not valid:
            entry["status"] = "rejected"
            entry["rejected_at"] = datetime.now().isoformat()
            entry["validation_error"] = validation_message
            save_rewrite_backlog(backlog)
            return

        entry["status"] = "validated"
        entry["validated_at"] = datetime.now().isoformat()
        entry["candidate_rule_id"] = candidate["rule_id"]
        save_rewrite_backlog(backlog)

        result = apply_rewrite_candidate(entry, candidate)
        entry["status"] = "applied"
        entry["applied_at"] = datetime.now().isoformat()
        entry["apply_result"] = result
        save_rewrite_backlog(backlog)
        return

def load_website_state():
    """Auto-generated docstring."""
    default_state = {
        "suggestions": [],
        "error_reports": [],
        "submissions": [],
    }
    if WEBSITE_STATE_FILE.exists():
        try:
            with WEBSITE_STATE_FILE.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                default_state.update(loaded)
        except Exception as exc:
            log_action(f"Failed to load website state: {exc}")
    default_state["suggestions"] = _normalize_entries(default_state.get("suggestions", []), "feedback")
    default_state["error_reports"] = _normalize_entries(default_state.get("error_reports", []), "error")
    if default_state.get("submissions"):
        default_state["submissions"] = _normalize_entries(default_state["submissions"], "feedback")
    else:
        default_state["submissions"] = [
            *default_state["suggestions"],
            *default_state["error_reports"],
        ]
    return default_state

def save_website_state(state):
    """Auto-generated docstring."""
    write_json(WEBSITE_STATE_FILE, state)

def _normalize_entries(entries, default_type):
    """Auto-generated docstring."""
    normalized = []
    for index, entry in enumerate(entries):
        if isinstance(entry, dict):
            normalized.append(
                {
                    "type": entry.get("type", default_type),
                    "message": str(entry.get("message", "")).strip(),
                    "contact": str(entry.get("contact", "")).strip(),
                    "created_at": entry.get("created_at", f"legacy-{index}"),
                }
            )
        elif isinstance(entry, str) and entry.strip():
            normalized.append(
                {
                    "type": default_type,
                    "message": entry.strip(),
                    "contact": "",
                    "created_at": f"legacy-{index}",
                }
            )
    return normalized

def add_submission(entry_type, message, contact=""):
    """Auto-generated docstring."""
    cleaned_message = " ".join(message.split()).strip()
    cleaned_contact = contact.strip()
    state = load_website_state()
    submissions = state.setdefault("submissions", [])

    duplicate = next(
        (
            item
            for item in submissions
            if item.get("type") == entry_type and item.get("message", "").strip().lower() == cleaned_message.lower()
        ),
        None,
    )
    if duplicate:
        return False, duplicate

    entry = {
        "type": entry_type,
        "message": cleaned_message,
        "contact": cleaned_contact,
        "created_at": datetime.now().isoformat(),
    }
    submissions.append(entry)

    key = "suggestions" if entry_type == "feedback" else "error_reports"
    state.setdefault(key, []).append(entry)
    save_website_state(state)
    registry_state = ensure_registry_state()
    registry_state["last_site_submission"] = entry
    save_registry_state(registry_state)
    if entry_type == "feedback" and registry_state.get("auto_apply_site_feedback", True):
        apply_feedback_to_site_config([entry], reason="live_feedback_submission")
    refresh_live_site_template(reason=f"submission:{entry_type}")
    if entry_type == "error":
        queue_code_rewrite(
            reason=entry["message"],
            source="website:error_report",
            severity="high",
        )
    return True, entry

def get_current_template():
    """Auto-generated docstring."""
    if TEMPLATE_FILE.exists():
        try:
            return TEMPLATE_FILE.read_text(encoding="utf-8")
        except Exception as exc:
            log_action(f"Failed to read template: {exc}")
    return None

def save_template(new_html):
    """Auto-generated docstring."""
    try:
        if TEMPLATE_FILE.exists():
            TEMPLATE_BACKUP_FILE.write_text(TEMPLATE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        TEMPLATE_FILE.write_text(new_html, encoding="utf-8")
        log_action("Template saved successfully.")
    except Exception as exc:
        log_action(f"Failed to save template: {exc}")

def evolve_template_with_ollama(feedback_message):
    """Auto-generated docstring."""
    if not ENABLE_OLLAMA_TEMPLATE_EVOLUTION:
        return False

    current_html = get_current_template() or ""
    prompt = (
        "You are an autonomous website agent. "
        "Given the current HTML template and this user feedback, generate a new HTML template that implements the feedback. "
        "Only return the new HTML.\n\n"
        f"Current HTML:\n{current_html}\n\n"
        f"User feedback: {feedback_message}\n"
    )
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        new_html = payload.get("response", "").strip()
        if new_html and "<html" in new_html.lower():
            save_template(new_html)
            log_action("LLM updated website template based on feedback.")
            return True
    except Exception as exc:
        log_action(f"LLM site evolution failed: {exc}")
    return False

def get_site_features_and_content(include_pending_feedback=False):
    """Auto-generated docstring."""
    config = load_site_config()
    features = merge_site_features(config.get("features", {}), {})
    if include_pending_feedback:
        state = load_website_state()
        suggestions = [entry["message"] for entry in state.get("suggestions", [])]
        updates, _, _ = extract_feature_updates_from_messages(suggestions)
        features = merge_site_features(features, updates)
    return features

def build_daily_theme_seed():
    """Auto-generated docstring."""
    now_est = datetime.now(SITE_TIMEZONE)
    return int(now_est.strftime("%Y%m%d"))

def build_daily_palette():
    """Auto-generated docstring."""
    palettes = [
        {"bg_start": "#f5efe6", "bg_end": "#d7e7f5", "accent": "#0f766e", "card": "rgba(255,255,255,0.88)"},
        {"bg_start": "#fef3c7", "bg_end": "#dbeafe", "accent": "#1d4ed8", "card": "rgba(255,255,255,0.90)"},
        {"bg_start": "#fae8ff", "bg_end": "#dcfce7", "accent": "#047857", "card": "rgba(255,255,255,0.90)"},
        {"bg_start": "#ffe4e6", "bg_end": "#e0f2fe", "accent": "#be123c", "card": "rgba(255,255,255,0.89)"},
        {"bg_start": "#ecfccb", "bg_end": "#ede9fe", "accent": "#4338ca", "card": "rgba(255,255,255,0.90)"},
    ]
    rng = random.Random(build_daily_theme_seed())
    return rng.choice(palettes)

def archive_and_clear_site_feedback(reason):
    """Auto-generated docstring."""
    state = load_website_state()
    submissions = state.get("submissions", [])
    if not submissions:
        return None

    archive = load_feedback_archive()
    archive_entry = {
        "archived_at": datetime.now(SITE_TIMEZONE).isoformat(),
        "reason": reason,
        "submissions": submissions,
    }
    archive.append(archive_entry)
    save_feedback_archive(archive)

    state["suggestions"] = []
    state["error_reports"] = []
    state["submissions"] = []
    save_website_state(state)
    return archive_entry

def build_daily_evolved_template():
    """Auto-generated docstring."""
    state = load_website_state()
    rules = load_rewrite_rules()
    intelligence = load_web_intelligence()
    site_config = load_site_config()
    palette = build_daily_palette()
    today_est = datetime.now(SITE_TIMEZONE)
    feedback_items = state.get("suggestions", [])
    error_items = state.get("error_reports", [])
    features = get_site_features_and_content(include_pending_feedback=True)
    quiet_day = not feedback_items and not error_items

    autonomous_upgrades = [
        "Introduced a fresh color story and editorial hero treatment.",
        "Rebalanced spacing and card density for cleaner scanning.",
        "Promoted stronger headline contrast and more focused sections.",
        "Rotated the visual rhythm so the site does not feel frozen day to day.",
        "Refreshed layout emphasis using learned self-fix signals and recent site history.",
    ]
    rng = random.Random(build_daily_theme_seed() + 17)
    selected_upgrades = rng.sample(autonomous_upgrades, k=3)

    feedback_summary = (
        f"{len(feedback_items)} private feedback item(s) were processed during the latest refresh."
        if feedback_items
        else "No new feedback was submitted before this refresh."
    )
    error_summary = (
        f"{len(error_items)} private error report(s) were reviewed during the latest refresh."
        if error_items
        else "No new error reports were submitted before this refresh."
    )
    rules_html = "".join(
        f"<li><strong>{rule['title']}</strong> - {rule['site_response']}</li>" for rule in rules[-5:]
    ) or "<li>No learned rules have been applied yet.</li>"

    sections = "".join(f"<li>{section}</li>" for section in features["custom_sections"]) or "<li>No custom sections yet.</li>"
    autonomous_html = "".join(f"<li>{item}</li>" for item in selected_upgrades)
    ideas_html = "".join(
        f"<li><a href=\"{idea['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{idea['title']}</a> <em>({idea['source']})</em></li>"
        for idea in intelligence.get("ideas", [])[:6]
    ) or "<li>No web design ideas were available during the last scan.</li>"
    top_story_blurbs = "".join(
        (
            f"<li><a href=\"{story['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{story['title']}</a> "
            f"<div class=\"story-blurb\">{story.get('blurb', '')}</div><em>({story['source']})</em></li>"
        )
        for story in intelligence.get("tech_stories", [])[:3]
    ) or "<li>No tech stories were available during the last scan.</li>"
    stories_html = "".join(
        f"<li><a href=\"{story['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{story['title']}</a> <em>({story['source']})</em></li>"
        for story in intelligence.get("tech_stories", [])[3:8]
    ) or "<li>No additional tech stories were available during the last scan.</li>"
    video = intelligence.get("video_inspiration", {})
    youtube_videos_html = "".join(
        f"<li><a href=\"{video['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{video['title']}</a> by {video['author']}<div class=\"story-blurb\">{video['reason']}</div></li>"
        for video in intelligence.get("youtube_videos", [])[:4]
    ) or "<li>No tech video picks are available right now.</li>"
    video_title = video.get("title", "Self-improving agent inspiration")
    video_author = video.get("author", "Unknown creator")
    video_source = video.get("source_url", "https://www.youtube.com/watch?v=97irLVqYJCI")
    video_concepts_html = "".join(f"<li>{concept}</li>" for concept in video.get("concepts", []))
    video_adaptations_html = "".join(
        f"<li>{concept}</li>" for concept in video.get("implemented_adaptations", [])
    ) or "<li>No implemented adaptations recorded yet.</li>"
    refresh_summary = (
        "No new visitor feedback arrived today, so the site generated its own visual improvements for this refresh."
        if quiet_day
        else "The site refreshed itself using the most recent feedback, error reports, and learned self-fix rules."
    )
    implemented_feedback_html = "".join(
        f"<li><strong>{entry['message']}</strong><div class=\"story-blurb\">{', '.join(entry.get('applied', []))}</div></li>"
        for entry in site_config.get("implemented_feedback", [])[-6:]
    ) or "<li>No feedback has been auto-implemented yet.</li>"
    adaptive_requests_html = render_adaptive_request_links(limit=6)
    pending_downtime_html = render_pending_downtime_links(limit=6)
    personalization_html = build_personalization_panel()

    return f"""
    <html>
    <head>
        <title>skynetv1 Daily Evolution</title>
        <style>
            :root {{
                --bg-start: {palette['bg_start']};
                --bg-end: {palette['bg_end']};
                --accent: {palette['accent']};
                --card: {palette['card']};
                --ink: #172033;
            }}
            body {{
                margin: 0;
                font-family: Georgia, 'Times New Roman', serif;
                color: var(--ink);
                background:
                    radial-gradient(circle at top left, rgba(255,255,255,0.8), transparent 34%),
                    linear-gradient(135deg, var(--bg-start), var(--bg-end));
            }}
            .page {{
                max-width: 1180px;
                margin: 0 auto;
                padding: 28px 18px 56px;
            }}
            .hero {{
                background: linear-gradient(145deg, rgba(255,255,255,0.92), rgba(255,255,255,0.74));
                border: 1px solid rgba(255,255,255,0.55);
                border-radius: 24px;
                padding: 30px;
                box-shadow: 0 20px 50px rgba(23, 32, 51, 0.12);
            }}
            .eyebrow {{
                letter-spacing: 0.2em;
                text-transform: uppercase;
                font-size: 12px;
                color: var(--accent);
            }}
            .hero h1 {{
                margin: 10px 0 12px;
                font-size: clamp(2.2rem, 5vw, 4.8rem);
                line-height: 0.95;
            }}
            .hero p {{
                max-width: 760px;
                font-size: 1.05rem;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                gap: 18px;
                margin-top: 20px;
            }}
            .tabs {{
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin: 18px 0 4px;
            }}
            .tabs a {{
                text-decoration: none;
                color: var(--ink);
                background: rgba(255,255,255,0.72);
                padding: 10px 14px;
                border-radius: 999px;
                font-weight: bold;
            }}
            .card {{
                background: var(--card);
                border-radius: 20px;
                padding: 20px;
                box-shadow: 0 14px 34px rgba(23, 32, 51, 0.09);
            }}
            h2 {{
                margin-top: 0;
                color: var(--accent);
            }}
            ul {{
                padding-left: 18px;
                margin-bottom: 0;
            }}
            .badge {{
                display: inline-block;
                padding: 6px 10px;
                background: rgba(255,255,255,0.7);
                border-radius: 999px;
                margin-right: 8px;
                margin-bottom: 8px;
            }}
            label {{
                display: block;
                font-weight: bold;
                margin-bottom: 8px;
            }}
            input, textarea {{
                width: 100%;
                box-sizing: border-box;
                padding: 10px 12px;
                border: 1px solid rgba(23, 32, 51, 0.18);
                border-radius: 12px;
                margin-bottom: 10px;
            }}
            textarea {{
                min-height: 110px;
                resize: vertical;
            }}
            button {{
                background: var(--accent);
                color: white;
                border: 0;
                border-radius: 999px;
                padding: 10px 18px;
                cursor: pointer;
            }}
            .story-blurb {{
                margin: 8px 0;
                line-height: 1.45;
            }}
            .save-item-btn {{
                margin-left: 10px;
                background: var(--accent);
                color: white;
                border: 0;
                border-radius: 999px;
                padding: 8px 12px;
                cursor: pointer;
            }}
        </style>
    </head>
    <body>
        <div class="page">
            <section class="hero">
                <div class="eyebrow">Daily Evolution</div>
                <h1>{features['custom_title']}</h1>
                <p>The site refreshed itself on {today_est.strftime('%B %d, %Y at %I:%M %p %Z')}. {refresh_summary}</p>
                <div class="badge">Auto-refresh at 1:00 AM EST</div>
                <div class="badge">Feedback applied and archived</div>
                <div class="badge">Learned rules: {len(rules)}</div>
                <div class="badge">Autonomous design fallback: {"on" if quiet_day else "standby"}</div>
            </section>
            <nav class="tabs">
                <a href="#changes">Changes</a>
                <a href="#news">Top Stories</a>
                <a href="#ideas">Design Ideas</a>
                <a href="#video">Video Upgrades</a>
                <a href="#adaptive-requests">Requests</a>
                <a href="#feedback">Feedback</a>
                <a href="#errors">Errors</a>
            </nav>
            <section class="grid">
                <article class="card" id="changes">
                    <h2>What Changed</h2>
                    <ul>{sections}</ul>
                </article>
                <article class="card" id="feedback">
                    <h2>Feedback Processed</h2>
                    <p>{feedback_summary}</p>
                </article>
                <article class="card" id="errors">
                    <h2>Error Reports Reviewed</h2>
                    <p>{error_summary}</p>
                </article>
                <article class="card">
                    <h2>Learned Self-Fix Rules</h2>
                    <ul>{rules_html}</ul>
                </article>
                <article class="card">
                    <h2>Autonomous Improvements</h2>
                    <ul>{autonomous_html}</ul>
                </article>
                <article class="card">
                    <h2>Implemented Overnight</h2>
                    <ul>{implemented_feedback_html}</ul>
                </article>
                <article class="card" id="adaptive-requests">
                    <h2>Adaptive Request Pages</h2>
                    <ul>{adaptive_requests_html}</ul>
                </article>
                <article class="card">
                    <h2>Queued For Downtime</h2>
                    <ul>{pending_downtime_html}</ul>
                </article>
                {personalization_html}
                <article class="card" id="ideas">
                    <h2>Web Design Ideas</h2>
                    <ul>{ideas_html}</ul>
                </article>
                <article class="card" id="news">
                    <h2>Top 3 Story Briefs</h2>
                    <ul>{top_story_blurbs}</ul>
                </article>
                <article class="card">
                    <h2>Top Tech Stories</h2>
                    <ul>{stories_html}</ul>
                </article>
                <article class="card" id="video">
                    <h2>Video-Inspired Upgrades</h2>
                    <p><a href="{video_source}" target="_blank" rel="noopener noreferrer">{video_title}</a> by {video_author}</p>
                    <h3>Concepts Pulled In</h3>
                    <ul>{video_concepts_html}</ul>
                    <h3>Applied To This Codebase</h3>
                    <ul>{video_adaptations_html}</ul>
                </article>
                <article class="card">
                    <h2>Tech YouTube Picks</h2>
                    <ul>{youtube_videos_html}</ul>
                </article>
                <article class="card">
                    <h2>Send New Feedback</h2>
                    <form method="post">
                        <input type="hidden" name="entry_type" value="feedback">
                        <label for="feedback_message">Feedback message</label>
                        <textarea id="feedback_message" name="message" required></textarea>
                        <label for="feedback_contact">Email or contact</label>
                        <input id="feedback_contact" type="text" name="contact" placeholder="name@example.com">
                        <button type="submit">Submit feedback</button>
                    </form>
                </article>
                <article class="card">
                    <h2>Report a New Error</h2>
                    <form method="post">
                        <input type="hidden" name="entry_type" value="error">
                        <label for="error_message">What went wrong?</label>
                        <textarea id="error_message" name="message" required></textarea>
                        <label for="error_contact">Email or contact</label>
                        <input id="error_contact" type="text" name="contact" placeholder="name@example.com">
                        <button type="submit">Report error</button>
                    </form>
                </article>
            </section>
            {build_personalization_assets()}
        </div>
    </body>
    </html>
    """

def refresh_live_site_template(reason="live_update"):
    """Auto-generated docstring."""
    try:
        template = build_daily_evolved_template()
        save_template(template)
        registry_state = ensure_registry_state()
        registry_state["last_live_site_refresh_at"] = datetime.now(SITE_TIMEZONE).isoformat()
        registry_state["last_live_site_refresh_reason"] = reason
        save_registry_state(registry_state)
        return True
    except Exception as exc:
        log_action(f"Live site refresh failed ({reason}): {exc}")
        return False

def build_site_nav():
    """Auto-generated docstring."""
    items = [
        ("Changes", "/changes"),
        ("Requests", "/requests"),
        ("Project Chatbot", "/project-chat"),
        ("Top Stories", "/top-stories"),
        ("Design Ideas", "/design-ideas"),
        ("Tech Videos", "/tech-videos"),
        ("Video Upgrades", "/video-upgrades"),
        ("Feedback", "/feedback"),
        ("Errors", "/errors"),
    ]
    return "".join(f'<a href="{href}">{label}</a>' for label, href in items)

def build_personalization_panel():
    """Auto-generated docstring."""
    features = get_site_features_and_content()
    if not (features.get("signup") or features.get("saved_items") or features.get("recommendations")):
        return ""

    intelligence = load_web_intelligence()
    story_items = "".join(
        (
            "<li>"
            f"<a href=\"{story['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{story['title']}</a> "
            f"<button class=\"save-item-btn\" data-kind=\"story\" data-title=\"{story['title']}\" data-url=\"{story['url']}\" data-source=\"{story['source']}\">Save</button>"
            "</li>"
        )
        for story in intelligence.get("tech_stories", [])[:5]
    ) or "<li>No stories available to save yet.</li>"
    video_items = "".join(
        (
            "<li>"
            f"<a href=\"{video['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{video['title']}</a> "
            f"<button class=\"save-item-btn\" data-kind=\"video\" data-title=\"{video['title']}\" data-url=\"{video['url']}\" data-source=\"{video['author']}\">Save</button>"
            "</li>"
        )
        for video in intelligence.get("youtube_videos", [])[:4]
    ) or "<li>No videos available to save yet.</li>"

    signup_card = ""
    if features.get("signup"):
        signup_card = """
        <section class="card">
            <h2>Free Sign-Up</h2>
            <p>Create a lightweight profile on this browser so the site can remember what you save and recommend more of it.</p>
            <form id="signup-form">
                <label for="signup_name">Name</label>
                <input id="signup_name" name="name" type="text" placeholder="Your name">
                <label for="signup_email">Email</label>
                <input id="signup_email" name="email" type="email" placeholder="name@example.com">
                <button type="submit">Save profile</button>
            </form>
            <p id="signup-status"></p>
        </section>
        """

    saved_card = ""
    if features.get("saved_items"):
        saved_card = f"""
        <section class="card">
            <h2>Save Things You Like</h2>
            <p>Use these save buttons to keep stories and videos you want to come back to.</p>
            <ul>{story_items}{video_items}</ul>
            <h3>Saved Items</h3>
            <ul data-saved-items><li>No saved items yet.</li></ul>
        </section>
        """

    recommendation_card = ""
    if features.get("recommendations"):
        recommendation_card = """
        <section class="card">
            <h2>Recommended for You</h2>
            <p>Recommendations update from the stories and videos you save on this browser.</p>
            <ul data-recommendations><li>Save a few items to personalize this list.</li></ul>
        </section>
        """

    return signup_card + saved_card + recommendation_card

def build_personalization_assets():
    """Auto-generated docstring."""
    features = get_site_features_and_content()
    if not (features.get("signup") or features.get("saved_items") or features.get("recommendations")):
        return ""

    intelligence = load_web_intelligence()
    catalog = []
    for story in intelligence.get("tech_stories", [])[:10]:
        catalog.append(
            {
                "kind": "story",
                "title": story["title"],
                "url": story["url"],
                "source": story["source"],
            }
        )
    for video in intelligence.get("youtube_videos", [])[:8]:
        catalog.append(
            {
                "kind": "video",
                "title": video["title"],
                "url": video["url"],
                "source": video["author"],
            }
        )

    return f"""
    <script>
    (() => {{
        const profileKey = "skynet_profile_v1";
        const savedKey = "skynet_saved_items_v1";
        const catalog = {json.dumps(catalog)};

        const read = (key, fallback) => {{
            try {{
                const raw = localStorage.getItem(key);
                return raw ? JSON.parse(raw) : fallback;
            }} catch (error) {{
                return fallback;
            }}
        }};

        const write = (key, value) => localStorage.setItem(key, JSON.stringify(value));

        const renderProfile = () => {{
            const profile = read(profileKey, {{}});
            const form = document.getElementById("signup-form");
            const status = document.getElementById("signup-status");
            if (form) {{
                form.name.value = profile.name || "";
                form.email.value = profile.email || "";
            }}
            if (status && profile.name) {{
                status.textContent = `Profile saved for ${{profile.name}}.`;
            }}
        }};

        const renderSavedItems = () => {{
            const saved = read(savedKey, []);
            document.querySelectorAll("[data-saved-items]").forEach((list) => {{
                if (!saved.length) {{
                    list.innerHTML = "<li>No saved items yet.</li>";
                    return;
                }}
                list.innerHTML = saved.map((item) =>
                    `<li><a href="${{item.url}}" target="_blank" rel="noopener noreferrer">${{item.title}}</a> <em>(${{item.kind}})</em></li>`
                ).join("");
            }});
        }};

        const renderRecommendations = () => {{
            const saved = read(savedKey, []);
            const savedUrls = new Set(saved.map((item) => item.url));
            const keywords = new Set(
                saved.flatMap((item) =>
                    item.title.toLowerCase().split(/[^a-z0-9]+/).filter((word) => word.length > 4)
                )
            );
            let recommendations = catalog
                .filter((item) => !savedUrls.has(item.url))
                .map((item) => {{
                    let score = 0;
                    if (saved.some((savedItem) => savedItem.source === item.source)) {{
                        score += 2;
                    }}
                    for (const word of keywords) {{
                        if (item.title.toLowerCase().includes(word)) {{
                            score += 1;
                        }}
                    }}
                    return {{ ...item, score }};
                }})
                .sort((a, b) => b.score - a.score);

            if (!saved.length) {{
                recommendations = recommendations.slice(0, 5);
            }} else {{
                recommendations = recommendations.filter((item) => item.score > 0).slice(0, 5);
            }}

            document.querySelectorAll("[data-recommendations]").forEach((list) => {{
                if (!recommendations.length) {{
                    list.innerHTML = "<li>Save a few items to personalize this list.</li>";
                    return;
                }}
                list.innerHTML = recommendations.map((item) =>
                    `<li><a href="${{item.url}}" target="_blank" rel="noopener noreferrer">${{item.title}}</a> <em>(${{item.kind}})</em></li>`
                ).join("");
            }});
        }};

        document.addEventListener("click", (event) => {{
            const button = event.target.closest(".save-item-btn");
            if (!button) {{
                return;
            }}
            const saved = read(savedKey, []);
            const item = {{
                kind: button.dataset.kind,
                title: button.dataset.title,
                url: button.dataset.url,
                source: button.dataset.source
            }};
            if (!saved.some((savedItem) => savedItem.url === item.url)) {{
                saved.push(item);
                write(savedKey, saved);
            }}
            renderSavedItems();
            renderRecommendations();
        }});

        document.addEventListener("submit", (event) => {{
            const form = event.target;
            if (!form || form.id !== "signup-form") {{
                return;
            }}
            event.preventDefault();
            write(profileKey, {{
                name: form.name.value.trim(),
                email: form.email.value.trim()
            }});
            renderProfile();
        }});

        document.addEventListener("DOMContentLoaded", () => {{
            renderProfile();
            renderSavedItems();
            renderRecommendations();
        }});
    }})();
    </script>
    """

def build_page_shell(title, intro, body_html):
    """Auto-generated docstring."""
    personalization_assets = build_personalization_assets()
    return f"""
    <html>
    <head>
        <title>{title}</title>
        <style>
            body {{
                margin: 0;
                font-family: Georgia, 'Times New Roman', serif;
                color: #172033;
                background:
                    radial-gradient(circle at top left, rgba(255,255,255,0.8), transparent 34%),
                    linear-gradient(135deg, #fef3c7, #dbeafe);
            }}
            .page {{
                max-width: 1180px;
                margin: 0 auto;
                padding: 28px 18px 56px;
            }}
            .hero {{
                background: linear-gradient(145deg, rgba(255,255,255,0.92), rgba(255,255,255,0.74));
                border: 1px solid rgba(255,255,255,0.55);
                border-radius: 24px;
                padding: 30px;
                box-shadow: 0 20px 50px rgba(23, 32, 51, 0.12);
            }}
            .tabs {{
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin: 18px 0 4px;
            }}
            .tabs a {{
                text-decoration: none;
                color: #172033;
                background: rgba(255,255,255,0.72);
                padding: 10px 14px;
                border-radius: 999px;
                font-weight: bold;
            }}
            .card {{
                background: rgba(255,255,255,0.9);
                border-radius: 20px;
                padding: 20px;
                box-shadow: 0 14px 34px rgba(23, 32, 51, 0.09);
                margin-top: 18px;
            }}
            ul {{
                padding-left: 18px;
                margin-bottom: 0;
            }}
            .story-blurb {{
                margin: 8px 0;
                line-height: 1.45;
            }}
            label {{
                display: block;
                font-weight: bold;
                margin-bottom: 8px;
            }}
            input, textarea {{
                width: 100%;
                box-sizing: border-box;
                padding: 10px 12px;
                border: 1px solid rgba(23, 32, 51, 0.18);
                border-radius: 12px;
                margin-bottom: 10px;
            }}
            textarea {{
                min-height: 110px;
                resize: vertical;
            }}
            button {{
                background: #1d4ed8;
                color: white;
                border: 0;
                border-radius: 999px;
                padding: 10px 18px;
                cursor: pointer;
            }}
            .save-item-btn {{
                margin-left: 10px;
                background: #0f766e;
            }}
        </style>
    </head>
    <body>
        <div class="page">
            <section class="hero">
                <h1>{title}</h1>
                <p>{intro}</p>
            </section>
            <nav class="tabs">
                {build_site_nav()}
            </nav>
            {body_html}
        </div>
        {personalization_assets}
    </body>
    </html>
    """

def is_valid_contact_email(value):
    """Auto-generated docstring."""
    email = str(value or "").strip()
    return bool(EMAIL_PATTERN.match(email))

def build_homepage_chatbot_bubble():
    """Auto-generated docstring."""
    return """
    <style>
        .chatbot-fab {
            position: fixed;
            right: 20px;
            bottom: 20px;
            z-index: 9999;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            border: 0;
            border-radius: 999px;
            padding: 12px 16px;
            background: #0f766e;
            color: #ffffff;
            box-shadow: 0 12px 28px rgba(15, 118, 110, 0.38);
            font-weight: 700;
            cursor: pointer;
        }
        .chatbot-fab-panel {
            position: fixed;
            right: 20px;
            bottom: 78px;
            z-index: 9998;
            width: min(340px, calc(100vw - 32px));
            background: #ffffff;
            border: 1px solid #d1d5db;
            border-radius: 16px;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.18);
            padding: 14px;
            display: none;
        }
        .chatbot-fab-panel.open {
            display: block;
        }
        .chatbot-fab-panel h3 {
            margin: 0 0 8px;
            font-size: 18px;
        }
        .chatbot-fab-panel p {
            margin: 0 0 10px;
            line-height: 1.4;
            color: #334155;
        }
        .chatbot-fab-panel a {
            display: inline-block;
            text-decoration: none;
            background: #1d4ed8;
            color: #ffffff;
            border-radius: 999px;
            padding: 10px 14px;
            font-weight: 700;
        }
    </style>
    <div id="chatbot-fab-panel" class="chatbot-fab-panel" aria-hidden="true">
        <h3>Need something built?</h3>
        <p>Open the Project Chatbot request form. A valid delivery email is required for every request.</p>
        <a href="/project-chat">Start Project Request</a>
    </div>
    <button id="chatbot-fab-button" type="button" class="chatbot-fab" aria-expanded="false" aria-controls="chatbot-fab-panel">
        Chatbot Request
    </button>
    <script>
        (function () {
            const button = document.getElementById("chatbot-fab-button");
            const panel = document.getElementById("chatbot-fab-panel");
            if (!button || !panel) {
                return;
            }
            button.addEventListener("click", function () {
                const isOpen = panel.classList.toggle("open");
                button.setAttribute("aria-expanded", isOpen ? "true" : "false");
                panel.setAttribute("aria-hidden", isOpen ? "false" : "true");
            });
        })();
    </script>
    """

def inject_homepage_chatbot_bubble(html):
    """Auto-generated docstring."""
    if not html:
        return html
    if "chatbot-fab-button" in html:
        return html
    bubble = build_homepage_chatbot_bubble()
    if "</body>" in html:
        return html.replace("</body>", bubble + "\n</body>", 1)
    return html + bubble

def build_changes_page():
    """Auto-generated docstring."""
    features = get_site_features_and_content()
    site_config = load_site_config()
    custom_sections = "".join(
        f"<li>{section}</li>" for section in features["custom_sections"]
    ) or "<li>No custom sections have been added yet.</li>"
    implemented_items = "".join(
        f"<li><strong>{entry['message']}</strong><div class='story-blurb'>{', '.join(entry.get('applied', []))}</div></li>"
        for entry in site_config.get("implemented_feedback", [])[-8:]
    ) or "<li>No feedback has been auto-implemented yet.</li>"
    adaptive_pages_html = render_adaptive_request_links(limit=10)
    pending_downtime_html = render_pending_downtime_links(limit=10)
    body = f"""
    <section class="card">
        <h2>Planned Improvements</h2>
        <ul>
            <li>New submissions are reviewed privately and queued in the backend.</li>
            <li>The site refreshes at 1:00 AM Eastern Time to roll in approved changes.</li>
            <li>Daily visual improvements can still happen even on quiet days.</li>
        </ul>
    </section>
    <section class="card">
        <h2>Current Custom Sections</h2>
        <ul>{custom_sections}</ul>
    </section>
    <section class="card">
        <h2>Auto-Implemented Feedback</h2>
        <ul>{implemented_items}</ul>
    </section>
    <section class="card">
        <h2>Adaptive Request Pages</h2>
        <ul>{adaptive_pages_html}</ul>
    </section>
    <section class="card">
        <h2>Queued For Downtime</h2>
        <ul>{pending_downtime_html}</ul>
    </section>
    {build_personalization_panel()}
    """
    return build_page_shell("Changes", "The latest requested changes shaping the next site refresh.", body)

def build_requests_page():
    """Auto-generated docstring."""
    pages = get_adaptive_pages()
    pending_html = render_pending_downtime_links(limit=12)
    request_items = "".join(
        f"<li><a href=\"/requests/{page['slug']}\">{page['title']}</a><div class='story-blurb'>{page['summary']}</div></li>"
        for page in reversed(pages)
    ) or "<li>No adaptive request pages are available yet.</li>"
    body = f"""
    <section class="card">
        <h2>Queued For Downtime Integration</h2>
        <ul>{pending_html}</ul>
    </section>
    <section class="card">
        <h2>Adaptive Request Library</h2>
        <p>Every request listed here was turned into a dedicated site destination automatically.</p>
        <ul>{request_items}</ul>
    </section>
    """
    return build_page_shell("Requests", "Dedicated pages generated from visitor feedback.", body)

def build_request_detail_page(page):
    """Auto-generated docstring."""
    section_html = "".join(
        "<section class=\"card\">"
        f"<h2>{section.get('heading', 'Details')}</h2>"
        f"<ul>{''.join(f'<li>{item}</li>' for item in section.get('items', [])) or '<li>No details yet.</li>'}</ul>"
        "</section>"
        for section in page.get("sections", [])
    )
    tags_html = "".join(f"<li>{tag}</li>" for tag in page.get("tags", [])) or "<li>general</li>"
    body = f"""
    <section class="card">
        <h2>Original Request</h2>
        <p>{page.get('source_message', '')}</p>
    </section>
    <section class="card">
        <h2>Tags</h2>
        <ul>{tags_html}</ul>
    </section>
    {section_html}
    """
    return build_page_shell(page.get("title", "Adaptive Request"), page.get("intro", ""), body)

def build_top_stories_page():
    """Auto-generated docstring."""
    intelligence = load_web_intelligence()
    top_story_blurbs = "".join(
        (
            f"<li><a href=\"{story['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{story['title']}</a>"
            f"<div class='story-blurb'>{story.get('blurb', '')}</div><em>({story['source']})</em></li>"
        )
        for story in intelligence.get("tech_stories", [])[:10]
    ) or "<li>No top stories are available right now.</li>"
    body = f"""
    <section class="card">
        <h2>Top Tech Stories</h2>
        <ul>{top_story_blurbs}</ul>
    </section>
    """
    return build_page_shell("Top Stories", "Readable tech headlines with short blurbs.", body)

def build_design_ideas_page():
    """Auto-generated docstring."""
    intelligence = load_web_intelligence()
    idea_items = "".join(
        f"<li><a href=\"{idea['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{idea['title']}</a> <em>({idea['source']})</em></li>"
        for idea in intelligence.get("ideas", [])
    ) or "<li>No design ideas are available right now.</li>"
    body = f"""
    <section class="card">
        <h2>Web Design Ideas</h2>
        <ul>{idea_items}</ul>
    </section>
    """
    return build_page_shell("Design Ideas", "Current web inspiration the site can learn from.", body)

def build_video_upgrades_page():
    """Auto-generated docstring."""
    intelligence = load_web_intelligence()
    video = intelligence.get("video_inspiration", {})
    concepts = "".join(f"<li>{concept}</li>" for concept in video.get("concepts", [])) or "<li>No concepts loaded.</li>"
    adaptations = "".join(
        f"<li>{item}</li>" for item in video.get("implemented_adaptations", [])
    ) or "<li>No adaptations recorded.</li>"
    body = f"""
    <section class="card">
        <h2>Video Inspiration</h2>
        <p><a href="{video.get('source_url', '#')}" target="_blank" rel="noopener noreferrer">{video.get('title', 'Video')}</a> by {video.get('author', 'Unknown')}</p>
    </section>
    <section class="card">
        <h2>Concepts Pulled In</h2>
        <ul>{concepts}</ul>
    </section>
    <section class="card">
        <h2>Applied Upgrades</h2>
        <ul>{adaptations}</ul>
    </section>
    """
    return build_page_shell("Video Upgrades", "How the self-improving agent video is influencing this project.", body)

def build_tech_videos_page():
    """Auto-generated docstring."""
    intelligence = load_web_intelligence()
    video_items = "".join(
        f"<li><a href=\"{video['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{video['title']}</a> by {video['author']}<div class='story-blurb'>{video['reason']}</div></li>"
        for video in intelligence.get("youtube_videos", [])
    ) or "<li>No tech videos are available right now.</li>"
    body = f"""
    <section class="card">
        <h2>Tech YouTube Picks</h2>
        <ul>{video_items}</ul>
    </section>
    """
    return build_page_shell("Tech Videos", "A rotating list of tech-related YouTube videos and channels.", body)

def build_feedback_page(status_message=""):
    """Auto-generated docstring."""
    state = load_website_state()
    queued_feedback = list(reversed(state.get("suggestions", [])))[:5]
    queued_html = "".join(
        f"<li><strong>{entry.get('created_at', '')}</strong> - {entry.get('message', '')}</li>"
        for entry in queued_feedback
    ) or "<li>No feedback is currently queued.</li>"
    status_html = f"<div class='card'><p>{status_message}</p></div>" if status_message else ""
    body = f"""
    {status_html}
    <section class="card">
        <h2>Send Feedback</h2>
        <p>Your message will be stored privately, queued in the backend, and reviewed for implementation during the next update cycle.</p>
        <form method="post" action="/">
            <input type="hidden" name="entry_type" value="feedback">
            <label for="feedback_message">Feedback message</label>
            <textarea id="feedback_message" name="message" required></textarea>
            <label for="feedback_contact">Email or contact</label>
            <input id="feedback_contact" type="text" name="contact" placeholder="name@example.com">
            <button type="submit">Submit feedback</button>
        </form>
    </section>
    <section class="card">
        <h2>Queued Feedback</h2>
        <p>{len(state.get("suggestions", []))} feedback item(s) are currently waiting for the next site evolution.</p>
        <ul>{queued_html}</ul>
    </section>
    """
    return build_page_shell("Feedback", "Share ideas that should shape the next evolution cycle.", body)

def build_errors_page(status_message=""):
    """Auto-generated docstring."""
    state = load_website_state()
    queued_errors = list(reversed(state.get("error_reports", [])))[:5]
    queued_html = "".join(
        f"<li><strong>{entry.get('created_at', '')}</strong> - {entry.get('message', '')}</li>"
        for entry in queued_errors
    ) or "<li>No error reports are currently queued.</li>"
    status_html = f"<div class='card'><p>{status_message}</p></div>" if status_message else ""
    body = f"""
    {status_html}
    <section class="card">
        <h2>Report an Error</h2>
        <p>Error reports are stored privately and sent into the backend review queue.</p>
        <form method="post" action="/">
            <input type="hidden" name="entry_type" value="error">
            <label for="error_message">What went wrong?</label>
            <textarea id="error_message" name="message" required></textarea>
            <label for="error_contact">Email or contact</label>
            <input id="error_contact" type="text" name="contact" placeholder="name@example.com">
            <button type="submit">Report error</button>
        </form>
    </section>
    <section class="card">
        <h2>Queued Error Reports</h2>
        <p>{len(state.get("error_reports", []))} error report(s) are currently waiting for the next review cycle.</p>
        <ul>{queued_html}</ul>
    </section>
    """
    return build_page_shell("Errors", "Report bugs and broken flows directly to the site.", body)

def build_project_chat_page(status_message=""):
    """Auto-generated docstring."""
    recent = get_recent_chatbot_requests(limit=8)
    ranked_queue = load_market_process_state().get("ranked_queue", [])
    ranked_lookup = {item.get("id"): item for item in ranked_queue}
    requests_html = "".join(
        (
            f"<li><strong>{item.get('id')}</strong> - {item.get('title')}"
            f"<div class='story-blurb'>Estimated budget: ${item.get('estimate_usd')} "
            f"(range ${item.get('range_low_usd')} - ${item.get('range_high_usd')})</div>"
            f"<div class='story-blurb'>Upfront payment: ${item.get('upfront_payment_required_usd', 'N/A')} | "
            f"Escrow: {item.get('escrow_status', 'N/A')} | Status: {item.get('status')}</div>"
            f"<div class='story-blurb'>Payment: deposit={((item.get('payment') or {}).get('deposit_status', 'UNPAID'))} | "
            f"final={((item.get('payment') or {}).get('final_status', 'UNPAID'))}</div>"
            f"<div class='story-blurb'>Payment events: {len(((item.get('payment') or {}).get('events') or []))} | "
            f"Final reminders: {int(((item.get('payment') or {}).get('final_payment_reminder_count') or 0))}</div>"
            f"<div class='story-blurb'>Promo code (100% off): {((item.get('promo') or {}).get('code') or 'N/A')}</div>"
            f"<div class='story-blurb'>Next action: {item.get('next_action')}</div>"
            f"<div class='story-blurb'>Score: {item.get('score', 'N/A')} | Rank: {ranked_lookup.get(item.get('id'), {}).get('order', 'N/A')}</div>"
            f"<form method='get' action='/project-chat/payment'>"
            f"<input type='hidden' name='request_id' value='{item.get('id', '')}'>"
            "<button type='submit'>Open Payment Page</button>"
            "</form>"
            "<form method='post' action='/project-chat/action'>"
            f"<input type='hidden' name='request_id' value='{item.get('id', '')}'>"
            "<button type='submit' name='action' value='approve'>Approve</button> "
            "<button type='submit' name='action' value='verify'>Mark VERIFIED_WON + FUNDED</button> "
            "<button type='submit' name='action' value='build_now'>Build Now</button>"
            "</form>"
            "</li>"
        )
        for item in recent
    ) or "<li>No chatbot project requests are queued yet.</li>"
    status_html = f"<div class='card'><p>{status_message}</p></div>" if status_message else ""

    body = f"""
    {status_html}
    <section class="card">
        <h2>Project Request Chatbot</h2>
        <p>Describe the project you want built. New requests now require an upfront payment approval and, once confirmed, they are auto-posted into the build queue without waiting for manual triage.</p>
        <form method="post" action="/project-chat">
            <label for="project_request">What project do you want built?</label>
            <textarea id="project_request" name="message" required></textarea>
            <label for="project_contact">Delivery email</label>
            <input id="project_contact" type="email" name="contact" placeholder="name@example.com" required>
            <label>
                <input type="checkbox" name="upfront_payment_ack" value="yes" required>
                I approve the required upfront payment so the build can start immediately after submission.
            </label>
            <button type="submit">Approve Deposit and Start Queue</button>
        </form>
    </section>
    <section class="card">
        <h2>Recent Chatbot Requests</h2>
        <form method="post" action="/project-chat/rank">
            <button type="submit">Run Automatic Phase 2.2 Ranking</button>
        </form>
        <ul>{requests_html}</ul>
    </section>
    """
    return build_page_shell("Project Chatbot", "Submit project ideas and push them into the Market Agent pipeline.", body)

def build_project_payment_page(request_id="", status_message=""):
    """Auto-generated docstring."""
    state = load_market_process_state()
    _, entry, payment = _payment_state_for_request(state, request_id) if request_id else (None, None, None)
    if not entry or payment is None:
        body = (
            f"<section class='card'><h2>Payment</h2><p>{status_message or 'Request not found.'}</p>"
            "<p>Open this page with a valid request id from Project Chat.</p></section>"
        )
        return build_page_shell("Project Payment", "Pay deposit and final balance for chatbot project requests.", body)

    deposit_status = payment.get("deposit_status", "UNPAID")
    final_status = payment.get("final_status", "UNPAID")
    deposit_amount = float(payment.get("deposit_amount_usd", 0) or 0)
    final_amount = float(payment.get("final_amount_usd", 0) or 0)
    promo = _apply_promo_defaults(entry)
    promo_code = str(promo.get("code", "")).strip()
    promo_applied = bool(promo.get("applied", False))
    req_id_safe = escape(str(entry.get("id", "")))

    body = f"""
    <section class="card">
        <h2>Project Payment</h2>
        <p>{status_message or 'Complete checkout to unlock build and final delivery.'}</p>
        <div class='story-blurb'><strong>Request ID:</strong> {req_id_safe}</div>
        <div class='story-blurb'><strong>Project:</strong> {escape(str(entry.get('title', '')))}</div>
        <div class='story-blurb'><strong>Total:</strong> ${float(payment.get('total_amount_usd', 0) or 0):.2f}</div>
        <div class='story-blurb'><strong>Deposit:</strong> ${deposit_amount:.2f} ({deposit_status})</div>
        <div class='story-blurb'><strong>Final:</strong> ${final_amount:.2f} ({final_status})</div>
        <div class='story-blurb'><strong>Provider:</strong> {escape(str(payment.get('provider', 'stripe')))}</div>
        <div class='story-blurb'><strong>Promo code:</strong> {escape(promo_code)} ({'applied' if promo_applied else 'not applied'})</div>
        <div class='story-blurb'><strong>Final reminders sent:</strong> {int(payment.get('final_payment_reminder_count', 0) or 0)}</div>
        <div class='story-blurb'><strong>Next reminder:</strong> {escape(_format_iso_timestamp(payment.get('next_final_payment_reminder_at')))}</div>
    </section>
    <section class="card">
        <h2>100% Off Promo</h2>
        <p>Use this promo code to waive payment in full: <strong>{escape(promo_code)}</strong></p>
        <form method="post" action="/project-chat/payment/promo">
            <input type="hidden" name="request_id" value="{req_id_safe}">
            <label for="promo_code_input">Promo code</label>
            <input id="promo_code_input" type="text" name="promo_code" value="{escape(promo_code)}" required>
            <button type="submit">Apply 100% Off Promo</button>
        </form>
    </section>
    <section class="card">
        <h2>Checkout Actions</h2>
        <form method="post" action="/project-chat/payment/checkout">
            <input type="hidden" name="request_id" value="{req_id_safe}">
            <input type="hidden" name="stage" value="deposit">
            <button type="submit">Pay Deposit (${deposit_amount:.2f})</button>
        </form>
        <form method="post" action="/project-chat/payment/checkout">
            <input type="hidden" name="request_id" value="{req_id_safe}">
            <input type="hidden" name="stage" value="final">
            <button type="submit">Pay Final (${final_amount:.2f})</button>
        </form>
        <p class='story-blurb'>Cash App Pay is available through Stripe Checkout when enabled in your Stripe dashboard and supported by your account/region.</p>
    </section>
    <section class="card">
        <h2>Payment Timeline</h2>
        {render_payment_timeline(entry, payment)}
    </section>
    <section class="card">
        <h2>Webhook and Payment Events</h2>
        {render_payment_event_log(payment)}
    </section>
    """
    return build_page_shell("Project Payment", "Pay deposit and final balance for chatbot project requests.", body)

def run_daily_site_evolution(reason="scheduled"):
    """Auto-generated docstring."""
    state = load_website_state()
    apply_feedback_to_site_config(state.get("submissions", []), reason)
    promoted_requests = apply_pending_downtime_requests(f"{reason}:downtime_promotion")
    refresh_web_intelligence()
    template = build_daily_evolved_template()
    save_template(template)

    # Always stamp site config with evolution metadata, even if no feedback was archived.
    site_config = load_site_config()
    site_config["last_evolution_at"] = datetime.now(SITE_TIMEZONE).isoformat()
    site_config["last_evolution_reason"] = reason
    save_site_config(site_config)

    archived = archive_and_clear_site_feedback(reason)
    registry_state = ensure_registry_state()
    registry_state["last_daily_evolution_at"] = datetime.now(SITE_TIMEZONE).isoformat()
    registry_state["last_daily_evolution_reason"] = reason
    registry_state["last_archived_submission_count"] = len(archived["submissions"]) if archived else 0
    registry_state["last_downtime_promoted_count"] = len(promoted_requests)
    save_registry_state(registry_state)
    log_action(
        "Daily site evolution completed. "
        f"Reason: {reason}. "
        f"Archived submissions: {len(archived['submissions']) if archived else 0}. "
        f"Downtime promotions: {len(promoted_requests)}"
    )
def parse_registry_timestamp(raw_value):
    """Auto-generated docstring."""
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SITE_TIMEZONE)
    return parsed.astimezone(SITE_TIMEZONE)

def should_run_daily_site_evolution(now_est, last_run_raw):
    """Auto-generated docstring."""
    scheduled_time = now_est.replace(hour=1, minute=0, second=0, microsecond=0)
    last_run = parse_registry_timestamp(last_run_raw)
    if last_run is None:
        return True

    # Keep the strict daily run anchored at 1:00 AM Eastern time.
    if now_est >= scheduled_time and last_run < scheduled_time:
        return True

    # Also run periodic refreshes so the site visibly evolves through the day.
    periodic_interval = timedelta(hours=SITE_EVOLUTION_REFRESH_HOURS)
    return (now_est - last_run) >= periodic_interval

def start_daily_site_evolution_scheduler():
    """Auto-generated docstring."""
    def loop():
        """Auto-generated docstring."""
        while True:
            now_est = datetime.now(SITE_TIMEZONE)
            registry_state = ensure_registry_state()
            last_run = registry_state.get("last_daily_evolution_at", "")
            if should_run_daily_site_evolution(now_est, last_run):
                if now_est.hour == 1 and now_est.minute < 2:
                    reason = "scheduled_1am_est"
                else:
                    reason = f"periodic_refresh_{SITE_EVOLUTION_REFRESH_HOURS}h"
                run_daily_site_evolution(reason)
            time.sleep(30)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread

def build_default_site_html(status_message="", status_level="success"):
    """Auto-generated docstring."""
    state = load_website_state()
    features = get_site_features_and_content()
    intelligence = load_web_intelligence()
    adaptive_requests_html = render_adaptive_request_links(limit=6)
    pending_downtime_html = render_pending_downtime_links(limit=6)
    bg_style = (
        f"background: linear-gradient(135deg, {features['bg_color']} 0%, #cfdef3 100%);"
        if features["background"]
        else "background: linear-gradient(135deg, #f7f7f7 0%, #ebf4f5 100%);"
    )
    feedback_count = len(state.get("suggestions", []))
    error_count = len(state.get("error_reports", []))
    recent_chatbot_requests = get_recent_chatbot_requests(limit=3)
    chatbot_count = len(load_market_process_state().get("chatbot_requests", []))
    feature_cards = []
    if features["tabs"]:
        feature_cards.append("Tabbed navigation requested")
    if features["signup"]:
        feature_cards.append("Free sign-up is enabled")
    if features["saved_items"]:
        feature_cards.append("Saved items are enabled")
    if features["recommendations"]:
        feature_cards.append("Recommendations based on saved items are enabled")
    if features["doc2mp3"]:
        feature_cards.append("Word/PDF to MP3 workflow requested")
    for section in features["custom_sections"]:
        feature_cards.append(f"Custom section: {section}")
    if not feature_cards:
        feature_cards.append("Feedback-powered roadmap is active")

    custom_text_html = "".join(f"<div class='custom-text'>{text}</div>" for text in features["custom_text"])
    feature_items = "".join(f"<li>{item}</li>" for item in feature_cards)
    top_story_blurbs = "".join(
        (
            f"<li><a href=\"{story['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{story['title']}</a>"
            f"<div class='story-blurb'>{story.get('blurb', '')}</div><em>({story['source']})</em></li>"
        )
        for story in intelligence.get("tech_stories", [])[:3]
    ) or "<li>Top story blurbs will appear after the next web intelligence refresh.</li>"
    tech_story_items = "".join(
        f"<li><a href=\"{story['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{story['title']}</a> <em>({story['source']})</em></li>"
        for story in intelligence.get("tech_stories", [])[3:6]
    ) or "<li>Top tech stories will appear after the next web intelligence refresh.</li>"
    idea_items = "".join(
        f"<li><a href=\"{idea['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{idea['title']}</a> <em>({idea['source']})</em></li>"
        for idea in intelligence.get("ideas", [])[:5]
    ) or "<li>Design ideas will appear after the next web intelligence refresh.</li>"
    video = intelligence.get("video_inspiration", {})
    youtube_video_items = "".join(
        f"<li><a href=\"{video['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">{video['title']}</a> by {video['author']}<div class='story-blurb'>{video['reason']}</div></li>"
        for video in intelligence.get("youtube_videos", [])[:4]
    ) or "<li>Tech video picks will appear after the next web intelligence refresh.</li>"
    video_summary = ""
    if video:
        video_summary = (
            f"<p><a href=\"{video.get('source_url')}\" target=\"_blank\" rel=\"noopener noreferrer\">"
            f"{video.get('title')}</a> by {video.get('author')}</p>"
        )
    site_actions = "".join(
        f"<li>{item}</li>"
        for item in [
            "Read the top tech stories with short summaries instead of just links.",
            "Share feedback to shape tomorrow's refresh and new sections.",
            "Report broken parts of the site directly from the page.",
            "Browse design inspiration pulled from current web sources.",
        ]
    )
    highlight_items = "".join(
        f"<li>{item}</li>"
        for item in [
            f"{len(intelligence.get('tech_stories', []))} current tech stories are cached for reading.",
            f"{len(intelligence.get('ideas', []))} web design ideas are ready for the next refresh.",
            f"{feedback_count} private feedback item(s) are queued into the next site evolution.",
            f"{error_count} private error report(s) are waiting in the backend review queue.",
            f"{chatbot_count} chatbot project request(s) are queued for Market Agent execution.",
        ]
    )
    improvement_items = "".join(
        f"<li>{item}</li>"
        for item in [
            "The site refreshes every day at 1:00 AM Eastern Time.",
            "New feedback is saved immediately and folded into future updates.",
            "Quiet days still trigger a fresh layout/theme so the site keeps evolving.",
        ]
    )
    status_html = (
        f"<div class='status {status_level}'>{status_message}</div>" if status_message else ""
    )

    return f"""
    <html>
    <head>
        <title>skynetv1 Evolving Website</title>
        <style>
            body {{{bg_style} font-family: Arial, sans-serif; margin: 0; color: #1f2933;}}
            .shell {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }}
            .hero {{ background: rgba(255,255,255,0.86); border-radius: 18px; padding: 28px; box-shadow: 0 18px 45px rgba(15, 23, 42, 0.10); }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; margin-top: 20px; }}
            .tabs {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
            .tabs a {{ text-decoration: none; background: #eef2ff; color: #1e293b; padding: 10px 14px; border-radius: 999px; font-weight: bold; }}
            .panel {{ background: rgba(255,255,255,0.88); border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08); }}
            h1, h2 {{ margin-top: 0; }}
            label {{ display: block; font-weight: bold; margin-bottom: 8px; }}
            input, textarea {{ width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 10px; box-sizing: border-box; }}
            textarea {{ min-height: 110px; resize: vertical; }}
            button {{ margin-top: 12px; background: #0f766e; color: white; border: 0; border-radius: 999px; padding: 10px 18px; cursor: pointer; }}
            ul {{ padding-left: 18px; margin-bottom: 0; }}
            .status {{ padding: 12px 14px; border-radius: 12px; margin: 16px 0; }}
            .status.success {{ background: #dcfce7; color: #166534; }}
            .status.warning {{ background: #fef3c7; color: #92400e; }}
            .pill {{ display: inline-block; background: #dbeafe; color: #1d4ed8; padding: 6px 10px; border-radius: 999px; margin-right: 8px; margin-bottom: 8px; }}
            .custom-text {{ margin-top: 12px; padding: 12px; background: #f8fafc; border-left: 4px solid #0f766e; border-radius: 10px; }}
            .story-blurb {{ margin: 8px 0; line-height: 1.45; }}
            .save-item-btn {{ margin-left: 10px; background: #0f766e; }}
        </style>
    </head>
    <body>
        <div class="shell">
            <div class="hero">
                <div class="pill">Live feedback intake</div>
                <div class="pill">Error reporting enabled</div>
                <div class="pill">Persistent site state</div>
                <h1>{features['custom_title']}</h1>
                <p>{features['footer']}</p>
                {status_html}
                {custom_text_html}
            </div>
            <nav class="tabs">
                <a href="/requests">Requests</a>
                <a href="/project-chat">Project Chatbot</a>
                <a href="#feedback-form">Feedback</a>
                <a href="#error-form">Errors</a>
                <a href="#news">Top Stories</a>
                <a href="#ideas">Design Ideas</a>
                <a href="#video">Video Inspiration</a>
            </nav>
            <div class="grid">
                <section class="panel" id="feedback-form">
                    <h2>Feedback</h2>
                    <p>{features['form_label']}</p>
                    <form method="post">
                        <input type="hidden" name="entry_type" value="feedback">
                        <label for="feedback_message">Feedback message</label>
                        <textarea id="feedback_message" name="message" required></textarea>
                        <label for="feedback_contact">Email or contact (optional)</label>
                        <input id="feedback_contact" type="text" name="contact" placeholder="name@example.com">
                        <button type="submit">Submit feedback</button>
                    </form>
                </section>
                <section class="panel" id="error-form">
                    <h2>Error Report</h2>
                    <p>Visitors can report bugs, broken links, or other issues directly from the page.</p>
                    <form method="post">
                        <input type="hidden" name="entry_type" value="error">
                        <label for="error_message">What went wrong?</label>
                        <textarea id="error_message" name="message" required></textarea>
                        <label for="error_contact">Email or contact (optional)</label>
                        <input id="error_contact" type="text" name="contact" placeholder="name@example.com">
                        <button type="submit">Report error</button>
                    </form>
                </section>
                <section class="panel">
                    <h2>Requested Features</h2>
                    <ul>{feature_items}</ul>
                </section>
                <section class="panel">
                    <h2>What You Can Do Here</h2>
                    <ul>{site_actions}</ul>
                </section>
                <section class="panel">
                    <h2>Today's Highlights</h2>
                    <ul>{highlight_items}</ul>
                </section>
                <section class="panel">
                    <h2>How The Site Improves</h2>
                    <ul>{improvement_items}</ul>
                </section>
                <section class="panel">
                    <h2>Adaptive Request Pages</h2>
                    <ul>{adaptive_requests_html}</ul>
                </section>
                <section class="panel">
                    <h2>Queued For Downtime</h2>
                    <ul>{pending_downtime_html}</ul>
                </section>
                <section class="panel">
                    <h2>Chatbot Project Queue</h2>
                    <p>Use <a href="/project-chat">Project Chatbot</a> to request a build, get a budget estimate, and send it to Market Agent workflow.</p>
                    <ul>{''.join(f"<li>{item.get('id')} - ${item.get('estimate_usd')} - {item.get('title')}</li>" for item in recent_chatbot_requests) or '<li>No chatbot requests queued yet.</li>'}</ul>
                </section>
                {build_personalization_panel()}
                <section class="panel" id="ideas">
                    <h2>Web Design Ideas</h2>
                    <ul>{idea_items}</ul>
                </section>
                <section class="panel" id="news">
                    <h2>Top 3 Story Briefs</h2>
                    <ul>{top_story_blurbs}</ul>
                </section>
                <section class="panel">
                    <h2>Top Tech Stories</h2>
                    <ul>{tech_story_items}</ul>
                </section>
                <section class="panel" id="video">
                    <h2>Video Inspiration</h2>
                    {video_summary}
                </section>
                <section class="panel">
                    <h2>Tech YouTube Picks</h2>
                    <ul>{youtube_video_items}</ul>
                </section>
            </div>
        </div>
        {build_personalization_assets()}
    </body>
    </html>
    """

def create_app():
    """Auto-generated docstring."""
    app = Flask(__name__)

    @app.before_request
    def apply_rate_limit():
        # Keep health checks exempt so local liveness probes always work.
        if request.path == "/health":
            return None

        client_ip = get_client_ip(request)
        now_ts = time.time()
        if is_rate_limited(client_ip, now_ts):
            record_rate_limited_request(request.path, client_ip)
            return {
                "status": "rate_limited",
                "message": "Too many requests. Please retry shortly.",
                "retry_after_seconds": RATE_LIMIT_WINDOW_SECONDS,
            }, 429
        return None

    @app.after_request
    def track_request(response):
        """Auto-generated docstring."""
        record_traffic_event(request.path, response.status_code, get_client_ip(request))
        return response

    def ensure_admin_auth():
        """Auto-generated docstring."""
        if not ADMIN_API_KEY:
            return None
        supplied_key = (request.headers.get("X-Admin-Key") or request.args.get("admin_key") or "").strip()
        if supplied_key == ADMIN_API_KEY:
            return None
        return {"status": "forbidden", "message": "Missing or invalid admin key."}, 403

    @app.route("/", methods=["GET", "POST"])
    def index():
        """Auto-generated docstring."""
        if request.method == "POST":
            entry_type = request.form.get("entry_type", "").strip().lower()
            message = request.form.get("message", "").strip()
            contact = request.form.get("contact", "").strip()
            redirect_endpoint = "feedback_page" if entry_type == "feedback" else "errors_page"

            if entry_type not in {"feedback", "error"} or not message:
                return redirect(url_for(redirect_endpoint, status="invalid"))

            added, entry = add_submission(entry_type, message, contact)
            if not added:
                return redirect(url_for(redirect_endpoint, status="duplicate"))

            if entry_type == "feedback":
                send_email("New Website Feedback", entry["message"], SUGGESTION_EMAIL)
                send_email("Feedback Added to Website", json.dumps(entry, indent=2), ADMIN_EMAIL)
                return redirect(url_for("feedback_page", status="feedback_added"))

            send_email("Website Error Report", json.dumps(entry, indent=2), ADMIN_EMAIL)
            return redirect(url_for("errors_page", status="error_added"))

        status = request.args.get("status", "")
        if status == "feedback_added":
            html = build_default_site_html(
                "Thanks. Your feedback was saved and added to the site history.",
                "success",
            )
        elif status == "error_added":
            html = build_default_site_html(
                "Thanks. Your error report was saved for follow-up.",
                "success",
            )
        elif status == "duplicate":
            html = build_default_site_html(
                "That submission already exists, so it was not added twice.",
                "warning",
            )
        elif status == "invalid":
            html = build_default_site_html(
                "Please choose a valid form and include a message.",
                "warning",
            )
        else:
            html = get_current_template() or build_default_site_html()
        html = inject_homepage_chatbot_bubble(html)
        return render_template_string(html)

    @app.route("/changes", methods=["GET"])
    def changes_page():
        """Auto-generated docstring."""
        return render_template_string(build_changes_page())

    @app.route("/requests", methods=["GET"])
    def requests_page():
        """Auto-generated docstring."""
        return render_template_string(build_requests_page())

    @app.route("/requests/<slug>", methods=["GET"])
    def request_detail_page(slug):
        """Auto-generated docstring."""
        page = next((item for item in get_adaptive_pages() if item.get("slug") == slug), None)
        if not page:
            return render_template_string(build_page_shell("Request Not Found", "That generated request page does not exist.", """
            <section class="card">
                <h2>Missing Page</h2>
                <p>The requested adaptive page could not be found.</p>
            </section>
            """)), 404
        return render_template_string(build_request_detail_page(page))

    @app.route("/top-stories", methods=["GET"])
    def top_stories_page():
        """Auto-generated docstring."""
        return render_template_string(build_top_stories_page())

    @app.route("/design-ideas", methods=["GET"])
    def design_ideas_page():
        """Auto-generated docstring."""
        return render_template_string(build_design_ideas_page())

    @app.route("/tech-videos", methods=["GET"])
    def tech_videos_page():
        """Auto-generated docstring."""
        return render_template_string(build_tech_videos_page())

    @app.route("/video-upgrades", methods=["GET"])
    def video_upgrades_page():
        """Auto-generated docstring."""
        return render_template_string(build_video_upgrades_page())

    @app.route("/feedback", methods=["GET"])
    def feedback_page():
        """Auto-generated docstring."""
        status = request.args.get("status", "")
        message = ""
        if status == "feedback_added":
            message = "Your feedback was received and is now queued in the backend for implementation."
        elif status == "duplicate":
            message = "That feedback is already queued in the backend."
        elif status == "invalid":
            message = "Please include a feedback message."
        return render_template_string(build_feedback_page(message))

    @app.route("/errors", methods=["GET"])
    def errors_page():
        """Auto-generated docstring."""
        status = request.args.get("status", "")
        message = ""
        if status == "error_added":
            message = "Your error report was received and is now queued in the backend for review."
        elif status == "duplicate":
            message = "That error report is already queued in the backend."
        elif status == "invalid":
            message = "Please include an error message."
        return render_template_string(build_errors_page(message))

    @app.route("/project-chat", methods=["GET", "POST"])
    def project_chat_page():
        """Auto-generated docstring."""
        if request.method == "POST":
            message = request.form.get("message", "").strip()
            contact = request.form.get("contact", "").strip()
            upfront_payment_ack = request.form.get("upfront_payment_ack", "").strip().lower() in {"1", "true", "yes", "on"}
            if not message or not contact:
                return redirect(url_for("project_chat_page", status="invalid"))
            if not is_valid_contact_email(contact):
                return redirect(url_for("project_chat_page", status="invalid_email"))
            if not upfront_payment_ack:
                return redirect(url_for("project_chat_page", status="deposit_required"))

            entry = queue_chatbot_project_request(message, contact, upfront_payment_confirmed=False)
            if not entry:
                return redirect(url_for("project_chat_page", status="invalid"))
            promo_code = ((entry.get("promo") or {}).get("code") or "").strip()
            send_email(
                "New Project Chatbot Request",
                json.dumps(entry, indent=2),
                ADMIN_EMAIL,
            )
            send_chatbot_promo_email(entry)
            return redirect(
                url_for(
                    "project_payment_page",
                    request_id=entry.get("id", ""),
                    status="promo_ready",
                    promo_code=promo_code,
                )
            )

        status = request.args.get("status", "")
        request_id = request.args.get("request_id", "")
        message = ""
        if status == "queued":
            message = (
                "Project request queued successfully. "
                f"Request ID: {request_id}. Market Agent will triage this request next."
            )
        elif status == "started":
            message = (
                "Project request accepted. "
                f"Request ID: {request_id}. Complete deposit payment to start build delegation."
            )
        elif status == "deposit_required":
            message = "Upfront payment approval is required before the request can enter the build queue."
        elif status == "invalid":
            message = "Please describe the project, provide a delivery email, and submit the form again."
        elif status == "invalid_email":
            message = "Please enter a valid delivery email address before submitting your request."
        elif status == "approved":
            message = f"Request approved: {request_id}."
        elif status == "ranked":
            message = "Phase 2.2 scoring and ranked submission queue updated."
        elif status == "verified":
            message = f"Request verified as won with funded escrow: {request_id}."
        elif status == "delegated":
            message = f"Build delegation queued for request {request_id}."
        elif status == "blocked":
            message = request.args.get("reason", "Build trigger blocked by verification guard.")
        return render_template_string(build_project_chat_page(message))
    @app.route("/project-chat/payment", methods=["GET"])
    def project_payment_page():
        """Auto-generated docstring."""
        request_id = request.args.get("request_id", "").strip()
        status = request.args.get("status", "").strip().lower()
        stage = request.args.get("stage", "").strip().lower()
        promo_code = request.args.get("promo_code", "").strip()
        message = ""
        if status == "deposit_required":
            message = "Deposit payment is required before build can begin."
        elif status == "promo_ready":
            message = f"Your 100% off promo code is {promo_code or 'available below'}. Apply it to waive payment."
        elif status == "promo_applied":
            message = "Promo code applied. Payments are now fully waived."
        elif status == "promo_invalid":
            message = request.args.get("reason", "Promo code is invalid.")
        elif status == "success":
            message = f"Checkout completed for {stage or 'payment'}. Waiting for webhook confirmation."
        elif status == "cancelled":
            message = "Checkout was cancelled. You can retry payment below."
        elif status == "checkout_error":
            message = request.args.get("reason", "Unable to create checkout session.")
        return render_template_string(build_project_payment_page(request_id, message))

    @app.route("/project-chat/payment/promo", methods=["POST"])
    def project_payment_apply_promo():
        """Auto-generated docstring."""
        request_id = request.form.get("request_id", "").strip()
        promo_code = request.form.get("promo_code", "").strip()
        if not request_id:
            return redirect(url_for("project_chat_page", status="invalid"))

        applied, reason, canonical_code = apply_chatbot_promo_code(request_id, promo_code)
        if not applied:
            return redirect(
                url_for(
                    "project_payment_page",
                    request_id=request_id,
                    status="promo_invalid",
                    reason=reason,
                    promo_code=canonical_code,
                )
            )

        delegated, _ = trigger_chatbot_build_now(request_id)
        if delegated:
            send_email(
                "Market Build Delegation Queued",
                json.dumps(delegated, indent=2),
                ADMIN_EMAIL,
            )
        return redirect(url_for("project_payment_page", request_id=request_id, status="promo_applied", promo_code=canonical_code))

    @app.route("/project-chat/payment/checkout", methods=["POST"])
    def project_payment_checkout():
        """Auto-generated docstring."""
        request_id = request.form.get("request_id", "").strip()
        stage = request.form.get("stage", "deposit").strip().lower()
        if not request_id:
            return redirect(url_for("project_chat_page", status="invalid"))
        checkout_url, error = create_stripe_checkout_session_for_request(request_id, stage=stage)
        if error:
            return redirect(url_for("project_payment_page", request_id=request_id, status="checkout_error", reason=error, stage=stage))
        if not checkout_url:
            return redirect(url_for("project_payment_page", request_id=request_id, status="checkout_error", reason="Checkout URL missing", stage=stage))
        return redirect(checkout_url)

    @app.route("/project-chat/payment/webhook", methods=["POST"])
    def project_payment_webhook():
        """Auto-generated docstring."""
        if stripe is None:
            return jsonify({"ok": False, "error": "Stripe SDK unavailable"}), 503
        if not STRIPE_WEBHOOK_SECRET:
            return jsonify({"ok": False, "error": "STRIPE_WEBHOOK_SECRET is not configured"}), 503

        payload = request.get_data()
        signature = request.headers.get("Stripe-Signature", "")
        try:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=STRIPE_WEBHOOK_SECRET)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Invalid webhook signature: {exc}"}), 400

        ok, message = process_stripe_checkout_event(event)
        status_code = 200 if ok else 400
        return jsonify({"ok": ok, "message": message}), status_code

    @app.route("/project-chat/rank", methods=["POST"])
    def project_chat_rank():
        """Auto-generated docstring."""
        rank_chatbot_requests()
        return redirect(url_for("project_chat_page", status="ranked"))

    @app.route("/project-chat/action", methods=["POST"])
    def project_chat_action():
        """Auto-generated docstring."""
        request_id = request.form.get("request_id", "").strip()
        action = request.form.get("action", "").strip().lower()
        if not request_id:
            return redirect(url_for("project_chat_page", status="invalid"))

        if action == "approve":
            approve_chatbot_request(request_id)
            return redirect(url_for("project_chat_page", status="approved", request_id=request_id))

        if action == "verify":
            proof = f"Verified manually in admin UI at {datetime.now(SITE_TIMEZONE).isoformat()}"
            verify_chatbot_request_award(request_id, proof=proof)
            return redirect(url_for("project_chat_page", status="verified", request_id=request_id))

        if action == "build_now":
            delegated, error = trigger_chatbot_build_now(request_id)
            if error:
                return redirect(url_for("project_chat_page", status="blocked", reason=error, request_id=request_id))

            # Guarded delegation event record for operator/auditing.
            send_email(
                "Market Build Delegation Queued",
                json.dumps(delegated, indent=2),
                ADMIN_EMAIL,
            )
            return redirect(url_for("project_chat_page", status="delegated", request_id=request_id))
        return redirect(url_for("project_chat_page", status="invalid"))

    @app.route("/health", methods=["GET"])
    def health():
        """Auto-generated docstring."""
        state = load_website_state()
        registry_state = ensure_registry_state()
        training_state = read_json(TRAINING_STATUS) or {}
        trainer_info = training_state.get("processes", {}).get("nlp_trainer", {})
        trainer_pid = trainer_info.get("pid")
        return {
            "status": "ok",
            "feedback_count": len(state.get("suggestions", [])),
            "error_count": len(state.get("error_reports", [])),
            "module_count": len(registry_state.get("modules", {})),
            "rewrite_backlog_count": len(load_rewrite_backlog()),
            "learned_rule_count": len(load_rewrite_rules()),
            "trainer_running_flag": trainer_info.get("running", False),
            "trainer_pid": trainer_pid,
            "trainer_pid_alive": is_pid_running(trainer_pid),
        }

    @app.route("/registry", methods=["GET"])
    def registry():
        """Auto-generated docstring."""
        return ensure_registry_state()

    @app.route("/rewrite-status", methods=["GET"])
    def rewrite_status():
        """Auto-generated docstring."""
        return {
            "backlog": load_rewrite_backlog(),
            "rules": load_rewrite_rules(),
            "history": load_rewrite_history()[-20:],
        }

    @app.route("/web-intel", methods=["GET"])
    def web_intel():
        """Auto-generated docstring."""
        return load_web_intelligence()

    @app.route("/backend/traffic", methods=["GET"])
    def backend_traffic():
        """Auto-generated docstring."""
        auth_failure = ensure_admin_auth()
        if auth_failure:
            return auth_failure
        return get_traffic_snapshot()

    @app.route("/backend/queue", methods=["GET"])
    def backend_queue():
        """Auto-generated docstring."""
        auth_failure = ensure_admin_auth()
        if auth_failure:
            return auth_failure
        state = load_website_state()
        site_config = load_site_config()
        return {
            "feedback_queue": state.get("suggestions", []),
            "error_queue": state.get("error_reports", []),
            "submissions": state.get("submissions", []),
            "pending_downtime_requests": site_config.get("pending_downtime_requests", []),
            "last_evolution_at": site_config.get("last_evolution_at"),
            "last_evolution_reason": site_config.get("last_evolution_reason"),
        }

    # ── YouTube content pages ────────────────────────────────────────────────
    _FRONTEND_PUBLIC = Path("/home/pi/Desktop/test/frontend/public")

    @app.route("/blog", methods=["GET"])
    def blog_page():
        """Auto-generated docstring."""
        return send_from_directory(str(_FRONTEND_PUBLIC), "blog.html")

    @app.route("/blog_posts.json", methods=["GET"])
    def blog_posts_json():
        """Auto-generated docstring."""
        return send_from_directory(str(_FRONTEND_PUBLIC), "blog_posts.json")

    @app.route("/videos", methods=["GET"])
    def videos_page():
        """Auto-generated docstring."""
        return send_from_directory(str(_FRONTEND_PUBLIC), "videos.html")

    @app.route("/video_links.json", methods=["GET"])
    def video_links_json():
        """Auto-generated docstring."""
        return send_from_directory(str(_FRONTEND_PUBLIC), "video_links.json")

    return app

def start_ngrok():
    """Auto-generated docstring."""
    if ngrok is None:
        log_action("pyngrok is not installed; skipping ngrok startup.")
        return None
    if NGROK_AUTH_TOKEN:
        ngrok.set_auth_token(NGROK_AUTH_TOKEN)

    def find_existing_cli_tunnel():
        """Auto-generated docstring."""
        try:
            response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
            response.raise_for_status()
            payload = response.json()
            for tunnel in payload.get("tunnels", []):
                tunnel_addr = str(tunnel.get("config", {}).get("addr", ""))
                public_url = tunnel.get("public_url")
                if any(
                    needle in tunnel_addr
                    for needle in [f":{SITE_PORT}", f"localhost:{SITE_PORT}", f"127.0.0.1:{SITE_PORT}"]
                ):
                    return public_url
                if NGROK_RESERVED_URL and public_url == NGROK_RESERVED_URL:
                    return public_url
        except Exception:
            return None
        return None

    def find_existing_site_tunnel():
        """Auto-generated docstring."""
        if ngrok is None:
            return None
        try:
            for tunnel in ngrok.get_tunnels():
                tunnel_addr = str((tunnel.config or {}).get("addr", ""))
                if any(
                    needle in tunnel_addr
                    for needle in [f":{SITE_PORT}", f"localhost:{SITE_PORT}", f"127.0.0.1:{SITE_PORT}"]
                ):
                    return tunnel.public_url
                if NGROK_RESERVED_URL and tunnel.public_url == NGROK_RESERVED_URL:
                    return tunnel.public_url
        except Exception as exc:
            log_action(f"Unable to inspect existing ngrok tunnels: {exc}")
        return None

    existing_cli_tunnel = find_existing_cli_tunnel()
    if existing_cli_tunnel:
        log_action(f"Reusing existing ngrok CLI tunnel for the website: {existing_cli_tunnel}")
        return existing_cli_tunnel

    def disconnect_site_tunnels():
        """Auto-generated docstring."""
        if ngrok is None:
            return
        try:
            for tunnel in ngrok.get_tunnels():
                tunnel_addr = str((tunnel.config or {}).get("addr", ""))
                if any(
                    needle in tunnel_addr
                    for needle in [f":{SITE_PORT}", f"localhost:{SITE_PORT}", f"127.0.0.1:{SITE_PORT}"]
                ):
                    if isinstance(tunnel.public_url, str):
                        ngrok.disconnect(tunnel.public_url)
        except Exception as exc:
            log_action(f"Unable to inspect existing ngrok tunnels: {exc}")

    existing_tunnel = find_existing_site_tunnel()
    if existing_tunnel:
        log_action(f"Reusing existing ngrok tunnel for the website: {existing_tunnel}")
        return existing_tunnel

    disconnect_site_tunnels()

    try:
        tunnel = ngrok.connect(str(SITE_PORT), bind_tls=True)
        return tunnel.public_url
    except Exception as exc:
        if "ERR_NGROK_334" in str(exc) or "already online" in str(exc):
            log_action(
                "ngrok reserved endpoint is already online; retrying with a fresh ephemeral tunnel for the website."
            )
            disconnect_site_tunnels()
            tunnel = ngrok.connect(str(SITE_PORT), bind_tls=True, domain=None)
            return tunnel.public_url
        raise

def feedback_loop():
    """Auto-generated docstring."""
    log_action("[feedback_loop] Website feedback intake is active.")

def network_scan():
    """Auto-generated docstring."""
    log_action("[network_scan] Placeholder: no scan implemented yet.")

def check_training_goal():
    """Auto-generated docstring."""
    status = read_json(TRAINING_STATUS)
    if not status:
        return False
    dataset_progress = status.get("dataset_progress", {})
    training_progress = status.get("training_progress", {})
    if dataset_progress.get("total_size_gb", 0) < DATASET_TARGET_GB:
        return False
    if training_progress.get("current_epoch", 0) < EPOCH_TARGET and training_progress.get("loss", 1) > LOSS_TARGET:
        return False
    return True

def monitor_resources():
    """Auto-generated docstring."""
    cpu = psutil.cpu_percent()
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    log_action(f"Resource usage: CPU={cpu}%, MEM={memory}%, DISK={disk}%")

def detect_failures():
    """Auto-generated docstring."""
    status = read_json(TRAINING_STATUS)
    if not status:
        return
    trainer = status.get("processes", {}).get("nlp_trainer", {})
    trainer_pid = trainer.get("pid")
    trainer_flag = trainer.get("running", False)
    trainer_alive = is_pid_running(trainer_pid)
    if trainer_flag and not trainer_alive:
        log_action("nlp_trainer status mismatch detected. PID is not alive even though running=true.")
        update_training_process_status(
            "nlp_trainer",
            False,
            note="Auto-corrected because PID from status file was not alive.",
        )
    if not trainer_flag or not trainer_alive:
        log_action("nlp_trainer not running. Attempting restart.")
        queue_code_rewrite(
            reason="nlp_trainer not running according to training_status.json",
            source="training_monitor",
            severity="high",
        )
        update_training_process_status(
            "nlp_trainer",
            False,
            note="Restart requested by detect_failures.",
        )
        maybe_restart_training("trainer not running or stale PID")

def ensure_flask_serving(app):
    """Auto-generated docstring."""
    global _last_flask_restart_attempt

    try:
        response = requests.get(f"http://127.0.0.1:{SITE_PORT}/health", timeout=4)
        if response.ok:
            return True
    except Exception:
        pass

    # If another process already owns the port, avoid restart storms.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", SITE_PORT)) == 0:
            log_action("Website health probe failed but port is already bound; skipping Flask restart attempt.")
            return True

    now = time.time()
    with _flask_restart_lock:
        if now - _last_flask_restart_attempt < _flask_restart_cooldown_sec:
            log_action("Website health check failed, but restart is in cooldown; skipping duplicate restart.")
            return False
        _last_flask_restart_attempt = now

    log_action("Website health check failed. Starting a fresh Flask server thread.")
    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=SITE_PORT, debug=False, use_reloader=False),
        daemon=True,
    )
    flask_thread.start()
    time.sleep(2)
    return flask_thread.is_alive()

def get_client_ip(flask_request):
    """Auto-generated docstring."""
    forwarded_for = (flask_request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return (flask_request.remote_addr or "unknown").strip()

def is_rate_limited(ip_address, now_ts):
    """Auto-generated docstring."""
    if not RATE_LIMIT_ENABLED:
        return False

    cutoff = now_ts - RATE_LIMIT_WINDOW_SECONDS
    with _rate_limit_lock:
        bucket = _rate_limit_buckets[ip_address]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            return True
        bucket.append(now_ts)
    return False

def record_traffic_event(path, status_code, ip_address):
    """Auto-generated docstring."""
    with _traffic_lock:
        _traffic_totals["requests_total"] += 1
        _traffic_routes[path] += 1
        _traffic_status_codes[str(status_code)] += 1
        _traffic_ips[ip_address] += 1

def record_rate_limited_request(path, ip_address):
    """Auto-generated docstring."""
    with _traffic_lock:
        _traffic_totals["blocked_rate_limited"] += 1
        _traffic_routes[path] += 1
        _traffic_status_codes["429"] += 1
        _traffic_ips[ip_address] += 1

def get_traffic_snapshot(top_n=15):
    """Auto-generated docstring."""
    with _traffic_lock:
        return {
            "started_at": _traffic_started_at,
            "rate_limit": {
                "enabled": RATE_LIMIT_ENABLED,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                "max_requests": RATE_LIMIT_MAX_REQUESTS,
            },
            "totals": dict(_traffic_totals),
            "top_routes": sorted(_traffic_routes.items(), key=lambda item: item[1], reverse=True)[:top_n],
            "status_codes": dict(_traffic_status_codes),
            "top_ips": sorted(_traffic_ips.items(), key=lambda item: item[1], reverse=True)[:top_n],
        }

def propose_and_apply_improvements():
    """Auto-generated docstring."""
    status = read_json(TRAINING_STATUS)
    if not status:
        return
    dataset_progress = status.get("dataset_progress", {})
    if dataset_progress.get("download_rate_mbps", 10) < 1:
        log_action("Download rate low. Attempting to restart dataset puller.")
        queue_code_rewrite(
            reason="dataset download rate dropped below 1 Mbps",
            source="training_monitor",
            severity="medium",
        )
        maybe_restart_training("dataset download rate below threshold")

def run_error_learning_cycle():
    """Auto-generated docstring."""
    error_log_path = Path("/home/pi/Desktop/test/implementation_outputs/error_log.json")
    if not error_log_path.exists():
        return
    try:
        contents = error_log_path.read_text(encoding="utf-8")
    except Exception as exc:
        log_action(f"Failed to read error log for learning cycle: {exc}")
        return
    if any(marker in contents for marker in ["Traceback", "Exception", "Error", "ModuleNotFoundError"]):
        queue_code_rewrite(
            reason="Detected error markers in implementation_outputs/error_log.json",
            source="error_learning_cycle",
            severity="medium",
        )

def main():
    """Auto-generated docstring."""
    log_action("skynetv1 autonomous agent started.")
    ensure_registry_state()
    save_rewrite_rules(load_rewrite_rules())
    backfill_adaptive_pages_from_history()
    refresh_web_intelligence()
    manager = build_self_healing_manager()
    start_self_healing_manager(manager)
    start_daily_site_evolution_scheduler()

    app = create_app()
    ensure_flask_serving(app)

    # Phase 1 & 2: Start delegation poller for auto-running delegated chatbot jobs
    try:
        delegation_poller = start_delegation_poller()
        if delegation_poller:
            log_action("Delegation poller started successfully (Phase 1 & 2)")
    except Exception as exc:
        log_action(f"Failed to start delegation poller: {exc}")

    if ENABLE_NGROK:
        try:
            public_url = start_ngrok()
            if public_url:
                log_action(f"Website public URL: {public_url}")
                try:
                    DASHBOARD_PUBLIC_URL_FILE.write_text(
                        "\n".join(
                            [
                                public_url,
                                f"Updated: {datetime.now(SITE_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S %Z')}",
                                f"Target: bidding dashboard (port {SITE_PORT})",
                            ]
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                except Exception as exc:
                    log_action(f"Unable to write dashboard public URL file: {exc}")
        except Exception as exc:
            log_action(f"ngrok startup failed; continuing with local website only: {exc}")
    else:
        log_action("ngrok disabled via ENABLE_NGROK=0; continuing with local website only.")

    scan_interval = 10
    feedback_interval = 5
    loop_count = 0

    while True:
        if check_training_goal():
            log_action("GOAL MET: Training and dataset targets achieved.")
            with STATUS_TXT.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[skynetv1 agent] GOAL MET at {datetime.now()}\n")
            break
        monitor_resources()
        ensure_flask_serving(app)
        detect_failures()
        propose_and_apply_improvements()
        run_error_learning_cycle()
        run_staged_self_rewrite_executor()
        if loop_count % scan_interval == 0:
            network_scan()
        if loop_count % feedback_interval == 0:
            feedback_loop()
        loop_count += 1
        time.sleep(LOOP_INTERVAL)

if __name__ == "__main__":
    # ...existing code...
    main()
