import datetime

from app.helpers.utils import get_iso_8601_timestamp, touch_probe_file

# ---------------------------------------------------------------------------
# get_iso_8601_timestamp
# ---------------------------------------------------------------------------


def test_get_iso_8601_timestamp_format():
    ts = get_iso_8601_timestamp()
    # Should be parseable as an ISO 8601 datetime with timezone
    dt = datetime.datetime.fromisoformat(ts)
    assert dt.tzinfo is not None


def test_get_iso_8601_timestamp_is_utc():
    ts = get_iso_8601_timestamp()
    dt = datetime.datetime.fromisoformat(ts)
    assert dt.utcoffset() == datetime.timedelta(0)


def test_get_iso_8601_timestamp_is_recent():
    ts = get_iso_8601_timestamp()
    dt = datetime.datetime.fromisoformat(ts)
    now = datetime.datetime.now(datetime.UTC)
    assert abs((now - dt).total_seconds()) < 5


# ---------------------------------------------------------------------------
# touch_probe_file
# ---------------------------------------------------------------------------


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
    assert probe.exists()
