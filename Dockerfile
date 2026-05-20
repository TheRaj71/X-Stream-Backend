FROM python:3.12-slim

WORKDIR /app

# Update package lists and install Git
RUN apt-get update && apt-get install -y git && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x start.sh
CMD ["bash", "start.sh"]
