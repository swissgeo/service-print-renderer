import pytest

from app.helpers import dynamo_db, sqs_queue


@pytest.fixture(autouse=True)
def reset_lru_caches():
    """Clear all lru_cache singletons between tests to avoid cross-test pollution."""
    dynamo_db.get_dynamodb.cache_clear()
    sqs_queue.get_sqs_client.cache_clear()
    yield
    dynamo_db.get_dynamodb.cache_clear()
    sqs_queue.get_sqs_client.cache_clear()
