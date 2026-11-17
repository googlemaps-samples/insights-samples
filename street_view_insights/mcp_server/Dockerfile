FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

COPY --chown=appuser:appuser main.py .

USER appuser

EXPOSE 8080

CMD ["python", "main.py"]
