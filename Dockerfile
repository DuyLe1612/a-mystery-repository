FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create articles directory
RUN mkdir -p articles

# Set Python to run unbuffered
ENV PYTHONUNBUFFERED=1

# Default command: cron with defaults (limit=30, priority=youtube)
# Override in docker-compose or docker run: cron [--limit N] [--priority kw]
ENTRYPOINT ["python", "main.py"]
CMD ["cron"]
