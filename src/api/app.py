"""Optional FastAPI integration for CiteGuard."""

from __future__ import annotations

from src.orchestrator import CiteGuardAgent

from .schemas import GenerateRequest, GenerateResponse

try:
    from fastapi import FastAPI
except ImportError:  # pragma: no cover - exercised only when FastAPI is installed.
    FastAPI = None


def create_app(agent: CiteGuardAgent):  # pragma: no cover - integration surface.
    """Create a FastAPI app when the dependency is installed."""

    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install it before creating the API app.")

    app = FastAPI(title="CiteGuard API", version="0.1.0")

    @app.post("/generate")
    def generate(request: GenerateRequest) -> dict:
        result = agent.run(request.to_task())
        return GenerateResponse.from_result(result).__dict__

    return app
