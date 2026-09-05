# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.13.7

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN python -m venv "${VIRTUAL_ENV}"

WORKDIR /build

# Both lock files are pinned. The API lock currently also contains development
# tools; keeping one audited lock is preferable to resolving production
# dependencies afresh during a release build.
COPY apps/api/requirements.lock /build/apps/api/requirements.lock
COPY requirements-core.lock /build/requirements-core.lock
RUN pip install \
      --requirement /build/apps/api/requirements.lock \
      --requirement /build/requirements-core.lock

COPY apps/api/pyproject.toml apps/api/README.md /build/apps/api/
COPY apps/api/src /build/apps/api/src

COPY pyproject.toml README.md /build/core/
COPY docreview.py run_review.py check_formal.py docx_text.py pdf_text.py /build/core/
COPY defects.yaml defects_prompt.yaml glossary.yaml template.yaml /build/core/

RUN pip install --no-deps --no-build-isolation /build/apps/api /build/core \
    && python -c "import pathlib, shutil, docreview; source=pathlib.Path('/build/core'); target=pathlib.Path(docreview.__file__).parent; [shutil.copy2(source/name, target/name) for name in ('defects.yaml','defects_prompt.yaml','glossary.yaml','template.yaml')]" \
    && docreview version


FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCREVIEW_ENVIRONMENT=production \
    DOCREVIEW_ANALYSIS_EXECUTABLE=docreview \
    DOCREVIEW_DOCUMENTS_DIR=/app/data/documents \
    DOCREVIEW_RUNS_DIR=/app/data/runs \
    DOCREVIEW_ARTIFACTS_DIR=/app/data/artifacts \
    DOCREVIEW_REVIEW_PACKS_DIR=/app/review-packs \
    DOCREVIEW_REVIEW_RESULT_SCHEMA_PATH=/app/contracts/review-result.schema.json \
    DOCREVIEW_WORKER_HEARTBEAT_PATH=/app/data/worker-heartbeat \
    DOCREVIEW_CONTAINER_ROLE=api

RUN groupadd --gid "${APP_GID}" docreview \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin docreview

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
COPY apps/api/alembic /app/apps/api/alembic
COPY apps/api/scripts/container_entrypoint.py /app/bin/container_entrypoint.py
COPY apps/api/scripts/container_healthcheck.py /app/bin/container_healthcheck.py
COPY apps/api/scripts/seed_demo.py /app/bin/seed_demo.py
COPY contracts/review-result.schema.json /app/contracts/review-result.schema.json
COPY review-packs /app/review-packs

RUN mkdir -p /app/data/documents /app/data/runs /app/data/artifacts \
    && chown -R docreview:docreview /app/data \
    && chmod -R a-w /app/contracts /app/review-packs /app/apps/api/alembic

USER docreview

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=3 \
  CMD ["python", "/app/bin/container_healthcheck.py"]

# The same immutable image runs API, worker and one-shot migrations. Compose
# overrides CMD and sets DOCREVIEW_CONTAINER_ROLE=worker for the worker service.
ENTRYPOINT ["python", "/app/bin/container_entrypoint.py"]
CMD ["api"]
