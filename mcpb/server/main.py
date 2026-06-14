#!/usr/bin/env python3
"""Entry point for the Selran Hub MCP Bundle (.mcpb).

The bundle ships the stdio MCP bridge (mcp_bridge.py) plus its dependencies
(mcp, httpx, pydantic) under server/lib/. We load the bridge as a standalone
module — it has no intra-package imports — so the bundle stays lean and does NOT
require the full selran-hub package to be installed.

The bridge connects to the user's running Selran Hub daemon at
127.0.0.1:${SELRAN_HUB_PORT} (default 11999); that daemon is installed and run
separately (pipx / the signed app). With no Hub running, the tools return a
friendly "start the Hub" message rather than failing hard.
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# Bundled third-party deps first, then the bundled bridge source.
for _p in (os.path.join(_HERE, "lib"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_bridge():
    bridge_path = os.path.join(_HERE, "mcp_bridge.py")
    spec = importlib.util.spec_from_file_location("selran_hub_mcp_bridge", bridge_path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so Pydantic can resolve the models' annotations
    # against this module's globals while it loads.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    _load_bridge().main()
