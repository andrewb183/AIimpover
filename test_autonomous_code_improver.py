from pathlib import Path
from create.autonomous_code_improver import CodeImprover, improve_workspace_files
def test_improve_file_dry_run_does_not_write(tmp_path):
    """Auto-generated docstring."""
    source = tmp_path / "sample.py"
    source.write_text("value = 1   \n\nprint(value)\n", encoding="utf-8")

    improver = CodeImprover()
    result = improver.improve_file(source, apply_all=False)

    assert result["status"] == "dry_run"
    assert source.read_text(encoding="utf-8") == "value = 1   \n\nprint(value)\n"
    assert result["changes_count"] >= 1

def test_improve_file_writes_backup_before_mutation(tmp_path):
    """Auto-generated docstring."""
    source = tmp_path / "backup_sample.py"
    source.write_text("value = 1   \n", encoding="utf-8")

    backup_dir = tmp_path / "backups"
    improver = CodeImprover()
    result = improver.improve_file(
        source,
        apply_all=True,
        git_prechange_push_enabled=False,
        backup_dir=backup_dir,
    )

    assert result["status"] == "improved"
    assert result["prechange_backup_path"]
    assert Path(result["prechange_backup_path"]).exists()
    assert backup_dir.exists()
    assert source.read_text(encoding="utf-8").endswith("\n")

def test_improve_workspace_files_honors_exclusions_and_limits(tmp_path):
    """Auto-generated docstring."""
    keep = tmp_path / "keep.py"
    skip = tmp_path / "__pycache__" / "skip.py"
    skip.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("x = 1   \n", encoding="utf-8")
    skip.write_text("y = 2   \n", encoding="utf-8")

    summary = improve_workspace_files(tmp_path, max_files=1, apply_all=False)

    assert summary["status"] == "complete"
    assert summary["workspace_root"] == str(tmp_path.resolve())
    assert summary["total_files"] == 1
    assert summary["files_improved"] == 1
    assert summary["results"][0]["file"] == str(keep.resolve())
