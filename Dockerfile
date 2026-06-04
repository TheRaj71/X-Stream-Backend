FROM python:3.10-slim

WORKDIR /app

# Update package lists and install Git
RUN apt-get update && apt-get install -y git

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN sed -i 's/\r$//' start.sh
RUN chmod +x start.sh
CMD ["bash", "start.sh"]
