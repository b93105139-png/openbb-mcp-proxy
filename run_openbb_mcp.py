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


def _apply_fred_ua_patch() -> str:
    """Override the User-Agent for stlouisfed.org. Returns a status line for the log.

    Deliberately swallows every failure. This patch reaches into openbb-core
    internals, which are not a public API and do move between releases. If it stops
    applying we want to lose the FRED provider, not the whole MCP server -- the
    other ~200 tools have nothing to do with FRED.
    """
    try:
        import openbb_core.provider.utils.client as client
    except Exception as exc:  # module moved or renamed upstream
        return f"NOT APPLIED - cannot import openbb_core client ({exc!r})"

    try:
        orig_request = client.ClientSession.request
    except AttributeError as exc:
        return f"NOT APPLIED - ClientSession.request missing ({exc!r})"

    async def request(self, *args, **kwargs):
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        if "stlouisfed.org" in str(url):
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("Accept", "application/json")
            headers["User-Agent"] = "curl/8.5.0"
            kwargs["headers"] = headers
        return await orig_request(self, *args, **kwargs)

    try:
        client.ClientSession.request = request
    except Exception as exc:
        return f"NOT APPLIED - could not patch ClientSession.request ({exc!r})"

    return "applied"


_status = _apply_fred_ua_patch()
print(f"[fred-ua-patch] {_status}", flush=True)
if _status != "applied":
    print(
        "[fred-ua-patch] provider='fred' calls will hang and surface as "
        "\"HTTP 400 {'detail': ''}\". Use provider='federal_reserve' meanwhile, and "
        "check whether openbb-core moved openbb_core.provider.utils.client.",
        flush=True,
    )

from openbb_mcp_server.app.app import main  # noqa: E402  (must follow the patch)

if __name__ == "__main__":
    sys.exit(main())
