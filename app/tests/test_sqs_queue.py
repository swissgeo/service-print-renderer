import json
from unittest.mock import MagicMock, patch

import pytest

from app.helpers.sqs_queue import delete_message, parse_message_body, receive_messages


@pytest.fixture
def mock_sqs_client():
    with patch("app.helpers.sqs_queue.get_sqs_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


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


def test_delete_message_calls_sqs(mock_sqs_client):
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "http://localhost/queue"}

    delete_message("some-receipt-handle")

    mock_sqs_client.delete_message.assert_called_once()


def test_parse_message_body():
    job = {"job_id": "abc", "status": "open", "payload": {"foo": "bar"}}
    message = {"Body": json.dumps(job)}

    result = parse_message_body(message)

    assert result == job
