# Use an official Python runtime as a parent image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set the working directory in the container
WORKDIR /app

# Install packages specified in requirements.txt and create a non-root user
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --shell /usr/sbin/nologin appuser

# Copy the current directory contents into the container at /app
COPY --chown=appuser:appuser . /app

USER appuser

# Make port 8080 available outside this container
EXPOSE 8080

# Define environment variables
ENV PORT=8080
ENV MAPS_API_KEY=""

# Run Gunicorn in production rather than Flask's development server
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "8", "--timeout", "60", "app:app"]