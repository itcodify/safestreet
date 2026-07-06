# Use an official lightweight Python runtime
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project code into the container
COPY . .

# Compile the ADK Web Agent assets
RUN adk web agent

# Render dynamically assigns a public port via the $PORT variable
EXPOSE 8080

# Run a shell command sequence to:
# 1. Start the HTTP static frontend server on port 5500 in the background (&)
# 2. Run the ADK API backend server on the Render assigned port, allowing your frontend to talk to it
CMD python -m http.server 5500 --directory frontend & \
    adk api_server agent --port $PORT --allow_origins *