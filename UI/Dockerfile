FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required for certain Python packages (like pgvector/psycopg2)
# Install system dependencies required for compiling Python packages
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

# Expose the default port Streamlit runs on
EXPOSE 8501


# Configure Streamlit to run headlessly and bind to all network interfaces
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
