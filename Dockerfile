FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY scripts/ scripts/
COPY sql/ sql/
ENV PYTHONPATH=/app/src
# default is overridden per CronJob
CMD ["python", "-m", "ingestion.loader", "matchday", "--league", "EPL"]
