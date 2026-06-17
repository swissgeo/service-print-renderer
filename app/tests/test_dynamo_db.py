from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

import pytest

from app.helpers.dynamo_db import get_print_job, update_job_status


@pytest.fixture
def mock_table():
    with patch("app.helpers.dynamo_db.get_dynamodb_table") as mock_get:
        table = MagicMock()
        mock_get.return_value = table
        yield table


def test_get_print_job_found(mock_table):
    job = {"job_id": "4a80ad23a0d62b4102", "status": "open"}
    mock_table.get_item.return_value = {"Item": job}

    result = get_print_job("4a80ad23a0d62b4102")

    assert result == job
    mock_table.get_item.assert_called_once_with(Key={"job_id": "4a80ad23a0d62b4102"})


def test_get_print_job_not_found(mock_table):
    mock_table.get_item.return_value = {}

    result = get_print_job("missing")

    assert result is None


def test_get_print_job_propagates_connect_timeout(mock_table):
    mock_table.get_item.side_effect = ConnectTimeoutError(endpoint_url="http://localhost")

    with pytest.raises(ConnectTimeoutError):
        get_print_job("4a80ad23a0d62b4102")


def test_get_print_job_propagates_read_timeout(mock_table):
    mock_table.get_item.side_effect = ReadTimeoutError(endpoint_url="http://localhost")

    with pytest.raises(ReadTimeoutError):
        get_print_job("4a80ad23a0d62b4102")


def test_get_print_job_propagates_client_error(mock_table):
    mock_table.get_item.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": ""}}, "GetItem"
    )

    with pytest.raises(ClientError):
        get_print_job("4a80ad23a0d62b4102")


def test_update_job_status_processing(mock_table):
    update_job_status(
        "4a80ad23a0d62b4102", "processing", started_timestamp_iso_8601="2024-01-01T00:00:00+00:00"
    )

    mock_table.update_item.assert_called_once()
    call_kwargs = mock_table.update_item.call_args[1]
    assert call_kwargs["Key"] == {"job_id": "4a80ad23a0d62b4102"}
    assert ":val_status" in call_kwargs["ExpressionAttributeValues"]
    assert call_kwargs["ExpressionAttributeValues"][":val_status"] == "processing"


def test_update_job_status_done(mock_table):
    update_job_status(
        "4a80ad23a0d62b4102",
        "done",
        finished_timestamp_iso_8601="2024-01-01T00:05:00+00:00",
        message="Print completed",
    )

    mock_table.update_item.assert_called_once()
    call_kwargs = mock_table.update_item.call_args[1]
    assert call_kwargs["ExpressionAttributeValues"][":val_status"] == "done"
    assert ":val_message" in call_kwargs["ExpressionAttributeValues"]


def test_update_job_status_uses_correct_key(mock_table):
    update_job_status("job-xyz", "started")

    call_kwargs = mock_table.update_item.call_args[1]
    assert call_kwargs["Key"] == {"job_id": "job-xyz"}


def test_update_job_status_expression_attribute_names_aliased(mock_table):
    update_job_status("job-1", "error", message="Internal error")

    names = mock_table.update_item.call_args[1]["ExpressionAttributeNames"]
    assert names.get("#attr_status") == "status"
    assert names.get("#attr_message") == "message"


def test_update_job_status_update_expression_contains_all_fields(mock_table):
    update_job_status(
        "job-1",
        "finished",
        finished_timestamp_iso_8601="2024-01-01T00:05:00+00:00",
        message="Print completed",
    )

    expr = mock_table.update_item.call_args[1]["UpdateExpression"]
    assert "SET" in expr
    assert "#attr_status" in expr
    assert "#attr_finished_timestamp_iso_8601" in expr
    assert "#attr_message" in expr


def test_update_job_status_all_extra_values_present(mock_table):
    update_job_status(
        "job-1",
        "error",
        finished_timestamp_iso_8601="2024-01-01T00:05:00+00:00",
        message="Something went wrong",
    )

    values = mock_table.update_item.call_args[1]["ExpressionAttributeValues"]
    assert values[":val_status"] == "error"
    assert values[":val_finished_timestamp_iso_8601"] == "2024-01-01T00:05:00+00:00"
    assert values[":val_message"] == "Something went wrong"


def test_update_job_status_propagates_connect_timeout(mock_table):
    mock_table.update_item.side_effect = ConnectTimeoutError(endpoint_url="http://localhost")

    with pytest.raises(ConnectTimeoutError):
        update_job_status("job-1", "error")


def test_update_job_status_propagates_read_timeout(mock_table):
    mock_table.update_item.side_effect = ReadTimeoutError(endpoint_url="http://localhost")

    with pytest.raises(ReadTimeoutError):
        update_job_status("job-1", "error")


def test_update_job_status_propagates_client_error(mock_table):
    mock_table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": ""}}, "UpdateItem"
    )

    with pytest.raises(ClientError):
        update_job_status("job-1", "error")
