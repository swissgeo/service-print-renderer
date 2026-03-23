from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

import pytest

from app.config.settings import S3_BUCKET_NAME
from app.helpers.s3 import upload_pdf


@pytest.fixture
def mock_s3_client():
    with patch("app.helpers.s3.get_s3_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


def test_upload_pdf_success(mock_s3_client, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")

    result = upload_pdf("job-123", pdf)

    assert result.endswith("/api/print/pdf/job-123.pdf")
    mock_s3_client.upload_file.assert_called_once_with(
        str(pdf),
        S3_BUCKET_NAME,
        "job-123.pdf",
        ExtraArgs={"ContentType": "application/pdf"},
    )


def test_upload_pdf_propagates_client_error(mock_s3_client, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    mock_s3_client.upload_file.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": ""}}, "upload_file"
    )

    with pytest.raises(ClientError):
        upload_pdf("job-err", pdf)
