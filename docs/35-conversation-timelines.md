# Conversation Timelines and Time Travel

## User-visible behavior

An application conversation can contain multiple immutable timelines. Editing a user question and regenerating an assistant answer create a new timeline inside the existing conversation. They do not create a new conversation in the sidebar.

Each timeline is a complete materialized message snapshot from the beginning through its current head. A new timeline copies the prefix before the selected user turn, resumes the checkpoint immediately before that turn, and generates the edited or repeated question. The original timeline and its later turns are retained.

The previous/next control switches the selected timeline and reloads the entire message snapshot. Future messages are persisted only to the selected timeline. The selected timeline ID is carried in the chat URL and generation request.

Fork remains a separate operation: it creates a new conversation, copies the selected timeline's messages through the selected assistant answer, and copies that answer's LangGraph checkpoint into the new conversation thread.

## Persistence model

- `conversation_paths.id` is also the LangGraph thread ID for that alternate timeline.
- `conversation_paths.conversation_id` keeps every alternate timeline under the original application conversation.
- `parent_path_id` records which timeline was used as the source.
- `branch_point_message_id` is the stable user-turn key shared by all versions of that turn.
- Each assistant message stores both `checkpoint_id` and `checkpoint_thread_id`; this preserves the actual owner of older checkpoints copied into a newer timeline, so editing an earlier turn still resumes the right snapshot.
- `fork_checkpoint_id` records the checkpoint immediately before the turn; `head_checkpoint_id` advances after each generated answer.
- `conversation_messages.path_id IS NULL` denotes the legacy/root timeline. A non-null value associates a message with a complete alternate snapshot. Prefix messages are copied into the snapshot so retrieval does not depend on reconstructing a fragile ancestry chain.

## Generation invariants

1. A generation request with `path_id` must belong to the supplied conversation.
2. An explicit checkpoint must equal the selected path's stored head checkpoint.
3. Generation uses `path_id` as LangGraph `thread_id`; root generation continues using `conversation_id`.
4. User and assistant message rows are written with the same `path_id`.
5. The assistant checkpoint is read from the actual post-invocation graph state and persisted as the path head.
6. Switching paths only changes the selected snapshot; it never mutates another path's rows or checkpoint thread.

## API surface

- `POST /conversations/{id}/branches` with `action=regenerate|edit_input` creates a path in the same conversation and returns `path_id`, checkpoint and query data.
- `GET /conversations/{id}/messages?path_id=...` retrieves the complete selected snapshot. Omit `path_id` for the root timeline.
- `GET /conversations/{id}/paths?branch_point_message_id=...` lists the original base timeline followed by each generated timeline exactly once, ordered by creation time. Do not include every path's `base_path_id` as a separate version: those IDs describe ancestry and would duplicate earlier versions in a sequential regeneration chain.
- `POST /conversations/{id}/branches` with `action=fork` creates a separate conversation.
