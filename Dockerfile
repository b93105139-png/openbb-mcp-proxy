FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc g++ make curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    openbb \
    openbb-mcp-server \
    openbb-polygon \
    openbb-alpha-vantage

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8001
CMD ["/app/entrypoint.sh"]
