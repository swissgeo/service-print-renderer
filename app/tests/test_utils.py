import datetime
import errno
from pathlib import Path

import pytest

from app.helpers.utils import ensure_writable_dir, get_iso_8601_timestamp, touch_probe_file


def test_get_iso_8601_timestamp_format():
    ts = get_iso_8601_timestamp()
    # Should be parseable as an ISO 8601 datetime with timezone
    dt = datetime.datetime.fromisoformat(ts)
    assert dt.tzinfo is not None


def test_get_iso_8601_timestamp_is_utc():
    ts = get_iso_8601_timestamp()
    dt = datetime.datetime.fromisoformat(ts)
    assert dt.utcoffset() == datetime.timedelta(0)


def test_touch_probe_file_creates_file(tmp_path):
    probe = tmp_path / "startup_probe"
    touch_probe_file(str(probe))
    assert probe.exists()


def test_touch_probe_file_empty_string_is_noop(tmp_path):
    touch_probe_file("")
    # Nothing should be created; just check no exception is raised
    assert list(tmp_path.iterdir()) == []


def test_touch_probe_file_touches_existing_file(tmp_path):
    probe = tmp_path / "probe"
    probe.write_text("old")
    touch_probe_file(str(probe))
    assert probe.read_text() == "old"


def test_ensure_writable_dir_creates_missing_directory(tmp_path):
    scratch = tmp_path / "scratch" / "nested"
    ensure_writable_dir(str(scratch))
    assert scratch.is_dir()


def test_ensure_writable_dir_leaves_no_leftover_file(tmp_path):
    ensure_writable_dir(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_ensure_writable_dir_raises_on_read_only_filesystem(tmp_path, monkeypatch):
    def _read_only_touch(*_args, **_kwargs) -> None:
        raise OSError(errno.EROFS, "Read-only file system")

    monkeypatch.setattr(Path, "touch", _read_only_touch)
    with pytest.raises(RuntimeError, match="not writable"):
        ensure_writable_dir(str(tmp_path))


def test_ensure_writable_dir_raises_when_path_is_a_file(tmp_path):
    not_a_dir = tmp_path / "regular_file"
    not_a_dir.write_text("")
    with pytest.raises(RuntimeError, match="not writable"):
        ensure_writable_dir(str(not_a_dir / "scratch"))
