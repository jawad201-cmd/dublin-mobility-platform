@"
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY api.py .

# Expose port
EXPOSE 10000

# Run the app
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "10000"]
"@ | Out-File -FilePath Dockerfile -Encoding UTF8