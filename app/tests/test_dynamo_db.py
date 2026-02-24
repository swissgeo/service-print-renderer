from unittest.mock import MagicMock, patch

import pytest

from app.helpers.dynamo_db import get_print_job, update_job_status


@pytest.fixture
def mock_table():
    with patch("app.helpers.dynamo_db.get_dynamodb_table") as mock_get:
        table = MagicMock()
        mock_get.return_value = table
        yield table


def test_get_print_job_found(mock_table):
    job = {"job_id": "abc123", "status": "open"}
    mock_table.get_item.return_value = {"Item": job}

    result = get_print_job("abc123")

    assert result == job
    mock_table.get_item.assert_called_once_with(Key={"job_id": "abc123"})


def test_get_print_job_not_found(mock_table):
    mock_table.get_item.return_value = {}

    result = get_print_job("missing")

    assert result is None


def test_update_job_status_processing(mock_table):
    update_job_status(
        "abc123", "processing", started_timestamp_iso_8601="2024-01-01T00:00:00+00:00"
    )

    mock_table.update_item.assert_called_once()
    call_kwargs = mock_table.update_item.call_args[1]
    assert call_kwargs["Key"] == {"job_id": "abc123"}
    assert ":val_status" in call_kwargs["ExpressionAttributeValues"]
    assert call_kwargs["ExpressionAttributeValues"][":val_status"] == "processing"


def test_update_job_status_done(mock_table):
    update_job_status(
        "abc123",
        "done",
        finished_timestamp_iso_8601="2024-01-01T00:05:00+00:00",
        pdf_url="s3://bucket/abc123.pdf",
    )

    mock_table.update_item.assert_called_once()
    call_kwargs = mock_table.update_item.call_args[1]
    assert call_kwargs["ExpressionAttributeValues"][":val_status"] == "done"
    assert ":val_pdf_url" in call_kwargs["ExpressionAttributeValues"]
