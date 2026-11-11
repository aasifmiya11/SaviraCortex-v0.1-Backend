from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from botocore.exceptions import ClientError

from app.storage.b2_client import (
    get_b2_client,
    get_b2_bucket_name,
    get_b2_storage_prefix,
)


class FileStorage:
    """
    Backblaze B2 file storage interface.

    Stores original uploaded documents in a private B2 bucket.
    """

    def __init__(self):
        self.client = get_b2_client()
        self.bucket = get_b2_bucket_name()
        self.prefix = get_b2_storage_prefix()

    def build_document_version_key(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> str:
        """
        Generate an organization-scoped object key for a document version.
        """

        if not isinstance(organization_id, UUID):
            raise TypeError("organization_id must be a UUID.")
        if not isinstance(document_id, UUID):
            raise TypeError("document_id must be a UUID.")
        if not isinstance(version_id, UUID):
            raise TypeError("version_id must be a UUID.")

        return (
            f"{self.prefix}"
            f"organizations/{organization_id}/"
            f"documents/{document_id}/"
            f"versions/{version_id}.pdf"
        )

    def upload_file(
        self,
        local_path: str | Path,
        storage_key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Upload a local file to B2.

        Returns basic information about the uploaded object.
        """

        source = Path(local_path).expanduser()

        if not source.exists():
            raise FileNotFoundError(f"File does not exist: {source}")

        if not source.is_file():
            raise ValueError(f"Not a file: {source}")

        if not storage_key or not storage_key.strip():
            raise ValueError("Storage key cannot be empty.")

        storage_key = storage_key.lstrip("/")

        if not content_type:
            content_type, _ = mimetypes.guess_type(source.name)

        extra_args = {
            "ContentType": content_type or "application/octet-stream",
        }

        if metadata:
            extra_args["Metadata"] = metadata

        self.client.upload_file(
            Filename=str(source),
            Bucket=self.bucket,
            Key=storage_key,
            ExtraArgs=extra_args,
        )

        # Verify that the uploaded object exists and has the
        # same size as the local file.
        uploaded = self.client.head_object(
            Bucket=self.bucket,
            Key=storage_key,
        )

        local_size = source.stat().st_size
        uploaded_size = uploaded["ContentLength"]

        if local_size != uploaded_size:
            raise IOError(
                "Upload verification failed: "
                f"local size={local_size}, "
                f"remote size={uploaded_size}"
            )

        return {
            "storage_key": storage_key,
            "bucket": self.bucket,
            "size": uploaded_size,
            "content_type": uploaded.get("ContentType"),
        }

    def upload_bytes(self, content: bytes, storage_key: str, content_type: str, metadata: dict[str, str] | None = None) -> dict:
        """Upload in-memory content to the private bucket and verify its size."""
        if not content or not storage_key or not storage_key.strip() or not content_type:
            raise ValueError("Content, storage key, and content type are required.")
        key = storage_key.lstrip("/")
        arguments = {"Bucket": self.bucket, "Key": key, "Body": content, "ContentType": content_type}
        if metadata:
            arguments["Metadata"] = metadata
        self.client.put_object(**arguments)
        uploaded = self.client.head_object(Bucket=self.bucket, Key=key)
        if uploaded.get("ContentLength") != len(content):
            raise IOError("B2 upload verification failed: object size does not match.")
        return {"storage_key": key, "bucket": self.bucket, "size": uploaded["ContentLength"], "content_type": uploaded.get("ContentType")}

    def download_file(
        self,
        storage_key: str,
        destination: str | Path,
    ) -> Path:
        """
        Download an object from B2 to a local path.
        """

        if not storage_key:
            raise ValueError("Storage key cannot be empty.")

        destination = Path(destination).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)

        self.client.download_file(
            self.bucket,
            storage_key,
            str(destination),
        )

        return destination

    def download_to_fileobj(
        self,
        storage_key: str,
        file_object: BinaryIO,
    ) -> None:
        """
        Download an object directly into a binary file-like object.
        """

        self.client.download_fileobj(
            self.bucket,
            storage_key,
            file_object,
        )

    def exists(self, storage_key: str) -> bool:
        """
        Check whether an object exists in B2.

        Missing objects return False.
        Permission and connection errors are propagated.
        """

        try:
            self.client.head_object(
                Bucket=self.bucket,
                Key=storage_key,
            )
            return True

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")

            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False

            raise

    def get_metadata(self, storage_key: str) -> dict | None:
        """
        Retrieve object metadata without downloading its contents.
        """

        try:
            response = self.client.head_object(
                Bucket=self.bucket,
                Key=storage_key,
            )

            return {
                "size": response["ContentLength"],
                "content_type": response.get("ContentType"),
                "last_modified": response.get("LastModified"),
                "metadata": response.get("Metadata", {}),
            }

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")

            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return None

            raise

    def delete_file(self, storage_key: str) -> None:
        """
        Delete an object from B2.

        This method deliberately does not ask for interactive
        confirmation. The calling service controls deletion policy.
        """

        if not storage_key:
            raise ValueError("Storage key cannot be empty.")

        self.client.delete_object(
            Bucket=self.bucket,
            Key=storage_key,
        )

    def delete_file_permanently(self, storage_key: str) -> None:
        """Permanently remove every B2/S3 object version and delete marker for a key.

        A plain DeleteObject can create a delete marker in a versioned bucket
        while leaving older PDF versions billable and recoverable. Enumerate
        all exact-key versions first, then delete each version explicitly.
        """
        if not storage_key or not storage_key.strip():
            raise ValueError("Storage key cannot be empty.")

        storage_key = storage_key.lstrip("/")
        versions_to_delete: list[dict[str, str]] = []
        key_marker = None
        version_id_marker = None

        while True:
            arguments = {
                "Bucket": self.bucket,
                "Prefix": storage_key,
            }
            if key_marker:
                arguments["KeyMarker"] = key_marker
            if version_id_marker:
                arguments["VersionIdMarker"] = version_id_marker

            response = self.client.list_object_versions(**arguments)
            for version in response.get("Versions", []):
                if version.get("Key") == storage_key and version.get("VersionId") is not None:
                    versions_to_delete.append({
                        "Key": storage_key,
                        "VersionId": version["VersionId"],
                    })
            for marker in response.get("DeleteMarkers", []):
                if marker.get("Key") == storage_key and marker.get("VersionId") is not None:
                    versions_to_delete.append({
                        "Key": storage_key,
                        "VersionId": marker["VersionId"],
                    })

            if not response.get("IsTruncated"):
                break
            key_marker = response.get("NextKeyMarker")
            version_id_marker = response.get("NextVersionIdMarker")
            if not key_marker:
                raise RuntimeError("B2 version listing was truncated without a continuation key.")

        if not versions_to_delete:
            try:
                self.client.head_object(Bucket=self.bucket, Key=storage_key)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code")
                if error_code in {"404", "NoSuchKey", "NotFound"}:
                    return
                raise
            self.delete_file(storage_key)
            return

        for version in versions_to_delete:
            self.client.delete_object(
                Bucket=self.bucket,
                Key=version["Key"],
                VersionId=version["VersionId"],
            )

    def get_file_response(self, storage_key: str, range_header: str | None = None) -> dict:
        """Return a B2 object response, optionally for one HTTP byte range."""
        if not storage_key or not storage_key.strip():
            raise ValueError("Storage key cannot be empty.")

        arguments = {"Bucket": self.bucket, "Key": storage_key.lstrip("/")}
        if range_header:
            if not range_header.startswith("bytes=") or "," in range_header:
                raise ValueError("Only a single HTTP byte range is supported.")
            arguments["Range"] = range_header

        return self.client.get_object(**arguments)

    def generate_download_url(
        self,
        storage_key: str,
        expiration_seconds: int = 900,
    ) -> str:
        """
        Generate a temporary presigned download URL.

        Default expiration: 15 minutes.
        """

        if expiration_seconds <= 0:
            raise ValueError("Expiration must be greater than zero.")

        return self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": storage_key,
            },
            ExpiresIn=expiration_seconds,
        )
    def build_ingestion_staging_key(
        self, organization_id: UUID, ingestion_session_id: UUID
    ) -> str:
        if not isinstance(organization_id, UUID) or not isinstance(ingestion_session_id, UUID):
            raise TypeError("Organization and ingestion session IDs must be UUIDs.")
        return (
            f"{self.prefix}staging/organizations/{organization_id}/"
            f"document-ingestion/{ingestion_session_id}.pdf"
        )

    def copy_file(self, source_key: str, destination_key: str) -> dict:
        """Copy an already-uploaded object inside the configured private B2 bucket."""
        if not source_key or not destination_key or source_key == destination_key:
            raise ValueError("Distinct source and destination storage keys are required.")
        source_key = source_key.lstrip("/")
        destination_key = destination_key.lstrip("/")
        source = self.client.head_object(Bucket=self.bucket, Key=source_key)
        self.client.copy_object(
            Bucket=self.bucket,
            Key=destination_key,
            CopySource={"Bucket": self.bucket, "Key": source_key},
            MetadataDirective="COPY",
        )
        copied = self.client.head_object(Bucket=self.bucket, Key=destination_key)
        if copied.get("ContentLength") != source.get("ContentLength"):
            try:
                self.client.delete_object(Bucket=self.bucket, Key=destination_key)
            finally:
                raise IOError("B2 object copy verification failed.")
        return {"storage_key": destination_key, "size": copied.get("ContentLength")}
