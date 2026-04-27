"""Print the DataHub connection status from the running agent API."""
import json
import sys
import urllib.request

port = sys.argv[1] if len(sys.argv) > 1 else "8100"
try:
    with urllib.request.urlopen(f"http://localhost:{port}/api/settings/connections", timeout=3) as r:
        conns = json.load(r)
except Exception:
    print("  (could not reach the agent API)")
    sys.exit(0)

dh = [c for c in conns if c["type"] in ("datahub", "datahub-mcp")]
if dh:
    for c in dh:
        url = next((f["value"] for f in c.get("fields", []) if f["key"] == "url"), "")
        line = "  ✓ " + c["label"] + " (" + c["type"] + ") — " + c["status"]
        if url:
            line += ": " + url
        print(line)
else:
    print("  ℹ  No DataHub connection configured yet.")
    print("     Settings → Add context platform → DataHub or DataHub via MCP")
