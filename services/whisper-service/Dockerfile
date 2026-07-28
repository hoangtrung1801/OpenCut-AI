FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.lock* requirements-demucs.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f requirements.lock ]; then \
      uv pip install --system -r requirements.lock; \
    else \
      uv pip install --system -r requirements.txt; \
    fi

# Demucs' historical dependency metadata conflicts with the WhisperX/Torch stack;
# install the pinned source without allowing it to downgrade those packages.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps -r requirements-demucs.txt

COPY . .

RUN mkdir -p uploads artifacts

EXPOSE 8421

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8421"]
