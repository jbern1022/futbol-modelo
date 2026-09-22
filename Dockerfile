FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -M -d /app appuser
COPY requirements.txt requirements-nfl.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps -r requirements-nfl.txt
COPY --chown=appuser:appuser src/ src/
COPY --chown=appuser:appuser scripts/ scripts/
COPY --chown=appuser:appuser sql/ sql/
COPY --chown=appuser:appuser api/ api/
# dixon_coles is its own standalone package now (see packages/dixon-coles/
# README) -- each script that needs it does its own sys.path.insert
# pointing here, same pattern as the existing src/ insertion.
COPY --chown=appuser:appuser packages/dixon-coles/src/ packages/dixon-coles/src/
ENV PYTHONPATH=/app/src
USER appuser
# default is overridden per Job/CronJob/Deployment spec
CMD ["python", "scripts/auto_grade.py"]
