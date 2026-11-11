# Image understanding in chat

**Status:** Implemented in the local backend/frontend; automated and provider smoke checks pass. Browser end-to-end verification remains.
**Scope:** Normal SaviraCortex chat input; this is image understanding, not image generation.

## User-facing behavior

A chat turn may contain text, images, or both. Image-only turns receive a neutral default instruction so the model can analyze the attachments without requiring typed text. The composer supports the attachment picker, clipboard screenshots (Ctrl+V), and drag-and-drop of image files.

Initial limits:
- Up to four images per message.
- PNG, JPEG/JPG, and WEBP.
- 4 MiB maximum per image and 8 MiB combined per message.
- Unsupported file types and size violations are rejected before generation.

## Storage and authorization

New image bytes are uploaded by the backend to the existing private Backblaze B2 bucket. Object keys are scoped to the organization and owning user:

    organizations/{organization_id}/users/{user_id}/conversation-images/{request_id}/{index}.{extension}

Conversation message metadata stores only the object key, content type, original display name, and byte size. The LangGraph human message stores the same references in additional_kwargs.image_attachments; it does not put image bytes or expiring URLs into checkpoints.

The conversation message endpoint verifies conversation ownership and only creates a five-minute presigned URL for an object key under the current organization/user prefix. Reopening or refreshing conversation history creates fresh URLs. The bucket itself remains private.

Existing stored image references may be reused when editing a user message. The backend verifies that the object key belongs to the same organization and user and that the object exists with the expected MIME type.

## Model integration

The backend includes an automatic ModelRouter inside the generation agent:
- Text-only turns use the existing OPENAI_MODEL (currently GLM-5).
- Turns containing images use OPENAI_VISION_MODEL (currently writer.palmyra-vision-7b).
- Both clients reuse the verified Bedrock Mantle endpoint and credentials. Text-only traffic is not moved to the smaller vision model.

Image references are resolved from B2 at generation time and supplied as standard image_url content blocks alongside the user text. The most recent four images in conversation history are hydrated so follow-up questions can refer to recent attachments. The vision route compacts older conversation history and retrieved evidence because Palmyra Vision 7B has a 4K-token context window; its output-token cap is configured separately.

The Bedrock Palmyra Vision chat endpoint enforces alternating user/assistant turns. The vision prompt therefore embeds the trusted grounding/security instructions at the start of the current user turn (rather than sending a separate system role), and folds a trailing user history turn into that current turn when needed. Existing assistant turns and recent image context are retained. The text-only GLM-5 route continues to use the standard system/user prompt.

The current backend/.env enables OPENAI_VISION_ENABLED=true and sets OPENAI_VISION_MODEL=writer.palmyra-vision-7b after a live text-plus-four-images streaming request succeeded using the configured Bedrock credentials. To verify another environment, run:

    python scripts/check_vision_model_access.py

The script tests text access and then sends a generated four-image request through streaming Chat Completions. If vision is disabled or unavailable, the API returns a clear message asking the user to use text only or contact an administrator. It never sends images to GLM-5 or silently discards them.

## Grounding and security

- Company-specific claims continue to require retrieved company-document evidence.
- General visual tasks (reading an equation, describing a scene, reading text, or explaining an object) may use the user-provided image as direct evidence even when no company documents are retrieved.
- Image contents and text visible inside images are untrusted input. The generation prompt explicitly forbids following embedded instructions that attempt to override system rules or reveal secrets.
- The API Gateway's JEV image input is a separate guardrail workflow; normal chat vision input is handled by the generation model. This implementation does not route chat images through the JEV image classifier.
- Images are not exposed through public object URLs. Do not log data URLs or image bytes.

## Persistence and time travel

Attachment metadata is stored on the user message, while object bytes remain in B2. The checkpoint records stable object references, allowing later turns and timeline branches to rehydrate recent images. Message history returns a temporary URL for rendering; URLs are not persisted as durable message data.

## Remaining verification

The local implementation has passed the model-routing/image-attachment tests, the existing generation/endpoint/persistence regression suites, and a live streamed GenerationAgent test with four images. The provider smoke script also verified text access and four-image streaming. Before enabling this feature in another deployment:
1. Verify the configured provider/model supports image input and set OPENAI_VISION_ENABLED=true.
2. Verify B2 credentials, private bucket access, upload, download, and presigned URL generation.
3. Exercise text-only, image-only, and image-plus-text turns with PNG, JPEG, and WEBP.
4. Verify clipboard paste, drag-and-drop, four-image limit, size limits, message reload, edit, and regeneration.
5. Verify behavior when the model lacks vision support or returns a provider error.
6. Run the backend integration tests and a browser-level end-to-end test (still pending locally).
