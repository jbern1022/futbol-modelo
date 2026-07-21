FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY scripts/ scripts/
COPY sql/ sql/
COPY api/ api/
ENV PYTHONPATH=/app/src
# default is overridden per Job/CronJob/Deployment spec
CMD ["python", "scripts/auto_grade.py"]
