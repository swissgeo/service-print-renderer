from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

import pytest

from app.config.settings import LOCALSTACK_ENDPOINT, PRINT_PDF_BASE_URL, S3_BUCKET_NAME
from app.helpers.s3 import upload_pdf


@pytest.fixture
def mock_s3_client():
    with patch("app.helpers.s3.get_s3_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


@pytest.mark.usefixtures("mock_s3_client")
def test_upload_pdf_returns_s3_url(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")

    with patch("app.helpers.s3.AWS_LOCAL", new=False):
        result = upload_pdf("job-123", pdf)

    assert result == f"{PRINT_PDF_BASE_URL}/job-123.pdf"


@pytest.mark.usefixtures("mock_s3_client")
def test_upload_pdf_returns_localstack_url(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")

    with patch("app.helpers.s3.AWS_LOCAL", new=True):
        result = upload_pdf("job-123", pdf)

    assert result == f"{LOCALSTACK_ENDPOINT}/{S3_BUCKET_NAME}/job-123.pdf"


def test_upload_pdf_propagates_client_error(mock_s3_client, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    mock_s3_client.upload_file.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": ""}}, "upload_file"
    )

    with pytest.raises(ClientError):
        upload_pdf("job-err", pdf)
