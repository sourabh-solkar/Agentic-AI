FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required for compiling Python packages (psycopg, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# --- Runtime configuration ---
# Required (no defaults — pass via --env-file or -e):
#   GEMINI_API_KEY   Google Gemini API key
#   SECREAT_KEY      JWT signing secret
#   ALGORITHM        JWT algorithm (e.g. HS256)
#
# Database — local Postgres on the host machine:
#   DB_HOST=host.docker.internal
#   DB_PORT=5432
#   DB_NAME=sessions
#   DB_USER=postgres
#   DB_PASSWORD=<your-password>
# Or set DATABASE_URL instead of the individual DB_* vars.

ENV ALGORITHM=HS256 \
    DB_HOST=host.docker.internal \
    DB_PORT=5432 \
    DB_NAME=sessions \
    DB_USER=postgres \
    FASTAPI_PORT=9005

EXPOSE 9005

CMD ["python", "docker_entrypoint.py"]
