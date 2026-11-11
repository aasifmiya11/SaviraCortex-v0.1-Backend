from __future__ import annotations

import base64
import binascii
import re
from pathlib import PurePath
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.schemas.v1.generation import ImageAttachmentInput
from app.storage.file_storage import FileStorage

_DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$", re.I)
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_ALLOWED = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _validate_image_bytes(content: bytes, content_type: str) -> None:
    valid = (
        content.startswith(b"\x89PNG\r\n\x1a\n") if content_type == "image/png"
        else content.startswith(b"\xff\xd8\xff") if content_type == "image/jpeg"
        else content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    )
    if not valid:
        raise ValueError("The uploaded file contents do not match the declared image format.")


def _read_object(storage: FileStorage, storage_key: str) -> bytes:
    response = storage.get_file_response(storage_key)
    body = response["Body"]
    try:
        return body.read()
    finally:
        body.close()


def prepare_image_attachments(
    images: list[ImageAttachmentInput],
    *,
    organization_id: UUID,
    user_id: UUID,
    request_id: UUID,
) -> list[dict[str, Any]]:
    """Validate, privately store, and return metadata for this user's chat images."""
    if not images:
        return []
    if not settings.OPENAI_VISION_ENABLED:
        raise ValueError(
            "The currently configured model does not support image input. "
            "Please switch to a vision-capable model or send a text-only message."
        )
    if len(images) > 4:
        raise ValueError("You can attach up to four images per message.")

    storage = FileStorage()
    owner_prefix = (
        f"{storage.prefix}organizations/{organization_id}/users/{user_id}/conversation-images/"
    )
    total_bytes = 0
    prepared: list[tuple[str, str, str, bytes, bool]] = []

    # Validate the complete batch before writing any object to B2.
    for index, image in enumerate(images):
        name = PurePath(image.name.replace("\\", "/")).name[:255] or "image"
        if image.data_url:
            match = _DATA_URL.fullmatch(image.data_url.strip())
            if not match:
                raise ValueError("Each attachment must be a valid PNG, JPEG, or WebP image.")
            content_type, encoded = match.groups()
            content_type = content_type.lower()
            if content_type != image.content_type:
                raise ValueError("The image MIME type does not match its attachment metadata.")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("An image attachment contains invalid encoded data.") from exc
            if not content:
                raise ValueError("An image attachment is empty.")
            if len(content) > _MAX_IMAGE_BYTES:
                raise ValueError("Each image must be 4 MiB or smaller.")
            _validate_image_bytes(content, content_type)
            extension = _ALLOWED[content_type]
            storage_key = f"{owner_prefix}{request_id}/{index}.{extension}"
            is_new = True
        else:
            storage_key = image.storage_key or ""
            if not storage_key.startswith(owner_prefix):
                raise ValueError("An attached image is not owned by the current user.")
            remote = storage.get_metadata(storage_key)
            if not remote or remote.get("content_type") != image.content_type:
                raise ValueError("A previously attached image is no longer available.")
            if int(remote.get("size") or 0) > _MAX_IMAGE_BYTES:
                raise ValueError("Each image must be 4 MiB or smaller.")
            content = _read_object(storage, storage_key)
            _validate_image_bytes(content, image.content_type)
            is_new = False

        total_bytes += len(content)
        if total_bytes > _MAX_TOTAL_BYTES:
            raise ValueError("The combined image size must be 8 MiB or smaller.")
        prepared.append((name, image.content_type, storage_key, content, is_new))

    stored: list[dict[str, Any]] = []
    uploaded_keys: list[str] = []
    try:
        for name, content_type, storage_key, content, is_new in prepared:
            if is_new:
                storage.upload_bytes(
                    content,
                    storage_key,
                    content_type,
                    metadata={"owner_id": str(user_id), "organization_id": str(organization_id)},
                )
                uploaded_keys.append(storage_key)
            stored.append({
                "name": name,
                "content_type": content_type,
                "storage_key": storage_key,
                "size": len(content),
            })
    except Exception:
        for storage_key in uploaded_keys:
            try:
                storage.delete_file(storage_key)
            except Exception:
                pass
        raise

    return stored


def hydrate_image_history(messages: list[Any], *, max_images: int = 4) -> list[Any]:
    """Replace recent image-reference messages with provider-ready multimodal messages."""
    image_count = 0
    selected: dict[int, list[dict[str, Any]]] = {}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        refs = (getattr(message, "additional_kwargs", None) or {}).get("image_attachments") or []
        if not refs:
            continue
        available = max_images - image_count
        if available <= 0:
            break
        chosen = refs[-available:]
        selected[index] = chosen
        image_count += len(chosen)

    if not selected:
        return messages

    storage = FileStorage()
    hydrated = list(messages)
    for index, refs in selected.items():
        message = messages[index]
        blocks: list[dict[str, Any]] = []
        if isinstance(message.content, str) and message.content:
            blocks.append({"type": "text", "text": message.content})
        for ref in refs:
            content = _read_object(storage, ref["storage_key"])
            content_type = ref["content_type"]
            data_url = f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
            blocks.append({"type": "image_url", "image_url": {"url": data_url}})
        hydrated[index] = HumanMessage(
            id=getattr(message, "id", None),
            content=blocks,
            additional_kwargs=getattr(message, "additional_kwargs", {}) or {},
        )
    return hydrated
