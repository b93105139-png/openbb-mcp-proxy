#!/bin/sh
set -e

CONFIG_DIR="/root/.openbb_platform"
mkdir -p "$CONFIG_DIR"

if [ -z "${MCP_AUTH_PASSWORD}" ]; then
  echo "ERROR: MCP_AUTH_PASSWORD is required" >&2
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

cat > "$CONFIG_DIR/mcp_settings.json" <<EOF
{
  "transport": "streamable-http",
  "host": "0.0.0.0",
  "port": 8001,
  "server_auth": ["${MCP_AUTH_USER:-jesse}", "${MCP_AUTH_PASSWORD}"]
}
EOF

exec openbb-mcp
