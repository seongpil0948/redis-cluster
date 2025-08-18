FROM python:3.12-slim
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code (flat layout)
COPY . .

# Ensure package is importable when running as a module
ENV PYTHONPATH=/app

# Data/temp volumes (optional)
VOLUME ["/data/backups", "/tmp"]

# Default command (subcommand and options are specified at runtime)
ENTRYPOINT ["python", "__main__.py"]
