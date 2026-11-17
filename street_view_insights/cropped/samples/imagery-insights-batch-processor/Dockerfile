# Use the official lightweight Python image.
# https://hub.docker.com/_/python
FROM python:3.12-slim

# Allow statements and log messages to be sent straight to the logs
# without being buffered.
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set the working directory in the container.
WORKDIR /app

# Add the src directory to the Python path
ENV PYTHONPATH="/app/src"

# Copy over the requirements.txt file and install dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --shell /usr/sbin/nologin appuser

# Copy the rest of the application code.
COPY --chown=appuser:appuser . .

USER appuser