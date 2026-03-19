FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

WORKDIR /app

RUN python -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY . .
RUN python -m compileall ironcore deployment

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    IRONCORE_HOST=0.0.0.0 \
    IRONCORE_PORT=8000

WORKDIR /app

RUN addgroup --system ironcore && adduser --system --ingroup ironcore ironcore

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

RUN chown -R ironcore:ironcore /app

USER ironcore

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"IRONCORE_PORT\", \"8000\")}/health', timeout=3).read()"

CMD ["uvicorn", "ironcore.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
