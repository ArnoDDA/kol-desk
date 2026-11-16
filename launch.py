#!/usr/bin/env python3
"""Start the local app or reopen an already running KOL Desk instance."""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def running_workspace(url):
    try:
        # Never send loopback health checks through a configured system proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/health', timeout=2) as response:
            return json.load(response).get('app') == 'kol-desk'
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    if running_workspace(url):
        print('KOL Desk is already running / 工作台已在运行。', flush=True)
        webbrowser.open(url)
        return 0
    print('Starting KOL Desk. Keep this window open while using it.\n正在启动工作台，使用期间请保持此窗口打开。', flush=True)
    process = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--port', str(args.port), '--open-browser'], cwd=str(ROOT))
    try:
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.terminate()
        process.wait()
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
