#!/usr/bin/env python
"""Launch openbb-mcp with the FRED User-Agent workaround applied.

Why this wrapper exists
-----------------------
api.stlouisfed.org hangs the connection -- it never responds, the client just sits
there until it times out -- when the request User-Agent contains "Mozilla" or
"openbb". openbb-core stamps a random browser User-Agent on every outbound request
(see ``openbb_core/provider/utils/client.py::get_user_agent``), so *every*
``provider="fred"`` call hangs.

The failure is invisible from the outside: aiohttp raises ``TimeoutError``, whose
``str()`` is the empty string, and ``openbb_fred/models/series.py`` re-raises it as
``OpenBBError("")``. The MCP layer then reports ``HTTP 400 - {'detail': ''}``, which
looks like a bad request or a missing API key rather than a hung connection.

Measured against api.stlouisfed.org on 2026-08-01 (3 runs each, fully reproducible):

    no User-Agent header      -> 200 in ~0.2s
    curl/8.5.0                -> 200 in ~0.2s
    python-requests/2.31.0    -> 200 in ~0.4s
    Python/3.11 aiohttp/3.13.5 -> 200 in ~0.2s
    Mozilla/5.0 ... (openbb)  -> hangs until timeout
    python-openbb/1.0         -> hangs until timeout

So we override the User-Agent for stlouisfed.org only. Every other provider keeps
openbb's default rotating browser User-Agent, which some of them rely on.

This is a wrapper rather than a ``sitecustomize.py`` on purpose: sitecustomize is
imported by every interpreter in the container and pulling in openbb_core there costs
~515ms per process start, including proxy.py. Patching here keeps both the cost and
the blast radius inside the MCP server process.

Remove this once openbb-core stops sending browser User-Agents to API endpoints, or
once FRED stops hanging them.
"""

import sys

import openbb_core.provider.utils.client as _client

_orig_request = _client.ClientSession.request


async def _request(self, *args, **kwargs):
    """Force a benign User-Agent on FRED requests; pass everything else through."""
    url = args[1] if len(args) > 1 else kwargs.get("url", "")
    if "stlouisfed.org" in str(url):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Accept", "application/json")
        headers["User-Agent"] = "curl/8.5.0"
        kwargs["headers"] = headers
    return await _orig_request(self, *args, **kwargs)


_client.ClientSession.request = _request

from openbb_mcp_server.app.app import main  # noqa: E402  (must follow the patch)

if __name__ == "__main__":
    sys.exit(main())
