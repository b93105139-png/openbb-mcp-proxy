# OpenBB MCP Server

Remote MCP server exposing OpenBB Platform tools over Streamable HTTP for Claude Code / Claude Desktop / claude.ai.

## Deployment
Deployed on Zeabur at `openbb-mcp.jessefang.com`.

## Environment variables (set in Zeabur)
| Key | Purpose |
|-----|---------|
| `MCP_AUTH_USER` | Bearer auth username (default: `jesse`) |
| `MCP_AUTH_PASSWORD` | Bearer auth password (required) |
| `POLYGON_API_KEY` | Polygon.io free tier |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage free tier |
| `FRED_API_KEY` | Optional — FRED macro data |

## Client auth
Clients send `Authorization: Bearer <base64(user:password)>`.
