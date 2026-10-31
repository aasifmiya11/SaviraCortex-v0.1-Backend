from uuid import uuid4
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.storage import FileStorage


def test_storage():
    storage = FileStorage()

    # 1. Test bucket access
    storage.client.head_bucket(Bucket=storage.bucket)
    print("B2 connection successful.")

    # 2. Choose an existing local PDF
    local_pdf = Path(r"F:\HiPPA.pdf")

    if not local_pdf.exists():
        raise FileNotFoundError(local_pdf)

    # 3. Generate a test object key
    document_id = uuid4()
    version_id = uuid4()

    storage_key = storage.build_document_version_key(
        document_id=document_id,
        version_id=version_id,
    )

    # 4. Upload
    result = storage.upload_file(
        local_path=local_pdf,
        storage_key=storage_key,
        content_type="application/pdf",
        metadata={
            "document-id": str(document_id),
            "version-id": str(version_id),
        },
    )

    print("Upload result:", result)

    # 5. Check existence
    print("Object exists:", storage.exists(storage_key))

    # 6. Retrieve metadata
    print("Object metadata:", storage.get_metadata(storage_key))

    # 7. Generate temporary download URL
    url = storage.generate_download_url(
        storage_key,
        expiration_seconds=900,
    )
    print("Temporary download URL:", url)

    # 8. Download and verify size
    downloaded_path = Path("F:/HiPPA.pdf")

    storage.download_file(
        storage_key=storage_key,
        destination=downloaded_path,
    )

    assert downloaded_path.stat().st_size == local_pdf.stat().st_size

    print("Download verification successful.")
    print("Test completed.")

    # Deliberately do not delete the uploaded test object.


if __name__ == "__main__":
    test_storage()