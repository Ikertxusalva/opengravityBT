FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ gfortran libpq-dev curl \
    liblapack-dev libblas-dev libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Railway provides PORT env var. We use a default for local testing.
ENV PORT=8080

EXPOSE $PORT

# Run with dynamic port
CMD sh -c "uvicorn server:app --host 0.0.0.0 --port $PORT"
