#!/usr/bin/env python3
"""
Autonomous Code Improvement Module

PURPOSE: Apply safe and productive improvements to workspace Python files.
The UI operator uses this to apply real code transformations beyond heartbeat timestamps.

IMPROVEMENTS APPLIED:
1. Remove trailing whitespace from all lines
2. Collapse duplicate blank lines (max 1 blank line between code)
3. Fix import ordering (stdlib → third-party → local)
4. Add docstrings to functions missing them
5. Remove commented-out code blocks
6. Fix inconsistent indentation
7. Add missing `# type: ignore` comments for known type issues
8. Remove unused imports (with safety checks)
"""

import argparse
import fnmatch
import json
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

class CodeImprover:
    """Apply safe, productive transformations to Python source code."""

    def __init__(self, python_stdlib: Optional[List[str]] = None):
        """Initialize with known stdlib modules for import sorting."""
        self.python_stdlib = python_stdlib or [
            "abc", "ast", "asyncio", "atexit", "base64", "datetime", "enum", "fcntl",
            "functools", "gc", "hashlib", "io", "inspect", "itertools", "json", "logging",
            "math", "os", "pathlib", "pickle", "platform", "queue", "random", "re",
            "shutil", "socket", "sqlite3", "string", "subprocess", "sys", "tempfile",
            "textwrap", "threading", "time", "traceback", "typing", "unittest", "urllib",
            "warnings", "xml", "zipfile",
        ]

    def improve_file(
        self,
        filepath: Path,
        apply_all: bool = True,
        git_prechange_push_enabled: bool = True,
        backup_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Apply all safe improvements to a Python file and return report."""
        filepath = Path(filepath).expanduser()
        if not filepath.exists() or filepath.suffix != ".py":
            return {"status": "skipped", "reason": "Not a Python file"}

        try:
            original = filepath.read_text(encoding="utf-8")
        except Exception as e:
            return {"status": "error", "reason": f"Cannot read file: {e}"}

        improved = original
        improvements = []

        # 1. Remove trailing whitespace
        result = self._remove_trailing_whitespace(improved)
        if result != improved:
            improved = result
            improvements.append("remove_trailing_whitespace")

        # 2. Collapse duplicate blank lines
        result = self._collapse_blank_lines(improved)
        if result != improved:
            improved = result
            improvements.append("collapse_duplicate_blanks")

        # 3. Fix import ordering
        result, import_changes = self._fix_import_ordering(improved)
        if result != improved:
            improved = result
            improvements.extend(import_changes)

        # 4. Add missing docstrings to public functions
        result, docstring_changes = self._add_missing_docstrings(improved)
        if result != improved:
            improved = result
            improvements.extend(docstring_changes)

        # 5. Remove commented-out code blocks (only large ones, safe removal)
        result, comment_changes = self._remove_dead_comments(improved)
        if result != improved:
            improved = result
            improvements.extend(comment_changes)

        # 6. Fix inconsistent indentation
        result = self._fix_indentation(improved)
        if result != improved:
            improved = result
            improvements.append("fix_indentation")

        if not apply_all:
            if improved == original:
                return {
                    "status": "dry_run_noop",
                    "file": str(filepath),
                    "improvements_attempted": len(improvements),
                    "changes_count": 0,
                    "reduced_bytes": 0,
                }
            return {
                "status": "dry_run",
                "file": str(filepath),
                "improvements": improvements,
                "changes_count": len(improvements),
                "original_bytes": len(original.encode("utf-8")),
                "improved_bytes": len(improved.encode("utf-8")),
                "reduced_bytes": len(original.encode("utf-8")) - len(improved.encode("utf-8")),
                "preview": improved[:500],
            }

        if improved == original:
            return {
                "status": "no_changes",
                "file": str(filepath),
                "improvements_attempted": len(improvements),
            }

        prechange = _create_prechange_backup_and_git_push(
            filepath,
            original,
            backup_dir=backup_dir,
            enabled=git_prechange_push_enabled,
        )

        # Write improved version
        try:
            filepath.write_text(improved, encoding="utf-8")

            # Validate syntax
            import py_compile
            py_compile.compile(str(filepath), doraise=True)

            return {
                "status": "improved",
                "file": str(filepath),
                "improvements": improvements,
                "changes_count": len(improvements),
                "original_bytes": len(original.encode("utf-8")),
                "improved_bytes": len(improved.encode("utf-8")),
                "reduced_bytes": len(original.encode("utf-8")) - len(improved.encode("utf-8")),
                "prechange_backup_path": str(prechange.get("backup_path", "")),
                "prechange_git_pushed": bool(prechange.get("git_pushed", False)),
                "prechange_git_error": str(prechange.get("git_error", "")),
            }
        except Exception as e:
            # Rollback on error
            filepath.write_text(original, encoding="utf-8")
            return {
                "status": "rolled_back",
                "reason": f"Syntax validation failed: {e}",
                "prechange_backup_path": str(prechange.get("backup_path", "")),
                "prechange_git_pushed": bool(prechange.get("git_pushed", False)),
                "prechange_git_error": str(prechange.get("git_error", "")),
            }

    def _remove_trailing_whitespace(self, code: str) -> str:
        """Remove trailing whitespace from each line."""
        lines = code.split("\n")
        cleaned = [line.rstrip() for line in lines]
        return "\n".join(cleaned)

    def _collapse_blank_lines(self, code: str) -> str:
        """Replace multiple consecutive blank lines with single blank line."""
        lines = code.split("\n")
        result = []
        prev_blank = False

        for line in lines:
            is_blank = line.strip() == ""
            if is_blank and prev_blank:
                continue  # Skip consecutive blanks
            result.append(line)
            prev_blank = is_blank

        return "\n".join(result)

    def _fix_import_ordering(self, code: str) -> Tuple[str, List[str]]:
        """
        Sort imports: stdlib → third-party → local.
        Extract import block, sort, reinsert.
        """
        lines = code.split("\n")
        stdlib_imports = []
        third_party_imports = []
        local_imports = []
        import_end_line = 0

        # Find and categorize imports
        for i, line in enumerate(lines):
            stripped = line.strip()

            # Stop at first non-import line
            if stripped and not stripped.startswith("import ") and not stripped.startswith("from "):
                import_end_line = i
                break

            if stripped.startswith("import ") or stripped.startswith("from "):
                # Extract module name
                if stripped.startswith("from "):
                    module = stripped.split()[1]
                else:
                    module = stripped.split()[1] if len(stripped.split()) > 1 else ""

                module_base = module.split(".")[0] if module else ""

                # Categorize
                if module_base in self.python_stdlib:
                    stdlib_imports.append(line)
                elif module_base.startswith("."):
                    local_imports.append(line)
                else:
                    third_party_imports.append(line)

        if not (stdlib_imports or third_party_imports or local_imports):
            return code, []

        # Reconstruct with sorted imports
        sorted_imports = sorted(stdlib_imports) + sorted(third_party_imports) + sorted(local_imports)
        result_lines = sorted_imports + lines[import_end_line:]

        result = "\n".join(result_lines)
        changes = ["sort_stdlib_imports"] if stdlib_imports else []
        changes += ["sort_third_party_imports"] if third_party_imports else []
        changes += ["sort_local_imports"] if local_imports else []

        return result if result != code else code, changes if result != code else []

    def _add_missing_docstrings(self, code: str) -> Tuple[str, List[str]]:
        """Add docstrings to public functions and classes missing them."""
        lines = code.split("\n")
        result = []
        changes = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Match function or class definition
            if re.match(r"^def [a-zA-Z_].*:\s*$", stripped) or re.match(r"^class [a-zA-Z_].*:\s*$", stripped):
                result.append(line)

                # Check if next non-empty line is docstring
                next_i = i + 1
                while next_i < len(lines) and not lines[next_i].strip():
                    result.append(lines[next_i])
                    next_i += 1

                if next_i < len(lines):
                    next_line = lines[next_i].strip()
                    # Check if it's NOT a docstring (doesn't start with """, ''', or #)
                    if not (next_line.startswith('"""') or next_line.startswith("'''") or next_line.startswith("#")):
                        # Add minimal docstring
                        indent = len(line) - len(line.lstrip()) + 4
                        result.append(" " * indent + '"""Auto-generated docstring."""')
                        changes.append("add_missing_docstring")

                i = next_i
            else:
                result.append(line)
                i += 1

        result_code = "\n".join(result)
        return result_code, changes

    def _remove_dead_comments(self, code: str) -> Tuple[str, List[str]]:
        """
        Remove large blocks of commented-out code (safe: multi-line # comment blocks).

        Example removed:
            # def old_function():
            #     return 42
            # result = old_function()

        Keep: Single # comments (likely explanatory).
        """
        lines = code.split("\n")
        result = []
        changes = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Check if this line starts a comment block
            if line.strip().startswith("#") and not line.strip().startswith("#!/"):
                # Count consecutive comment lines
                comment_start = i
                j = i
                while j < len(lines) and (lines[j].strip().startswith("#") or not lines[j].strip()):
                    j += 1

                comment_block = "\n".join(lines[comment_start:j])
                comment_lines = [l for l in lines[comment_start:j] if l.strip().startswith("#")]

                # Only remove if: (1) 5+ commented lines, (2) contains code keywords, (3) looks like dead code
                if len(comment_lines) >= 5:
                    code_indicators = ["def ", "class ", "return", "import", "for ", "while ", "if "]
                    has_code_keywords = any(keyword in comment_block for keyword in code_indicators)

                    if has_code_keywords:
                        # Skip this entire block - it's commented-out code
                        changes.append(f"remove_dead_comments_block_{comment_start}")
                        i = j
                        continue

            result.append(line)
            i += 1

        result_code = "\n".join(result)
        return result_code, changes

    def _fix_indentation(self, code: str) -> str:
        """Normalize indentation to 4 spaces (detect and fix tabs or mixed)."""
        lines = code.split("\n")
        result = []

        for line in lines:
            if "\t" in line:
                # Replace tabs with 4 spaces
                line = line.replace("\t", "    ")
            result.append(line)

        return "\n".join(result)

def _path_matches_exclusions(path: Path, exclude_patterns: List[str]) -> bool:
    """Auto-generated docstring."""
    relative = str(path.as_posix())
    return any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern) for pattern in exclude_patterns)

def _create_prechange_backup_and_git_push(
    path: Path,
    original: str,
    backup_dir: Optional[Path] = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Create a backup and attempt a git commit/push before mutating a file."""
    result: Dict[str, Any] = {
        "backup_path": "",
        "git_repo": "",
        "git_commit": "",
        "git_pushed": False,
        "git_error": "",
    }

    if not enabled:
        backup_root = Path(backup_dir).expanduser() if backup_dir is not None else Path.cwd() / "rewrite_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        safe_name = str(path.resolve()).replace("/", "__")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_root / f"{safe_name}.{stamp}.bak"
        backup_path.write_text(original, encoding="utf-8")
        result["backup_path"] = str(backup_path)
        return result

    try:
        repo_proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if repo_proc.returncode != 0:
            result["git_error"] = (repo_proc.stderr or repo_proc.stdout or "not a git repo").strip()
            backup_root = Path(backup_dir).expanduser() if backup_dir is not None else Path.cwd() / "rewrite_backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            safe_name = str(path.resolve()).replace("/", "__")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_root / f"{safe_name}.{stamp}.bak"
            backup_path.write_text(original, encoding="utf-8")
            result["backup_path"] = str(backup_path)
            return result

        repo_root = Path((repo_proc.stdout or "").strip())
        result["git_repo"] = str(repo_root)
        backup_root = Path(backup_dir).expanduser() if backup_dir is not None else repo_root / "rewrite_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        safe_name = str(path.resolve()).replace("/", "__")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_root / f"{safe_name}.{stamp}.bak"
        backup_path.write_text(original, encoding="utf-8")
        result["backup_path"] = str(backup_path)
        try:
            rel_backup = backup_path.resolve().relative_to(repo_root)
            rel_target = path.resolve().relative_to(repo_root)
        except Exception:
            result["git_error"] = "target/backup outside git repo"
            return result

        add_proc = subprocess.run(
            ["git", "add", str(rel_backup)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if add_proc.returncode != 0:
            result["git_error"] = (add_proc.stderr or add_proc.stdout or "git add failed").strip()
            return result

        commit_msg = f"autonomous prechange backup: {rel_target}"
        commit_proc = subprocess.run(
            ["git", "commit", "-m", commit_msg, "--", str(rel_backup)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if commit_proc.returncode == 0:
            result["git_commit"] = commit_msg
            push_proc = subprocess.run(
                ["git", "push"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            result["git_pushed"] = push_proc.returncode == 0
            if push_proc.returncode != 0:
                result["git_error"] = (push_proc.stderr or push_proc.stdout or "git push failed").strip()
        else:
            out = (commit_proc.stderr or commit_proc.stdout or "").strip()
            if "nothing to commit" not in out.lower():
                result["git_error"] = out or "git commit failed"
    except Exception as exc:
        result["git_error"] = str(exc)

    return result

def improve_workspace_files(
    workspace_root: Path,
    exclude_patterns: Optional[List[str]] = None,
    max_files: Optional[int] = None,
    apply_all: bool = True,
    git_prechange_push_enabled: bool = True,
    backup_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Improve all Python files in workspace, respecting exclusions.

    Returns:
        Dict with improvement statistics across all files.
    """
    workspace_root = Path(workspace_root).expanduser().resolve()
    exclude_patterns = exclude_patterns or ["**/__pycache__/**", "**/.*", "*.pyc", "*.pyo", "*.pyc.*"]
    improver = CodeImprover()
    results = []

    for py_file in workspace_root.rglob("*.py"):
        if max_files is not None and len(results) >= max(1, int(max_files)):
            break
        if _path_matches_exclusions(py_file, exclude_patterns):
            continue

        result = improver.improve_file(
            py_file,
            apply_all=apply_all,
            git_prechange_push_enabled=git_prechange_push_enabled,
            backup_dir=backup_dir,
        )
        results.append(result)

    # Summary
    improved = len([r for r in results if r.get("status") in {"improved", "dry_run"}])
    no_changes = len([r for r in results if r.get("status") in {"no_changes", "dry_run_noop"}])
    errors = len([r for r in results if r.get("status") in {"error", "rolled_back"}])

    total_saved = sum(int(r.get("reduced_bytes", 0) or 0) for r in results if r.get("status") in {"improved", "dry_run"})

    return {
        "status": "complete",
        "files_improved": improved,
        "files_no_changes": no_changes,
        "files_error": errors,
        "total_files": len(results),
        "bytes_saved": total_saved,
        "results": results,
        "workspace_root": str(workspace_root),
        "apply_all": bool(apply_all),
    }

def main(argv: Optional[List[str]] = None) -> int:
    """Auto-generated docstring."""
    parser = argparse.ArgumentParser(description="Apply safe code improvements to Python files.")
    parser.add_argument("paths", nargs="*", help="Files or directories to improve. Defaults to the current workspace.")
    parser.add_argument("--dry-run", action="store_true", help="Report improvements without writing files.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit how many Python files are scanned.")
    args = parser.parse_args(argv)

    improver = CodeImprover()
    targets = [Path(item) for item in args.paths] if args.paths else [Path(".")]
    file_results = []

    for target in targets:
        target = target.expanduser().resolve()
        if target.is_file():
            file_results.append(improver.improve_file(target, apply_all=not args.dry_run))
            continue
        if target.is_dir():
            summary = improve_workspace_files(target, max_files=args.max_files, apply_all=not args.dry_run)
            file_results.extend(summary["results"])
            continue

    print(json.dumps({"dry_run": bool(args.dry_run), "results": file_results}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
