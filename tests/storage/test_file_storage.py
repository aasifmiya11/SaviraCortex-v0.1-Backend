from app.storage.file_storage import FileStorage


class FakeS3Client:
    def __init__(self):
        self.deleted = []
        self.list_calls = []

    def list_object_versions(self, **kwargs):
        self.list_calls.append(kwargs)
        return {
            "Versions": [
                {"Key": "docs/policy.pdf", "VersionId": "version-1"},
                {"Key": "docs/policy.pdf", "VersionId": "version-2"},
                {"Key": "docs/policy-old.pdf", "VersionId": "other-key"},
            ],
            "DeleteMarkers": [
                {"Key": "docs/policy.pdf", "VersionId": "delete-marker"},
            ],
            "IsTruncated": False,
        }

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)


def test_delete_file_permanently_removes_all_exact_key_versions_and_markers():
    storage = FileStorage.__new__(FileStorage)
    storage.client = FakeS3Client()
    storage.bucket = "private-documents"

    storage.delete_file_permanently("/docs/policy.pdf")


    assert storage.client.list_calls == [
        {"Bucket": "private-documents", "Prefix": "docs/policy.pdf"}
    ]
    assert storage.client.deleted == [
        {"Bucket": "private-documents", "Key": "docs/policy.pdf", "VersionId": "version-1"},
        {"Bucket": "private-documents", "Key": "docs/policy.pdf", "VersionId": "version-2"},
        {"Bucket": "private-documents", "Key": "docs/policy.pdf", "VersionId": "delete-marker"},
    ]
