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

# Copy the client_secret file to the /app directory
COPY client_secret.json /app/

# Expose the application port
EXPOSE 5000

# Use gunicorn with multiple workers for better performance
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "server:app"]
