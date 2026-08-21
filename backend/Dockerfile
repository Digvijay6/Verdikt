# Python 3.12 rather than latest: livekit-agents and its audio dependencies are
# not reliably wheel-packaged for 3.13+ yet, and a hackathon is the wrong place
# to be building native extensions from source.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so code edits don't invalidate the install layer.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir \
      fastapi uvicorn[standard] "pydantic[email]" pydantic-settings pyjwt \
      supabase google-genai google-adk resend python-multipart

COPY . .

# llm/ lives at the repo root, one level above backend/, and is mounted there
# by compose. shared/llm.py resolves it relative to this file.

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
