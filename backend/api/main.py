"""FastAPI app.

Run: uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
OpenAPI: http://localhost:8000/openapi.json  <- frontend types generate from this
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config import get_settings

from .routers import insights, intake, interview

app = FastAPI(
    title="Verdikt API",
    version="0.1.0",
    description="AI recruiter — intake, screening, interview, insights.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intake.router)
app.include_router(interview.router)
app.include_router(insights.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
