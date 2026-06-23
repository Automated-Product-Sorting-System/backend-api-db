FROM python:3.10-slim

# Prevent Python from generating .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy dependencies file and install required packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project (core, databases, main.py, etc.)
COPY . .

# Expose the port used by the FastAPI application
EXPOSE 8000

# Start the FastAPI server with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]