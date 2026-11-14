# A software token (SoftHSM) to run the connector end to end without a USB DSC. Test use only.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends softhsm2 opensc openssl ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt pytest
WORKDIR /app
