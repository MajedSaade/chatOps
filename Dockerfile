FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies and create a non-root user
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m myuser

# Copy and install requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code and set ownership to the non-root user
COPY --chown=myuser:myuser app ./app

# Switch to the non-root user for execution
USER myuser

EXPOSE 8443

CMD ["python", "-m", "app.app"]