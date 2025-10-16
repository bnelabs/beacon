# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# FIX: Updated to use --no-cache-dir for smaller image size and avoiding intermediate files
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code
COPY . .

# Ensure environment variables are set (will be overridden by docker run -e if present)
ENV FRED_API_KEY=""
ENV SEC_API_KEY=""

# The ENTRYPOINT is defined here, but main.py will handle the actual execution path.
# For flexibility in running tests or verification scripts, we don't set a hard ENTRYPOINT here
# that points only to main.py. We rely on running commands explicitly via docker exec or docker run python main.py
# However, following the original script's intent:
CMD ["python", "main.py"]
