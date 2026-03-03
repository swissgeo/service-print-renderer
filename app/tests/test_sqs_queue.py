import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, ConnectTimeoutError

import pytest

from app.helpers.sqs_queue import delete_message, parse_message_body, receive_messages, send_to_dlq


@pytest.fixture
def mock_sqs_client():
    with patch("app.helpers.sqs_queue.get_sqs_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


# ---------------------------------------------------------------------------
# receive_messages
# ---------------------------------------------------------------------------


def test_receive_messages_returns_list(mock_sqs_client):
    job = {"job_id": "abc123", "status": "open"}
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}
    mock_sqs_client.receive_message.return_value = {
        "Messages": [{"Body": json.dumps(job), "ReceiptHandle": "handle-1"}]
    }

    messages = receive_messages()

    assert len(messages) == 1
    assert messages[0]["ReceiptHandle"] == "handle-1"


def test_receive_messages_empty(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}
    mock_sqs_client.receive_message.return_value = {}

    messages = receive_messages()

    assert messages == []


def test_receive_messages_requests_receive_count_attribute(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}
    mock_sqs_client.receive_message.return_value = {}

    receive_messages()

    call_kwargs = mock_sqs_client.receive_message.call_args[1]
    assert "ApproximateReceiveCount" in call_kwargs.get("AttributeNames", [])


def test_receive_messages_propagates_connect_timeout(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}
    mock_sqs_client.receive_message.side_effect = ConnectTimeoutError(
        endpoint_url="http://localhost"
    )

    with pytest.raises(ConnectTimeoutError):
        receive_messages()


def test_receive_messages_propagates_client_error(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}
    mock_sqs_client.receive_message.side_effect = ClientError(
        {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue", "Message": ""}},
        "ReceiveMessage",
    )

    with pytest.raises(ClientError):
        receive_messages()


# ---------------------------------------------------------------------------
# delete_message
# ---------------------------------------------------------------------------


def test_delete_message_calls_sqs(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}

    delete_message("some-receipt-handle")

    mock_sqs_client.delete_message.assert_called_once()


def test_delete_message_passes_receipt_handle(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}

    delete_message("my-handle-xyz")

    call_kwargs = mock_sqs_client.delete_message.call_args[1]
    assert call_kwargs["ReceiptHandle"] == "my-handle-xyz"


def test_delete_message_propagates_client_error(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}
    mock_sqs_client.delete_message.side_effect = ClientError(
        {"Error": {"Code": "ReceiptHandleIsInvalid", "Message": ""}}, "DeleteMessage"
    )

    with pytest.raises(ClientError):
        delete_message("bad-handle")


# ---------------------------------------------------------------------------
# send_to_dlq
# ---------------------------------------------------------------------------


def test_send_to_dlq_calls_send_message(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/dlq"}

    send_to_dlq('{"job_id": "bad-job"}')

    mock_sqs_client.send_message.assert_called_once()


def test_send_to_dlq_forwards_message_body(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/dlq"}
    body = '{"job_id": "bad-job", "raw": true}'

    send_to_dlq(body)

    call_kwargs = mock_sqs_client.send_message.call_args[1]
    assert call_kwargs["MessageBody"] == body


def test_send_to_dlq_propagates_client_error(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/dlq"}
    mock_sqs_client.send_message.side_effect = ClientError(
        {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue", "Message": ""}},
        "SendMessage",
    )

    with pytest.raises(ClientError):
        send_to_dlq("some body")


# ---------------------------------------------------------------------------
# parse_message_body
# ---------------------------------------------------------------------------


def test_parse_message_body():
    job = {"job_id": "281c683057b2be6fcee", "status": "open", "payload": {"foo": "bar"}}
    message = {"Body": json.dumps(job)}

    result = parse_message_body(message)

    assert result == job


def test_parse_message_body_invalid_json_raises():
    message = {"Body": "not-valid-json"}

    with pytest.raises(json.JSONDecodeError):
        parse_message_body(message)


def test_parse_message_body_returns_dict():
    message = {"Body": json.dumps({"job_id": "281c683057b2be6fcee"})}

    result = parse_message_body(message)

    assert isinstance(result, dict)
