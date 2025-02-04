FROM bitnami/python:latest
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY mra_grafana_ingestor.py .

# Change entrypoint to bash
ENTRYPOINT ["/bin/bash"]
