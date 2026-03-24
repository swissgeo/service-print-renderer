import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, ConnectTimeoutError

import pytest

from app.helpers.sqs_queue import (
    delete_message,
    parse_message_body,
    receive_messages,
    send_to_dlq,
)


@pytest.fixture
def mock_sqs_client():
    with patch("app.helpers.sqs_queue.get_sqs_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


def test_receive_messages_returns_list(mock_sqs_client):
    job = {"job_id": "4a80ad23a0d62b4102", "status": "open"}
    queue_url = "http://localhost/queue"
    mock_sqs_client.receive_message.return_value = {
        "Messages": [{"Body": json.dumps(job), "ReceiptHandle": "handle-1"}]
    }

    messages = receive_messages(queue_url)

    assert len(messages) == 1
    assert messages[0]["ReceiptHandle"] == "handle-1"


def test_receive_messages_empty(mock_sqs_client):
    queue_url = "http://localhost/queue"
    mock_sqs_client.receive_message.return_value = {}

    messages = receive_messages(queue_url)

    assert messages == []


def test_receive_messages_requests_receive_count_attribute(mock_sqs_client):
    queue_url = "http://localhost/queue"
    mock_sqs_client.receive_message.return_value = {}

    receive_messages(queue_url)

    call_kwargs = mock_sqs_client.receive_message.call_args[1]
    assert "ApproximateReceiveCount" in call_kwargs.get("AttributeNames", [])


def test_receive_messages_propagates_connect_timeout(mock_sqs_client):
    queue_url = "http://localhost/queue"
    mock_sqs_client.receive_message.side_effect = ConnectTimeoutError(
        endpoint_url="http://localhost"
    )

    with pytest.raises(ConnectTimeoutError):
        receive_messages(queue_url)


def test_receive_messages_propagates_client_error(mock_sqs_client):
    queue_url = "http://localhost/queue"
    mock_sqs_client.receive_message.side_effect = ClientError(
        {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue", "Message": ""}},
        "ReceiveMessage",
    )

    with pytest.raises(ClientError):
        receive_messages(queue_url)


def test_delete_message(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}

    delete_message("4a80ad23a0d62b4102")

    mock_sqs_client.delete_message.assert_called_once_with(
        QueueUrl="http://localhost/queue",
        ReceiptHandle="4a80ad23a0d62b4102",
    )


def test_delete_message_propagates_client_error(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}
    mock_sqs_client.delete_message.side_effect = ClientError(
        {"Error": {"Code": "ReceiptHandleIsInvalid", "Message": ""}}, "DeleteMessage"
    )

    with pytest.raises(ClientError):
        delete_message("bad-handle")


def test_send_to_dlq_calls_send_message(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/dlq"}
    body = '{"job_id": "bad-job", "raw": true}'

    send_to_dlq(body)

    mock_sqs_client.send_message.assert_called_once_with(
        QueueUrl="http://localhost/dlq",
        MessageBody=body,
    )


def test_send_to_dlq_propagates_client_error(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/dlq"}
    mock_sqs_client.send_message.side_effect = ClientError(
        {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue", "Message": ""}},
        "SendMessage",
    )

    with pytest.raises(ClientError):
        send_to_dlq("some body")


def test_parse_message_body():
    job = {"job_id": "281c683057b2be6fcee", "status": "open", "payload": {"format": "a4"}}
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
