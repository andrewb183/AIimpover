#!/usr/bin/env python3
"""
Escalating Retry System with Learning Database
Handles attempts 1-24 with progressive escalation strategies
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

class LearningFixDatabase:
    """Tracks successful fixes and learns from patterns"""

    def __init__(self, db_path: str = None):
        """Auto-generated docstring."""
        if db_path is None:
            db_path = str(Path(__file__).parent / "implementation_outputs" / "fix_database.json")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_db()

    def _load_db(self) -> Dict[str, Any]:
        """Load database or create new"""
        if self.db_path.exists():
            try:
                with open(self.db_path) as f:
                    return json.load(f)
            except Exception:
                return self._init_new_db()
        return self._init_new_db()

    def _init_new_db(self) -> Dict[str, Any]:
        """Initialize new learning database"""
        return {
            "created_at": datetime.utcnow().isoformat(),
            "version": "2.0",
            "total_fixes": 0,
            "successful_fixes": 0,
            "reuse_rate": 0.0,
            "errors_by_type": {},
            "fixes_by_error_signature": {},
            "reuse_wins": 0,
            "learning_efficiency": 0.0,
            "statistics": {
                "day_1_fixes": 0,
                "week_1_fixes": 0,
                "month_growth": [],
            }
        }

    def log_successful_fix(self, error_type: str, error_msg: str, fix: str, language: str):
        """Log a successful fix for learning"""
        signature = hashlib.md5(error_msg[:100].encode()).hexdigest()[:8]
        normalized_language = str(language or "").strip() or "unknown"
        normalized_error_type = str(error_type or "").strip() or "unknown"

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "error_type": normalized_error_type,
            "error_signature": signature,
            "language": normalized_language,
            "fix": fix[:500],  # Store first 500 chars of fix
            "attempt": self.data["total_fixes"] + 1,
        }

        if signature not in self.data["fixes_by_error_signature"]:
            self.data["fixes_by_error_signature"][signature] = []

        self.data["fixes_by_error_signature"][signature].append(entry)
        self.data["total_fixes"] += 1
        self.data["successful_fixes"] += 1

        # Update statistics
        self._update_stats()
        self._save_db()

    def find_similar_fixes(self, error_msg: str, error_type: str) -> List[Dict]:
        """Find similar fixes from database"""
        signature = hashlib.md5(error_msg[:100].encode()).hexdigest()[:8]

        if signature in self.data["fixes_by_error_signature"]:
            self.data["reuse_wins"] += 1
            return self.data["fixes_by_error_signature"][signature]

        return []

    def _update_stats(self):
        """Update learning statistics"""
        if self.data["total_fixes"] > 0:
            self.data["reuse_rate"] = (self.data["reuse_wins"] / self.data["total_fixes"]) * 100
            self.data["learning_efficiency"] = (self.data["successful_fixes"] / max(1, self.data["total_fixes"])) * 100

    def _save_db(self):
        """Save database to disk"""
        with open(self.db_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def get_stats(self) -> Dict[str, Any]:
        """Get learning database statistics"""
        self._update_stats()
        return {
            "total_fixes": self.data["total_fixes"],
            "successful_fixes": self.data["successful_fixes"],
            "reuse_rate": f"{self.data['reuse_rate']:.1f}%",
            "learning_efficiency": f"{self.data['learning_efficiency']:.1f}%",
            "reuse_wins": self.data["reuse_wins"],
            "unique_error_signatures": len(self.data["fixes_by_error_signature"]),
        }

def escalate_retry_for_project(
    project_id: str,
    attempt: int,
    error_msg: str,
    error_type: str,
    language: str,
    learning_db: LearningFixDatabase = None
) -> Dict[str, Any]:
    """
    Progressive escalation strategy based on attempt number.

    Tier 1: Attempts 1-3   → Same prompt, different seed
    Tier 2: Attempt 4      → AI analysis + targeted fix strategy
    Tier 3: Attempts 5-8   → Conservative rewrites
    Tier 4: Attempts 9-16  → Moderate to aggressive rewrites
    Tier 5: Attempts 17-24 → Nuclear options (complete rewrite)
    """

    if learning_db is None:
        learning_db = LearningFixDatabase()

    # Check if we have a learned fix
    similar_fixes = learning_db.find_similar_fixes(error_msg, error_type)
    if similar_fixes and attempt > 3:
        return {
            "attempt": attempt,
            "strategy": "learned_fix",
            "fix_instruction": similar_fixes[0].get("fix", ""),
            "confidence": "high",
            "reuse_from_attempt": similar_fixes[0].get("attempt"),
        }

    # Escalation strategy
    if attempt <= 3:
        return {
            "attempt": attempt,
            "strategy": "standard_retry",
            "instruction": "Retry with different random seed, same approach",
            "tier": 1,
            "seed_variation": attempt * 1000,
        }

    elif attempt == 4:
        return {
            "attempt": attempt,
            "strategy": "ai_analysis",
            "instruction": "Analyze all 3 error logs, generate 20 targeted fix variations",
            "tier": 2,
            "analysis_depth": "deep",
        }

    elif 5 <= attempt <= 8:
        strategies = {
            5: "Fix syntax, keep logic (conservative)",
            6: "Rewrite problematic section only",
            7: "Different language construction",
            8: "Simplify entire function",
        }
        return {
            "attempt": attempt,
            "strategy": "conservative_rewrite",
            "instruction": strategies.get(attempt, "Rewrite conservatively"),
            "tier": 3,
            "preserve_logic": True,
        }

    elif 9 <= attempt <= 16:
        intensity = "moderate" if attempt <= 12 else "aggressive"
        strategies = {
            9: "Moderate: Different algorithm, same language",
            10: "Moderate: Use alternative libraries",
            11: "Moderate: Change architecture",
            12: "Moderate: Complete function redesign",
            13: "Aggressive: Remove problematic sections",
            14: "Aggressive: Use only stdlib",
            15: "Aggressive: Minimal implementation",
            16: "Aggressive: Ultra-simple fallback",
        }
        return {
            "attempt": attempt,
            "strategy": f"{intensity}_rewrite",
            "instruction": strategies.get(attempt, "Rewrite aggressively"),
            "tier": 4,
            "preserve_interfaces": True,
        }

    else:  # attempts 17-24
        strategies = {
            17: "Nuclear: Single file, single function, core only",
            18: "Nuclear: Skeleton implementation",
            19: "Nuclear: Mock/stub implementation",
            20: "Nuclear: Data structure only",
            21: "Nuclear: Error handling wrapper",
            22: "Nuclear: Timeout wrapper",
            23: "Nuclear: Return defaults",
            24: "Nuclear: Documentation only",
        }
        return {
            "attempt": attempt,
            "strategy": "nuclear_option",
            "instruction": strategies.get(attempt, "Last resort: minimal stub"),
            "tier": 5,
            "give_up_after": attempt >= 24,
        }

def summarize_retry_strategy(
    project_id: str,
    attempt: int,
    error_msg: str,
    error_type: str,
    language: str,
    learning_db: Optional[LearningFixDatabase] = None,
) -> Dict[str, Any]:
    """Return a compact retry summary that UI and logs can display directly."""
    plan = escalate_retry_for_project(
        project_id=project_id,
        attempt=attempt,
        error_msg=error_msg,
        error_type=error_type,
        language=language,
        learning_db=learning_db,
    )
    return {
        "project_id": project_id,
        "attempt": attempt,
        "error_type": str(error_type or "").strip() or "unknown",
        "language": str(language or "").strip() or "unknown",
        "strategy": plan.get("strategy", ""),
        "tier": plan.get("tier", 0),
        "instruction": plan.get("instruction") or plan.get("fix_instruction", ""),
        "confidence": plan.get("confidence", "unknown"),
        "reuse_from_attempt": plan.get("reuse_from_attempt"),
    }

def recommend_retry_next_action(error_msg: str, error_type: str, language: str, attempt: int = 1) -> Dict[str, Any]:
    """Convenience wrapper for quick caller-side retry guidance."""
    db = LearningFixDatabase()
    return summarize_retry_strategy(
        project_id="default",
        attempt=attempt,
        error_msg=error_msg,
        error_type=error_type,
        language=language,
        learning_db=db,
    )

def explain_retry_tier(attempt: int) -> str:
    """Translate a retry attempt into a human-readable tier label."""
    if attempt <= 3:
        return "tier_1_standard_retry"
    if attempt == 4:
        return "tier_2_ai_analysis"
    if 5 <= attempt <= 8:
        return "tier_3_conservative_rewrite"
    if 9 <= attempt <= 16:
        return "tier_4_moderate_to_aggressive_rewrite"
    return "tier_5_nuclear_option"

def create_fix_database_if_needed():
    """Initialize fix database"""
    base_dir = Path(__file__).parent / "implementation_outputs"
    base_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_dir / "fix_database.json"

    db = LearningFixDatabase(str(db_path))
    if not db_path.exists():
        # Force a save
        db._save_db()
        print(f"✅ Created fix database at {db_path}")
    else:
        print(f"✅ Fix database already exists at {db_path}")

    return db

if __name__ == "__main__":
    # Initialize learning database
    db = create_fix_database_if_needed()

    # Show statistics
    print("\nLearning Database Statistics:")
    print(json.dumps(db.get_stats(), indent=2))

    # Show escalation examples
    print("\nEscalation Strategy Examples:")
    for attempt in [1, 3, 4, 8, 12, 16, 24]:
        result = escalate_retry_for_project(
            "test-project",
            attempt,
            "SyntaxError: invalid syntax",
            "syntax_error",
            "python",
            db
        )
        print(f"\nAttempt {attempt:2d}: {result.get('strategy'):25} → {result.get('instruction', result.get('tier'))}")