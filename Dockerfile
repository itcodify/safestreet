# Use an official lightweight Python runtime
FROM python:3.12-slim

WORKDIR /app

# Copy package dependencies and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project code into the container
COPY . .

# Render dynamically assigns a public port via the $PORT env var.
# server.py reads $PORT itself, so no hardcoded port here.
EXPOSE 8080

# Single process: server.py serves the frontend, proxies weather calls,
# and mounts the ADK agent — all on the one port Render exposes.
CMD ["python", "server.py"]
