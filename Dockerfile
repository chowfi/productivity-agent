# Dockerfile for task scheduler server
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server/ ./server/
COPY client/ ./client/

# Create data directory
RUN mkdir -p /app/server/data /app/server/data/tokens

# Set environment variables
ENV PYTHONPATH=/app
ENV MCP_DATA_DIR=/app/server/data

# Expose port
EXPOSE 8084

# Run the server
CMD ["python", "-m", "server.task_scheduler_server"]

