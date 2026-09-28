"""Audit every dashboard view with axe-core through the Chrome DevTools protocol.

    python scripts/a11y_audit.py --axe path/to/axe.min.js [--base http://localhost:8000]

Exits non-zero if any view has a violation in either theme. CI runs it on every push.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

VIEWS = [
    "overview", "breaches", "queues", "quality", "tickets",
]
CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]
AUDIT = """
axe.run(document, { resultTypes: ['violations'] }).then(r => r.violations.map(v => ({
  id: v.id, impact: v.impact, count: v.nodes.length,
  target: v.nodes[0].target.join(' '),
  why: (v.nodes[0].failureSummary || '').split('\\n').slice(1, 2).join(' ')
})))"""


def chrome_binary() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate and (os.path.exists(candidate) or shutil.which(candidate)):
            return candidate
    raise SystemExit("Chrome not found; set CHROME to its path.")


class DevTools:
    def __init__(self, url: str) -> None:
        self.socket = websocket.create_connection(url, timeout=60)
        self.counter = 0

    def call(self, method: str, **params):
        self.counter += 1
        self.socket.send(json.dumps({"id": self.counter, "method": method, "params": params}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == self.counter:
                return message.get("result", {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--axe", required=True, help="path to axe.min.js")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--port", type=int, default=9333)
    args = parser.parse_args()
    axe = Path(args.axe).read_text(encoding="utf-8")
    profile = tempfile.mkdtemp(prefix="serviceops-a11y-")
    chrome = subprocess.Popen(
        [chrome_binary(), "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={args.port}", f"--remote-allow-origins=http://127.0.0.1:{args.port}",
         "--window-size=1440,900", f"--user-data-dir={profile}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    failures = 0
    try:
        page = None
        for _ in range(100):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{args.port}/json"))
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        if page is None:
            raise SystemExit("Chrome did not expose a page target.")
        tools = DevTools(page["webSocketDebuggerUrl"])
        tools.call("Page.enable")
        for theme in ("dark", "light"):
            tools.call("Page.navigate", url=f"{args.base}/")
            time.sleep(2)
            store = f"localStorage.setItem('serviceops.theme','{theme}')"
            tools.call("Runtime.evaluate", expression=store)
            for view in VIEWS:
                tools.call("Page.navigate", url="about:blank")
                time.sleep(0.3)
                tools.call("Page.navigate", url=f"{args.base}/#/{view}")
                time.sleep(4)
                tools.call("Runtime.evaluate", expression=axe)
                result = tools.call("Runtime.evaluate", expression=AUDIT, awaitPromise=True,
                                    returnByValue=True)
                violations = result.get("result", {}).get("value", [])
                status = "ok" if not violations else f"{len(violations)} violation(s)"
                print(f"{theme:5} {view:15} {status}")
                for violation in violations:
                    failures += 1
                    print(f"      [{violation['impact']}] {violation['id']} x{violation['count']}: "
                          f"{violation['why']} ({violation['target']})")
    finally:
        chrome.kill()
        chrome.wait()
        shutil.rmtree(profile, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
