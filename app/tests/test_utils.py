import datetime

from app.helpers.utils import get_iso_8601_timestamp


def test_get_iso_8601_timestamp_format():
    ts = get_iso_8601_timestamp()
    # Should be parseable as an ISO 8601 datetime with timezone
    dt = datetime.datetime.fromisoformat(ts)
    assert dt.tzinfo is not None
