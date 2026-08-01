FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc g++ make curl \
    && rm -rf /var/lib/apt/lists/*

# Versions are pinned on purpose. This image was previously built from unpinned
# specs, so an unrelated redeploy on 2026-08-01 silently moved openbb 4.7.1 -> 4.7.2,
# openbb-core 1.6.8 -> 1.6.13 and aiohttp 3.13.5 -> 3.14.3. run_openbb_mcp.py patches
# openbb-core internals, so a surprise upgrade is exactly what we don't want.
# These are the versions verified working on 2026-08-01. Bump deliberately.
#
# tzdata: the python:*-slim base ships a trimmed zone set (486 zones, no legacy
# US/* aliases), and openbb's economy_calendar asks for 'US/Central' -- without this
# it fails with "No time zone found with key US/Central".
RUN pip install --no-cache-dir \
    openbb==4.7.2 \
    openbb-core==1.6.13 \
    openbb-mcp-server==1.4.1 \
    openbb-polygon==1.5.1 \
    openbb-alpha-vantage==1.6.1 \
    starlette==1.3.1 \
    uvicorn==0.40.0 \
    httpx==0.28.1 \
    tzdata

COPY proxy.py /app/proxy.py
COPY run_openbb_mcp.py /app/run_openbb_mcp.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8001
CMD ["/app/entrypoint.sh"]
