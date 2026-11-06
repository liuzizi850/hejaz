from pathlib import Path

import pytest

from apps.code_monitor.batching import MAX_BATCH_CHARS, split_into_batches
from apps.code_monitor.extract import render_batch


def test_default_budget_is_60000():
    assert MAX_BATCH_CHARS == 60000


def test_packs_small_files_until_budget(tmp_path: Path):
    one = tmp_path / "a.js"
    two = tmp_path / "b.js"
    one.write_text("a" * 30, encoding="utf-8")
    two.write_text("b" * 30, encoding="utf-8")
    batches = split_into_batches([one, two], tmp_path, max_chars=80)
    assert len(batches) == 1
    assert [chunk.source_file for chunk in batches[0]] == ["a.js", "b.js"]


def test_splits_a_long_file_without_dropping_characters(tmp_path: Path):
    path = tmp_path / "long.js"
    text = "\n".join(f"line-{i}" for i in range(20))
    path.write_text(text, encoding="utf-8")
    batches = split_into_batches([path], tmp_path, max_chars=40)
    joined = "".join(chunk.text for batch in batches for chunk in batch)
    assert joined == text
    assert all(len(chunk.text) <= 40 for batch in batches for chunk in batch)
    assert all(chunk.source_file == "long.js" for batch in batches for chunk in batch)


def test_splits_a_single_line_longer_than_budget(tmp_path: Path):
    path = tmp_path / "wide.js"
    path.write_text("z" * 25, encoding="utf-8")
    batches = split_into_batches([path], tmp_path, max_chars=10)
    joined = "".join(chunk.text for batch in batches for chunk in batch)
    assert joined == "z" * 25
    assert all(len(chunk.text) <= 10 for batch in batches for chunk in batch)


def test_several_small_files_stay_within_rendered_budget(tmp_path: Path):
    files = []
    for index in range(60):
        path = tmp_path / f"f{index:02d}.js"
        path.write_text("x" * 1000, encoding="utf-8")
        files.append(path)
    batches = split_into_batches(files, tmp_path)
    assert len(batches) >= 2
    assert sum(len(batch) for batch in batches) == 60
    for batch in batches:
        assert len(render_batch(batch)) <= 60000
    joined = "".join(chunk.text for batch in batches for chunk in batch)
    assert joined == "x" * 60000


def test_non_positive_budget_is_rejected(tmp_path: Path):
    path = tmp_path / "a.js"
    path.write_text("abc", encoding="utf-8")
    with pytest.raises(ValueError):
        split_into_batches([path], tmp_path, max_chars=0)
    with pytest.raises(ValueError):
        split_into_batches([path], tmp_path, max_chars=-5)
