from importlib import import_module

__all__ = [
    "DocumentIngestionError",
    "DocumentIngestionService",
    "IngestionResult",
    "DocumentIngestionWorkflowError",
    "DocumentIngestionWorkflowService",
]


def __getattr__(name: str):
    if name in {"DocumentIngestionError", "DocumentIngestionService", "IngestionResult"}:
        module = import_module(".ingestion_service", __name__)
        return getattr(module, name)
    if name in {"DocumentIngestionWorkflowError", "DocumentIngestionWorkflowService"}:
        module = import_module(".workflow_service", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
