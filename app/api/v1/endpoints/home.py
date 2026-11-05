from fastapi import APIRouter

router = APIRouter()


@router.get("/", tags=["Home"], summary="API home")
def api_home() -> dict[str, str]:
    return {
        "service": "SaviraCortex API",
        "version": "v1",
        "status": "running",
    }
