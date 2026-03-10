from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

import pytest

from app.helpers.s3 import upload_pdf


@pytest.fixture
def mock_s3_client():
    with patch("app.helpers.s3.get_s3_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


def test_upload_pdf_returns_presigned_url(mock_s3_client, tmp_path):
    pdf = tmp_path / "test281c683057b2be6fcee.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake map")
    mock_s3_client.generate_presigned_url.return_value = "https://presigned"

    result = upload_pdf("job-281c683057b2be6fcee", pdf)

    assert result == "https://presigned"


def test_upload_pdf_uses_job_id_as_key(mock_s3_client, tmp_path):
    pdf = tmp_path / "test281c683057b2be6fcee.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake map")
    mock_s3_client.generate_presigned_url.return_value = "https://presigned"

    upload_pdf("my-job-id", pdf)

    _, positional, _ = mock_s3_client.upload_file.mock_calls[0]
    assert positional[2] == "my-job-id.pdf"


def test_upload_pdf_sets_pdf_content_type(mock_s3_client, tmp_path):
    pdf = tmp_path / "test281c683057b2be6fcee.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake map")
    mock_s3_client.generate_presigned_url.return_value = "https://presigned"

    upload_pdf("job-abc", pdf)

    call_kwargs = mock_s3_client.upload_file.call_args[1]
    assert call_kwargs["ExtraArgs"]["ContentType"] == "application/pdf"


def test_upload_pdf_generates_presigned_url_for_correct_key(mock_s3_client, tmp_path):
    pdf = tmp_path / "test281c683057b2be6fcee.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake map")
    mock_s3_client.generate_presigned_url.return_value = "https://presigned"

    upload_pdf("job-test281c683057b2be6fcee", pdf)

    presign_call = mock_s3_client.generate_presigned_url.call_args
    assert presign_call[0][0] == "get_object"
    assert presign_call[1]["Params"]["Key"] == "job-test281c683057b2be6fcee.pdf"


def test_upload_pdf_propagates_client_error(mock_s3_client, tmp_path):
    pdf = tmp_path / "test281c683057b2be6fcee.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake map")
    mock_s3_client.upload_file.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": ""}}, "upload_file"
    )

    with pytest.raises(ClientError):
        upload_pdf("job-err", pdf)
