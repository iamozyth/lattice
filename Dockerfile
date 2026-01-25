FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    nmap \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=wsgi:app

# Make start script executable
RUN chmod +x /app/start.sh

EXPOSE 5000

# Use start script for proper initialization sequence
ENTRYPOINT ["/app/start.sh"]

