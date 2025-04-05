# Use slim version of Python for smaller image size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Cloud Run automatically assigns a PORT environment variable
# No need for EXPOSE as Cloud Run handles this

RUN echo "Contents of /app:" && ls -la /app

# Change this line
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "server_new:app"]
