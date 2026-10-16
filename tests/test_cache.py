import os
import stat
import time

from awsce.cache import FileCache


def test_round_trip_and_expiry(tmp_path, monkeypatch):
    cache = FileCache(tmp_path)
    key = FileCache.make_key("costs", profile="a", start="2026-01-01")
    cache.set(key, {"total": 1.5})
    assert cache.get(key, max_age_hours=1) == {"total": 1.5}

    future = time.time() + 2 * 3600
    monkeypatch.setattr(time, "time", lambda: future)
    assert cache.get(key, max_age_hours=1) is None


def test_files_are_private(tmp_path):
    cache = FileCache(tmp_path / "c")
    key = FileCache.make_key("costs")
    cache.set(key, [])
    assert stat.S_IMODE(os.stat(tmp_path / "c" / f"{key}.json").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "c").st_mode) == 0o700


def test_key_depends_on_params():
    assert FileCache.make_key("costs", a=1) != FileCache.make_key("costs", a=2)
    assert FileCache.make_key("costs", a=1, b=2) == FileCache.make_key("costs", b=2, a=1)


def test_clear_older_than(tmp_path, monkeypatch):
    cache = FileCache(tmp_path)
    cache.set("old-1", 1)
    later = time.time() + 10 * 86400
    monkeypatch.setattr(time, "time", lambda: later)
    cache.set("new-1", 2)
    assert cache.clear(older_than_days=5) == 1
    assert [e.key for e in cache.entries()] == ["new-1"]
    assert cache.clear() == 1


def test_missing_or_corrupt_file(tmp_path):
    cache = FileCache(tmp_path)
    assert cache.get("nope", 1) is None
    (tmp_path / "bad.json").write_text("{not json")
    assert cache.get("bad", 1) is None
