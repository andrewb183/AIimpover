from pathlib import Path
from create.skynetv2_agent import (
    _apply_transforms_for_file,
    _rewrite_duplicate_blank_lines,
    _rewrite_trailing_whitespace,
)

def test_rewrite_trailing_whitespace_strips_line_ends():
    """Auto-generated docstring."""
    source = "a = 1   \nline2\t\nline3\n"
    updated, changed = _rewrite_trailing_whitespace(source)
    assert changed is True
    assert updated == "a = 1\nline2\nline3\n"

def test_rewrite_duplicate_blank_lines_compacts_runs():
    """Auto-generated docstring."""
    source = "x\n\n\n\n\ny\n"
    updated, changed = _rewrite_duplicate_blank_lines(source)
    assert changed is True
    assert updated == "x\n\ny\n"

def test_apply_transforms_for_python_includes_new_conservative_rules():
    """Auto-generated docstring."""
    source = "value = 1   \n\n\nprint(value)\n"
    updated, transforms = _apply_transforms_for_file(Path("example.py"), source)
    assert "rewrite_trailing_whitespace" in transforms
    assert "rewrite_duplicate_blank_lines" in transforms
    assert updated == "value = 1\n\nprint(value)\n"

def test_apply_transforms_for_markdown_includes_text_safe_rules():
    """Auto-generated docstring."""
    source = "# Title   \n\n\n\nBody\n"
    updated, transforms = _apply_transforms_for_file(Path("notes.md"), source)
    assert "rewrite_trailing_whitespace" in transforms
    assert "rewrite_duplicate_blank_lines" in transforms
    assert updated == "# Title\n\nBody\n"
