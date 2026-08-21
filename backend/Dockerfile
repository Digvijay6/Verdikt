# syntax=docker/dockerfile:1

# 3.12, matching pyproject's requires-python. Not latest: livekit-agents and its
# audio dependencies lack reliable wheels for 3.13+, and compiling native
# extensions is a bad way to spend hackathon hours.
FROM python:3.12-slim

# EXTRAS lets one image serve both processes:
#   api    -> dev        (no audio dependencies)
#   voice  -> voice,dev  (lane 2's LiveKit stack)
ARG EXTRAS=dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer first: editing source should not reinstall the world.
# README is copied because setuptools reads it for project metadata.
COPY pyproject.toml ./
RUN mkdir -p shared api voice intake \
 && touch shared/__init__.py api/__init__.py voice/__init__.py intake/__init__.py \
 && pip install --no-cache-dir -e ".[${EXTRAS}]"

COPY . .

# llm/ is mounted here by compose rather than copied, so prompt edits take
# effect without a rebuild.
ENV VERDIKT_LLM_DIR=/llm

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
