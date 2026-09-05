FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -M -d /app appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser src/ src/
COPY --chown=appuser:appuser scripts/ scripts/
COPY --chown=appuser:appuser sql/ sql/
COPY --chown=appuser:appuser api/ api/
ENV PYTHONPATH=/app/src
USER appuser
# default is overridden per Job/CronJob/Deployment spec
CMD ["python", "scripts/auto_grade.py"]
