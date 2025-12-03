# Use the official lightweight Python image.
# https://hub.docker.com/_/python
FROM python:3.9-slim

# Allow statements and log messages to be sent straight to the logs
# without being buffered.
ENV PYTHONUNBUFFERED True

# Set the working directory in the container.
WORKDIR /app

# Add the src directory to the Python path
ENV PYTHONPATH "${PYTHONPATH}:/app/src"

# Copy over the requirements.txt file and install dependencies.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the rest of the application code.
COPY . .