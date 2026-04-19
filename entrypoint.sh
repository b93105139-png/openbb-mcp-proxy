#!/bin/sh
set -e

CONFIG_DIR="/root/.openbb_platform"
mkdir -p "$CONFIG_DIR"

if [ -z "${OPENBB_BEARER_TOKEN}" ]; then
  echo "ERROR: OPENBB_BEARER_TOKEN is required" >&2
  exit 1
fi

cat > "$CONFIG_DIR/user_settings.json" <<EOF
{
  "credentials": {
    "polygon_api_key": "${POLYGON_API_KEY:-}",
    "alpha_vantage_api_key": "${ALPHA_VANTAGE_API_KEY:-}",
    "fred_api_key": "${FRED_API_KEY:-}"
  }
}
EOF

openbb-mcp --host 127.0.0.1 --port 8002 --transport streamable-http &
UPSTREAM_PID=$!

trap "kill $UPSTREAM_PID 2>/dev/null" EXIT INT TERM

export OPENBB_UPSTREAM="http://127.0.0.1:8002"
export HOST=0.0.0.0
export PORT=8001

exec python /app/proxy.py
