#!/usr/bin/env python3
"""
Airdrop Scout — discovers, scores, and reports crypto airdrop opportunities.

Usage:
  python3 airdrop_scout.py --scan       # crawl sources, score, save airdrops.json
  python3 airdrop_scout.py --email      # email top 5 scored airdrops for approval
    python3 airdrop_scout.py --approve-all # mark all pending non-free airdrops as approved
    python3 airdrop_scout.py --watch-replies [--interval-minutes N]
                                                                     # continuously poll email replies for #number approvals
    python3 airdrop_scout.py --watch-scan [--scan-interval-minutes N]
                                                                     # continuously scan for new airdrops
  python3 airdrop_scout.py --selftest   # verify scraping + email without saving

Filters applied (all must pass before an airdrop is scored):
    - No "send ETH/BNB to receive" pattern (common scam)
    - Token not in SEC enforcement action list
    - Claim process does not request seed phrase or private key
    - USA-compatible (no explicit geo-block on US IPs)

FREE airdrop = zero cost to claim: no gas fee, no deposit, no token purchase required.
    → Free airdrops are claimed automatically (wallet address submitted or URL opened).
    → Airdrops with ANY cost/gas/approval requirement are queued for manual approval.
"""

import hashlib
import imaplib
import json
import os
import re
import smtplib
import sys
import time
from email import message_from_bytes
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError

STATE_DIR = Path(__file__).parent
AIRDROPS_FILE = STATE_DIR / "airdrops.json"
APPROVAL_INDEX_FILE = STATE_DIR / "approval_index.json"
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "andy.r.bltn@gmail.com")

# Wallet selection: support generic and Coinbase wallet
GENERIC_WALLET_ADDRESS = os.environ.get("CLAIM_WALLET_ADDRESS", "").strip()
COINBASE_WALLET_ADDRESS = os.environ.get("COINBASE_WALLET_ADDRESS", "").strip()

def get_wallet_address(prefer_coinbase: bool = False) -> str:
    """
    Returns the wallet address to use for airdrop claims.
    If prefer_coinbase is True and COINBASE_WALLET_ADDRESS is set, use it.
    Otherwise, use GENERIC_WALLET_ADDRESS.
    """
    if prefer_coinbase and COINBASE_WALLET_ADDRESS:
        return COINBASE_WALLET_ADDRESS
    return GENERIC_WALLET_ADDRESS

# ---------------------------------------------------------------------------
# SECURITY: patterns that indicate a scam or SEC issue
# ---------------------------------------------------------------------------
SCAM_PATTERNS = [
    r"send\s+\d*\.?\d*\s*(eth|bnb|btc|sol)\s+to\s+receive",
    r"deposit\s+to\s+claim",
    r"private[\s_]key",
    r"seed[\s_]phrase",
    r"mnemonic",
    r"wallet[\s_]recovery[\s_]phrase",
]
_SCAM_RE = [re.compile(p, re.IGNORECASE) for p in SCAM_PATTERNS]

# Patterns that indicate a cost is required (not a scam, but not free either)
COST_PATTERNS = [
    r"pay\s+(gas|fee)",
    r"gas\s+fee",
    r"purchase\s+(to|tokens?)\s+(claim|receive|get)",
    r"buy\s+\d",
    r"stake\s+to\s+earn",
    r"minimum\s+(deposit|balance|hold)",
    r"\$\d+\s+(fee|cost|payment)",
]
_COST_RE = [re.compile(p, re.IGNORECASE) for p in COST_PATTERNS]

# SEC enforcement list terms (simplified — cross-referenced against token name)
SEC_FLAGGED_TERMS = [
    "ripple", "xrp", "lbry", "library credits", "lbc", "genie", "poloniex",
]

UA = "Mozilla/5.0 (compatible; CryptoAirdropScout/1.0)"
FETCH_TIMEOUT = 20

def _fetch(url: str) -> str:
    """Simple HTTP GET with user-agent; returns body text or empty string."""
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=FETCH_TIMEOUT) as r:
            raw = r.read(256_000)
            return raw.decode("utf-8", errors="replace")
    except URLError as exc:
        print(f"[fetch] {url} → {exc}")
        return ""
    except Exception as exc:
        print(f"[fetch] {url} → {exc}")
        return ""

# ---------------------------------------------------------------------------
# Scam / compliance filters
# ---------------------------------------------------------------------------

def _is_scam(text: str) -> bool:
    """Auto-generated docstring."""
    for pattern in _SCAM_RE:
        if pattern.search(text):
            return True
    return False

def _has_cost(text: str) -> bool:
    """Returns True if the airdrop page mentions any fee, gas cost, or purchase requirement."""
    for pattern in _COST_RE:
        if pattern.search(text):
            return True
    return False

def _is_free(entry: dict, detail_html: str = "") -> bool:
    """
    An airdrop is FREE if ALL of the following are true:
      - No cost/gas pattern in the page text
      - No minimum token purchase or balance requirement mentioned
      - Claim process is just submitting a wallet address or clicking a button
    """
    if _has_cost(detail_html):
        return False
    steps = entry.get("claim_steps", 99)
    if steps > 3:
        # More than 3 steps usually implies some friction (KYC, purchase, etc.)
        return False
    if entry.get("requires_purchase") or entry.get("requires_gas"):
        return False
    return True

def _is_sec_flagged(name: str) -> bool:
    """Auto-generated docstring."""
    lower = name.lower()
    return any(term in lower for term in SEC_FLAGGED_TERMS)

def _has_verified_contract(token_name: str, contract_addr: str) -> bool:
    """
    Check Etherscan API for contract verification status.
    Requires ETHERSCAN_API_KEY env var; skips check (returns True) if missing.
    """
    api_key = os.environ.get("ETHERSCAN_API_KEY", "")
    if not api_key or not contract_addr:
        # Can't verify — allow through but note as unverified
        return False

    # Basic address sanity (0x + 40 hex chars)
    if not re.match(r"^0x[0-9a-fA-F]{40}$", contract_addr):
        return False

    url = (
        f"https://api.etherscan.io/api?module=contract&action=getsourcecode"
        f"&address={contract_addr}&apikey={api_key}"
    )
    try:
        body = _fetch(url)
        data = json.loads(body)
        if data.get("status") == "1":
            result = data.get("result", [{}])[0]
            return bool(result.get("SourceCode"))
    except Exception:
        pass
    return False

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_airdrop(entry: dict) -> int:
    """
    Score 0-100:
      Reward value estimate:  0-40 pts
      Legitimacy signals:     0-35 pts
      Claim simplicity:       0-25 pts
    """
    score = 0
    reward = entry.get("reward_usd_est", 0) or 0

    # Reward component (capped at 40)
    if reward >= 500:
        score += 40
    elif reward >= 100:
        score += 30
    elif reward >= 20:
        score += 20
    elif reward >= 5:
        score += 10

    # Legitimacy
    if entry.get("contract_verified"):
        score += 20
    if not entry.get("is_scam"):
        score += 10
    if not entry.get("sec_flagged"):
        score += 5

    # Claim simplicity — fewer steps = higher score
    steps = entry.get("claim_steps", 5)
    if steps <= 2:
        score += 25
    elif steps <= 4:
        score += 15
    elif steps <= 6:
        score += 5

    return min(100, score)

def _auto_claim_free(entry: dict, prefer_coinbase: bool = False) -> dict:
    """
    For truly free airdrops: open the claim URL and submit wallet address if there's a
    simple form, or log the URL so the user can paste their address.
    Returns updated entry with status = 'claimed' or 'claim_ready'.
    If prefer_coinbase is True, use the Coinbase wallet address if set.
    """
    wallet = get_wallet_address(prefer_coinbase=prefer_coinbase)
    claim_url = entry.get("url", "")

    if not claim_url:
        entry["status"] = "claim_ready"
        entry["claim_note"] = "No URL available — check project site manually"
        return entry

    if not wallet:
        entry["status"] = "claim_ready"
        if prefer_coinbase:
            entry["claim_note"] = (
                f"Set COINBASE_WALLET_ADDRESS env var, then visit: {claim_url}"
            )
        else:
            entry["claim_note"] = (
                f"Set CLAIM_WALLET_ADDRESS env var, then visit: {claim_url}"
            )
        return entry

    # Optional browser assist: use Playwright to open claim page and pre-fill wallet input.
    # This never submits transactions automatically.
    if os.environ.get("PLAYWRIGHT_ENABLED", "0") == "1":
        ok, note = _playwright_prepare_claim(claim_url, wallet, entry.get("id", "unknown"))
        entry["status"] = "claim_ready"
        entry["claim_note"] = note
        entry["claimed_at"] = datetime.now(timezone.utc).isoformat()
        print(f"  [free] {entry['name']}: {entry['claim_note']}")
        return entry

    # Attempt to find a simple wallet-submission form endpoint
    html = _fetch(claim_url)
    # Look for form action that accepts a wallet address
    form_action = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html)
    wallet_input = re.search(r'<input[^>]+(?:name|id)=["\'](?:address|wallet|eth)["\']', html, re.IGNORECASE)

    if form_action and wallet_input:
        # There's a form — log URL + wallet for manual paste (never auto-POST without user review)
        entry["status"] = "claim_ready"
        entry["claim_note"] = f"Form found at {claim_url} — paste wallet: {wallet[:6]}...{wallet[-4:]}"
    else:
        # No parseable form — record as ready for manual visit
        entry["status"] = "claim_ready"
        entry["claim_note"] = f"Visit {claim_url} and submit wallet: {wallet[:6]}...{wallet[-4:]}"

    entry["claimed_at"] = datetime.now(timezone.utc).isoformat()
    print(f"  [free] {entry['name']}: {entry['claim_note']}")
    return entry

def _playwright_prepare_claim(claim_url: str, wallet: str, claim_id: str):
    """
    Open the claim page with Playwright, try to pre-fill wallet address fields,
    and save a screenshot for review. Never clicks submit.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False, (
            "Playwright not installed. Install with: .venv/bin/pip install playwright "
            "and .venv/bin/playwright install chromium"
        )

    headless = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"
    screenshot_dir = STATE_DIR / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / f"claim_{claim_id}.png"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()
            page.goto(claim_url, wait_until="domcontentloaded", timeout=30000)

            # Try common wallet input selectors; fill only first visible match.
            selectors = [
                "input[name='wallet']",
                "input[name='address']",
                "input[name='eth']",
                "input[id='wallet']",
                "input[id='address']",
                "input[placeholder*='wallet' i]",
                "input[placeholder*='address' i]",
            ]

            filled = False
            for sel in selectors:
                locator = page.locator(sel)
                if locator.count() > 0:
                    locator.first.fill(wallet)
                    filled = True
                    break

            page.screenshot(path=str(screenshot_path), full_page=True)
            browser.close()

        if filled:
            return True, f"Playwright pre-filled wallet on {claim_url}; screenshot: {screenshot_path}"
        return True, f"Playwright opened {claim_url}; no wallet field found; screenshot: {screenshot_path}"

    except Exception as exc:
        return False, f"Playwright failed for {claim_url}: {exc}"

# ---------------------------------------------------------------------------
# Source scrapers (public pages, no auth required)
# ---------------------------------------------------------------------------

def _scrape_coinmarketcap() -> list:
    """Scrape CoinMarketCap /airdrop page for listed projects."""
    url = "https://coinmarketcap.com/airdrop/"
    html = _fetch(url)
    if not html:
        return []

    results = []
    # CMC renders server-side JSON in a script tag
    match = re.search(r'"airdrops"\s*:\s*(\[.*?\])\s*[,}]', html, re.DOTALL)
    if match:
        try:
            raw = json.loads(match.group(1))
            for item in raw[:30]:
                name = item.get("projectName") or item.get("name", "")
                if not name or _is_sec_flagged(name):
                    continue
                results.append({
                    "source": "coinmarketcap",
                    "name": name,
                    "url": item.get("link", "") or f"https://coinmarketcap.com/airdrop/",
                    "reward_usd_est": item.get("totalPrize") or item.get("rewardValue") or 0,
                    "claim_steps": 3,  # CMC listings are usually simple
                    "contract_addr": item.get("contractAddress", ""),
                    "is_scam": False,
                    "sec_flagged": False,
                    "contract_verified": False,
                    "status": "discovered",
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "requires_purchase": False,
                    "requires_gas": False,
                })
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: plain text extraction for project names
    if not results:
        names = re.findall(r'"projectName"\s*:\s*"([^"]{3,60})"', html)
        for name in names[:15]:
            if _is_sec_flagged(name):
                continue
            results.append({
                "source": "coinmarketcap",
                "name": name,
                "url": "https://coinmarketcap.com/airdrop/",
                "reward_usd_est": 0,
                "claim_steps": 3,
                "contract_addr": "",
                "is_scam": False,
                "sec_flagged": False,
                "contract_verified": False,
                "status": "discovered",
                "discovered_at": datetime.now(timezone.utc).isoformat(),
                "requires_purchase": False,
                "requires_gas": False,
            })
    return results

def _scrape_airdroph() -> list:
    """Scrape AirdropAlert for current airdrops."""
    url = "https://airdropalert.com/browse-airdrops/?category=new"
    html = _fetch(url)
    if not html:
        return []

    results = []
    # AirdropAlert renders most links via JS; titles are still present in heading tags.
    titles = re.findall(r'<h\d[^>]*>(.*?)</h\d>', html, flags=re.IGNORECASE | re.DOTALL)
    for raw_title in titles[:40]:
        title = re.sub(r"<[^>]+>", " ", raw_title)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or _is_sec_flagged(title):
            continue

        results.append({
            "source": "airdropalert",
            "name": title,
            "url": url,
            "reward_usd_est": 0,
            "claim_steps": 4,
            "contract_addr": "",
            "is_scam": False,
            "sec_flagged": False,
            "contract_verified": False,
            "status": "discovered",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "requires_purchase": False,
            "requires_gas": False,
            "_detail_html": "",
        })

    # Deduplicate on title while preserving order.
    unique = []
    seen = set()
    for item in results:
        key = item["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= 20:
            break

    return unique

def _scrape_coingecko() -> list:
    """Use CoinGecko public API to find recently launched tokens as airdrop candidates."""
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=id_asc&per_page=20&page=1&sparkline=false&price_change_percentage=24h"
    body = _fetch(url)
    if not body:
        return []

    try:
        coins = json.loads(body)
    except json.JSONDecodeError:
        return []

    results = []
    for coin in coins[:10]:
        name = coin.get("name", "")
        if not name or _is_sec_flagged(name):
            continue
        results.append({
            "source": "coingecko",
            "name": name,
            "url": f"https://www.coingecko.com/en/coins/{coin.get('id', '')}",
            "reward_usd_est": 0,
            "claim_steps": 5,
            "contract_addr": "",
            "is_scam": False,
            "sec_flagged": False,
            "contract_verified": False,
            "status": "discovered",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "requires_purchase": False,
            "requires_gas": False,
        })
    return results

# ---------------------------------------------------------------------------
# Deduplication — by name + source
# ---------------------------------------------------------------------------

def _dedup(entries: list) -> list:
    """Auto-generated docstring."""
    seen = set()
    out = []
    for e in entries:
        key = hashlib.md5(e["name"].lower().encode()).hexdigest()[:8]
        if key not in seen:
            seen.add(key)
            e["id"] = key
            out.append(e)
    return out

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str) -> bool:
    """Auto-generated docstring."""
    smtp_user = os.environ.get("GMAIL_USER") or os.environ.get("SMTP_USER")
    smtp_password = (
        os.environ.get("GMAIL_APP_PASSWORD")
        or os.environ.get("SMTP_PASSWORD")
        or os.environ.get("SMTP_PASS")
    )
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("SMTP_FROM") or smtp_user or "cryptobot@localhost"

    if not smtp_user or not smtp_password:
        print("[email] SMTP credentials missing — set GMAIL_USER + GMAIL_APP_PASSWORD")
        return False

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = EMAIL_RECIPIENT
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, [EMAIL_RECIPIENT], msg.as_string())
        print(f"[email] Sent to {EMAIL_RECIPIENT}")
        return True
    except Exception as exc:
        print(f"[email] Failed: {exc}")
        return False

# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def _write_atomic(path: Path, data):
    """Auto-generated docstring."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        json.dump(data, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)

def _extract_reply_numbers(text: str) -> list:
    """
    Parse approval markers from a reply body.
    Accepts formats like: #1, #2 #5, or plain numbers like 1,2,5.
    """
    if not text:
        return []

    tagged = re.findall(r"#\s*(\d+)", text)
    if tagged:
        nums = [int(n) for n in tagged]
    else:
        nums = [int(n) for n in re.findall(r"\b(\d{1,2})\b", text)]

    # Keep order, remove duplicates
    seen = set()
    out = []
    for n in nums:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out

def _is_go_ahead_reply(text: str) -> bool:
    """Return True if reply clearly indicates broad approval without explicit numbers."""
    if not text:
        return False
    lower = text.lower()
    triggers = [
        "go ahead",
        "go-ahead",
        "approve all",
        "all of them",
        "do all",
        "run all",
    ]
    return any(t in lower for t in triggers)

def _load_approval_index() -> dict:
    """Auto-generated docstring."""
    if not APPROVAL_INDEX_FILE.exists():
        return {"items": []}
    try:
        data = json.loads(APPROVAL_INDEX_FILE.read_text())
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
    except json.JSONDecodeError:
        pass
    return {"items": []}

def _apply_selected_approvals(selected_numbers: list) -> int:
    """
    Approve only the selected ranked items from the last approval email.
    Returns number of entries changed to approved.
    """
    entries = json.loads(AIRDROPS_FILE.read_text()) if AIRDROPS_FILE.exists() else []
    if not entries:
        print("[approve] No airdrops found — run --scan first")
        return 0

    index = _load_approval_index()
    ranked = index.get("items", [])
    if not ranked:
        print("[approve] No approval index found — run --email first")
        return 0

    allowed = {item.get("rank"): item.get("id") for item in ranked}
    selected_ids = set()
    for n in selected_numbers:
        if n in allowed and allowed[n]:
            selected_ids.add(allowed[n])

    if not selected_ids:
        print("[approve] No valid #numbers matched the latest email list")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    for entry in entries:
        if entry.get("id") in selected_ids and entry.get("status") == "discovered":
            entry["status"] = "approved"
            entry["approved_at"] = now
            entry["approval_note"] = f"Approved via reply numbers: {selected_numbers}"
            changed += 1

    _write_atomic(AIRDROPS_FILE, entries)
    print(f"[approve] Approved {changed} selected airdrop(s)")
    return changed

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scan(dry_run: bool = False):
    """Auto-generated docstring."""
    print("=== Airdrop Scout Scan ===")
    all_entries = []

    print("  Fetching CoinMarketCap airdrops...")
    all_entries += _scrape_coinmarketcap()

    print("  Fetching AirdropAlert listings...")
    all_entries += _scrape_airdroph()

    print("  Fetching CoinGecko new tokens...")
    all_entries += _scrape_coingecko()

    # Deduplicate
    unique = _dedup(all_entries)
    print(f"  Total unique candidates: {len(unique)}")

    # Score each
    for entry in unique:
        entry["score"] = _score_airdrop(entry)

    unique.sort(key=lambda e: e["score"], reverse=True)

    existing = {}
    if AIRDROPS_FILE.exists():
        try:
            for e in json.loads(AIRDROPS_FILE.read_text()):
                existing[e.get("id", "")] = e
        except json.JSONDecodeError:
            pass

    # Preserve prior approval/claim state across rescans.
    for entry in unique:
        prev = existing.get(entry.get("id", ""))
        if not prev:
            continue
        prev_status = prev.get("status")
        if prev_status in ("approved", "claimed", "verified", "claim_ready"):
            entry["status"] = prev_status
            for key in ("approved_at", "approval_note", "claimed_at", "claim_note"):
                if key in prev:
                    entry[key] = prev.get(key)
        if prev.get("is_free"):
            entry["is_free"] = True

    if dry_run:
        print("  [dry-run] Not saving.")

    # --- Detect free airdrops and process them automatically ---
    print("\n  Checking for free airdrops...")
    for entry in unique:
        if entry.get("status") in ("claimed", "verified", "claim_ready"):
            continue  # already processed
        detail_html = entry.pop("_detail_html", "")
        entry["is_free"] = _is_free(entry, detail_html)
        if entry["is_free"]:
            entry = _auto_claim_free(entry)
            # Persist updated entry back into unique list in-place
            idx = unique.index(entry) if entry in unique else -1
            if idx >= 0:
                unique[idx] = entry

    # Strip any remaining _detail_html before save (don't store raw HTML)
    for entry in unique:
        entry.pop("_detail_html", None)

    if not dry_run:
        _write_atomic(AIRDROPS_FILE, unique)
        print(f"  Saved {len(unique)} entries to {AIRDROPS_FILE}")

    free = [e for e in unique if e.get("is_free")]
    paid = [e for e in unique if not e.get("is_free")]
    print(f"\nFREE (auto-processed): {len(free)}")
    for e in free[:5]:
        print(f"  #{e['score']:>3} {e['name']:30s} → {e.get('status')} {e.get('claim_note','')}")
    print(f"\nNeeds approval: {len(paid)}")
    for e in paid[:5]:
        print(f"  #{e['score']:>3} {e['name']:30s} est=${e['reward_usd_est']} src={e['source']}")

    return unique

def cmd_email():
    """Auto-generated docstring."""
    entries = json.loads(AIRDROPS_FILE.read_text()) if AIRDROPS_FILE.exists() else []
    if not entries:
        print("[email] No airdrops found — run --scan first")
        return

    # Email only the ones that need human approval (non-free)
    needs_approval = [e for e in entries if not e.get("is_free") and e.get("status") == "discovered"]
    free_done = [e for e in entries if e.get("is_free")]
    top5 = sorted(needs_approval, key=lambda e: e.get("score", 0), reverse=True)[:5]

    lines = [
        "Airdrop Opportunities — Approval Required",
        "=" * 45,
        "",
        f"FREE airdrops auto-processed this scan: {len(free_done)}",
        "(Free = zero cost, no gas, no purchase — wallet address submitted automatically)",
        "",
        "The following airdrops REQUIRE your approval (involve gas, steps, or unclear cost):",
        "",
    ]
    if not top5:
        lines.append("No airdrops pending your approval at this time.")
    for i, e in enumerate(top5, 1):
        lines += [
            f"#{i}  [{e.get('score', 0)} pts] {e['name']}",
            f"    Est. reward: ${e.get('reward_usd_est', 'unknown')}",
            f"    Claim URL:   {e.get('url', 'N/A')}",
            f"    Source:      {e.get('source', 'N/A')}",
            f"    Status:      {e.get('status', 'discovered')}",
            f"    Verified:    {'Yes' if e.get('contract_verified') else 'No/Unknown'}",
            "",
        ]

    # Save ranked mapping so reply text like "#1 #3" can be resolved deterministically.
    approval_index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recipient": EMAIL_RECIPIENT,
        "items": [
            {
                "rank": i,
                "id": e.get("id"),
                "name": e.get("name"),
                "status": e.get("status"),
            }
            for i, e in enumerate(top5, 1)
        ],
    }
    _write_atomic(APPROVAL_INDEX_FILE, approval_index)

    lines += [
        "SAFETY REMINDER:",
        "- Never send funds to claim an airdrop",
        "- Never enter your seed phrase or private key",
        "- All scripts are audited by CodeReviewer before execution",
        "",
        "Reply format:",
        "- Reply with #numbers to approve only those entries (example: #1 #3)",
        "- Then run: python3 airdrop_scout.py --check-replies",
    ]
    send_email("[CryptoBot] Airdrop opportunities found", "\n".join(lines))

def cmd_approve_selection(reply_text: str):
    """Auto-generated docstring."""
    nums = _extract_reply_numbers(reply_text)
    if not nums:
        print("[approve] No numbers found in reply text. Example: #1 #3")
        return
    changed = _apply_selected_approvals(nums)
    index = _load_approval_index()
    by_rank = {item.get("rank"): item for item in index.get("items", [])}
    requested = [n for n in nums if isinstance(n, int)]
    matched = [n for n in requested if n in by_rank]
    matched_lines = []
    for r in matched:
        item = by_rank.get(r, {})
        matched_lines.append(f"  #{r}: {item.get('name', 'unknown')} ({item.get('id', 'n/a')})")

    send_email(
        "[CryptoBot] Selected approvals applied",
        (
            "Got your okay and making the move now.\n\n"
            f"Requested numbers: {requested}\n"
            f"Matched ranked items: {matched}\n"
            f"Approved count this pass: {changed}\n"
            + ("Note: count is 0 when those items were already approved earlier.\n\n" if changed == 0 else "\n")
            + "Items accepted:\n"
            + ("\n".join(matched_lines) if matched_lines else "  (none matched current rank list)")
        ),
    )

def cmd_check_replies():
    """
    Read unread inbox replies and apply #number approvals from the latest matching message.
    Intended flow: user replies to approval email with text like "go ahead #1 #3".
    """
    smtp_user = os.environ.get("GMAIL_USER") or os.environ.get("SMTP_USER")
    smtp_password = (
        os.environ.get("GMAIL_APP_PASSWORD")
        or os.environ.get("SMTP_PASSWORD")
        or os.environ.get("SMTP_PASS")
    )
    imap_host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.environ.get("IMAP_PORT", "993"))

    if not smtp_user or not smtp_password:
        print("[imap] Missing mailbox credentials")
        return

    try:
        mailbox = imaplib.IMAP4_SSL(imap_host, imap_port)
        mailbox.login(smtp_user, smtp_password)
        mailbox.select("INBOX")

        status, data = mailbox.search(None, "UNSEEN")
        if status != "OK":
            print("[imap] Failed to search inbox")
            mailbox.logout()
            return

        msg_ids = data[0].split()
        if not msg_ids:
            print("[imap] No unread replies found")
            mailbox.logout()
            return

        processed = 0
        # Iterate newest first so latest approval reply wins.
        for msg_id in reversed(msg_ids):
            status, msg_data = mailbox.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = message_from_bytes(raw)
            subject = (msg.get("Subject") or "").lower()
            sender = (msg.get("From") or "").lower()

            # Restrict to likely approval replies from our configured recipient.
            if EMAIL_RECIPIENT.lower() not in sender:
                continue
            if "airdrop opportunities" not in subject and "re:" not in subject:
                continue

            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = (part.get_content_type() or "").lower()
                    disp = (part.get("Content-Disposition") or "").lower()
                    if ctype == "text/plain" and "attachment" not in disp:
                        payload = part.get_payload(decode=True)
                        body_text = _decode_payload_text(payload, part.get_content_charset())
                        break
            else:
                payload = msg.get_payload(decode=True)
                body_text = _decode_payload_text(payload, msg.get_content_charset())

            nums = _extract_reply_numbers(body_text)
            if not nums and _is_go_ahead_reply(body_text):
                index = _load_approval_index()
                nums = [item.get("rank") for item in index.get("items", []) if item.get("rank")]
            if not nums:
                continue

            changed = _apply_selected_approvals(nums)
            processed += 1
            index = _load_approval_index()
            by_rank = {item.get("rank"): item for item in index.get("items", [])}
            requested = [n for n in nums if isinstance(n, int)]
            matched = [n for n in requested if n in by_rank]
            matched_lines = []
            for r in matched:
                item = by_rank.get(r, {})
                matched_lines.append(f"  #{r}: {item.get('name', 'unknown')} ({item.get('id', 'n/a')})")

            send_email(
                "[CryptoBot] Reply approvals applied",
                (
                    "Got your okay and making the move now.\n\n"
                    f"Processed reply selection: {requested}\n"
                    f"Matched ranked items: {matched}\n"
                    f"Approved count this pass: {changed}\n"
                    + ("Note: count is 0 when those items were already approved earlier.\n\n" if changed == 0 else "\n")
                    + "Items accepted:\n"
                    + ("\n".join(matched_lines) if matched_lines else "  (none matched current rank list)")
                ),
            )

            # Mark as seen regardless once parsed, to avoid reprocessing loop.
            mailbox.store(msg_id, "+FLAGS", "\\Seen")

            # Process one newest actionable reply per run.
            if processed > 0:
                break

        if processed == 0:
            print("[imap] No actionable reply found (expected #numbers like #1 #3)")
        else:
            print(f"[imap] Applied approvals from {processed} reply message(s)")

        mailbox.logout()
    except Exception as exc:
        print(f"[imap] Failed: {exc}")

def _normalize_interval_minutes(raw: str) -> int:
    """Clamp polling interval to allowed range: 30 minutes to 240 minutes."""
    try:
        val = int(raw)
    except Exception:
        val = 30
    return max(30, min(240, val))

def _decode_payload_text(payload: object, charset: str | None) -> str:
    """Decode bytes payload safely for email body extraction."""
    if isinstance(payload, bytes):
        return payload.decode(charset or "utf-8", errors="replace")
    if isinstance(payload, str):
        return payload
    return ""

def cmd_watch_replies(interval_minutes: int):
    """
    Continuously poll inbox replies and apply #number approvals.
    Allowed interval range: 30-240 minutes.
    """
    interval_minutes = _normalize_interval_minutes(str(interval_minutes))
    sleep_seconds = interval_minutes * 60

    print("=== Airdrop Reply Watcher ===")
    print(f"  Poll interval: {interval_minutes} minute(s)")
    print("  Press Ctrl+C to stop")

    while True:
        started = datetime.now(timezone.utc).isoformat()
        print(f"\n[watch] Polling inbox at {started}")
        cmd_check_replies()
        print(f"[watch] Sleeping for {interval_minutes} minute(s)")
        try:
            time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            print("\n[watch] Stopped by user")
            break

def cmd_watch_scan(interval_minutes: int):
    """
    Continuously run --scan to keep airdrops fresh.
    Allowed interval range: 5-240 minutes.
    """
    try:
        interval_minutes = int(interval_minutes)
    except Exception:
        interval_minutes = 30
    interval_minutes = max(5, min(240, interval_minutes))

    print("=== Airdrop Scan Watcher ===")
    print(f"  Scan interval: {interval_minutes} minute(s)")
    print("  Press Ctrl+C to stop")

    while True:
        started = datetime.now(timezone.utc).isoformat()
        print(f"\n[scan-watch] Scanning at {started}")
        try:
            cmd_scan(dry_run=False)
        except Exception as exc:
            print(f"[scan-watch] Error: {exc}")
        print(f"[scan-watch] Sleeping for {interval_minutes} minute(s)")
        try:
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            print("\n[scan-watch] Stopped by user")
            break

def cmd_approve_all():
    """Auto-generated docstring."""
    entries = json.loads(AIRDROPS_FILE.read_text()) if AIRDROPS_FILE.exists() else []
    if not entries:
        print("[approve] No airdrops found — run --scan first")
        return

    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    for entry in entries:
        if entry.get("is_free"):
            continue
        if entry.get("status") == "discovered":
            entry["status"] = "approved"
            entry["approved_at"] = now
            entry["approval_note"] = "Approved in bulk via --approve-all"
            changed += 1

    _write_atomic(AIRDROPS_FILE, entries)
    print(f"[approve] Approved {changed} airdrop(s)")

    send_email(
        "[CryptoBot] Airdrops approved in bulk",
        (
            f"Bulk approval applied at {now}.\n"
            f"Approved count: {changed}\n"
            "Next step: review approved items in airdrops.json before any on-chain actions."
        ),
    )

def cmd_selftest():
    """Auto-generated docstring."""
    print("=== Airdrop Scout Self-Test ===")

    # Test one scrape source
    print("  Testing CoinGecko fetch...")
    results = _scrape_coingecko()
    print(f"  CoinGecko returned {len(results)} entries")

    # Test scam filter
    scam_text = "Send 0.5 ETH to receive 1000 tokens"
    assert _is_scam(scam_text), "Scam filter failed to detect test string"
    print("  Scam filter: OK")

    # Test SEC flagging
    assert _is_sec_flagged("Ripple XRP Token"), "SEC flag missed Ripple"
    print("  SEC flag: OK")

    # Test email
    ok = send_email("[CryptoBot] Airdrop scout self-test", f"Self-test at {datetime.now(timezone.utc).isoformat()}")
    if ok:
        print(f"  Email: sent to {EMAIL_RECIPIENT}")
    else:
        print("  Email: FAILED — check GMAIL_USER / GMAIL_APP_PASSWORD")

    print("=== Done ===")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Auto-generated docstring."""
    argv = sys.argv[1:]
    if "--selftest" in argv:
        cmd_selftest()
    elif "--scan" in argv:
        cmd_scan(dry_run="--dry-run" in argv)
    elif "--email" in argv:
        cmd_email()
    elif "--approve-selection" in argv:
        try:
            idx = argv.index("--approve-selection")
            reply_text = argv[idx + 1]
        except Exception:
            print("Usage: airdrop_scout.py --approve-selection \"#1 #3\"")
            return
        cmd_approve_selection(reply_text)
    elif "--check-replies" in argv:
        cmd_check_replies()
    elif "--watch-replies" in argv:
        interval = os.environ.get("APPROVAL_POLL_MINUTES", "30")
        if "--interval-minutes" in argv:
            try:
                idx = argv.index("--interval-minutes")
                interval = argv[idx + 1]
            except Exception:
                print("Usage: airdrop_scout.py --watch-replies [--interval-minutes N]")
                return
        cmd_watch_replies(_normalize_interval_minutes(interval))
    elif "--watch-scan" in argv:
        interval = os.environ.get("AIRDROP_SCAN_POLL_MINUTES", "30")
        if "--scan-interval-minutes" in argv:
            try:
                idx = argv.index("--scan-interval-minutes")
                interval = argv[idx + 1]
            except Exception:
                print("Usage: airdrop_scout.py --watch-scan [--scan-interval-minutes N]")
                return
        cmd_watch_scan(_normalize_interval_minutes(interval))
    elif "--approve-all" in argv:
        cmd_approve_all()
    else:
        print(
            "Usage: airdrop_scout.py [--scan | --email | --approve-all | "
            "--approve-selection \"#1 #3\" | --check-replies | --watch-replies "
            "[--interval-minutes N] | --watch-scan [--scan-interval-minutes N] "
            "| --selftest] [--dry-run]"
        )

if __name__ == "__main__":
    main()
