# Build-time arguments
FROM python:3.11.9-slim
ARG RABBITMQ_HOST
ARG RABBITMQ_PORT

WORKDIR /app

# Create logs directory
RUN mkdir -p logs

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && pip install --no-cache-dir flask gunicorn pika nltk requests langchain-text-splitters flasgger \
    && python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab')" \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . /app

# Set environment variables, using ARG values
ENV RABBITMQ_HOST=$RABBITMQ_HOST
ENV RABBITMQ_PORT=$RABBITMQ_PORT
ENV RABBITMQ_USER=username
ENV RABBITMQ_PASS=password

# Expose static port
EXPOSE 5002

# Healthcheck for /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5002/health || exit 1

# Run Gunicorn with logging
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "run:app", "--workers", "4", "--timeout", "300", "--log-file", "/app/logs/gunicorn.log"]
