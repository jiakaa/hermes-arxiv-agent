#!/usr/bin/env python3
"""
Build papers_data.json from Excel and serve static viewer.

Usage:
  python3 run_viewer.py
"""

from __future__ import annotations

import argparse
import errno
import http.server
import json
import re
import socketserver
import subprocess
import threading
import time
from pathlib import Path
import socket
import sys

from build_data import main as build_data_main

PORT = 8765
HOST = "0.0.0.0"
VIEWER_DIR = Path(__file__).resolve().parent
FAVORITES_FILE = VIEWER_DIR / "favorites.json"

# ===== 精读生成(点击触发,不在任何定时任务里自动跑)=====
PAPERS_DIR = VIEWER_DIR.parent / "papers"
REVIEWS_DIR = VIEWER_DIR / "reviews"
GENERATE_SCRIPT = VIEWER_DIR.parent / "scripts" / "generate_review.py"
REVIEW_PATH_RE = re.compile(r"^/api/review/(?P<arxiv_id>\d{4}\.\d{4,5})$")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_review_jobs: dict[str, dict] = {}
_review_lock = threading.Lock()


def _cjk_count(path: Path) -> int:
    return len(CJK_RE.findall(path.read_text(encoding="utf-8", errors="replace")))


def review_status(arxiv_id: str) -> dict:
    md = REVIEWS_DIR / f"{arxiv_id}.md"
    if md.exists():
        return {"status": "done", "chars": _cjk_count(md)}
    with _review_lock:
        job = _review_jobs.get(arxiv_id)
        proc = job["proc"] if job else None
        started = job["started_at"] if job else 0.0
    if proc is not None and proc.poll() is None:
        return {"status": "generating", "elapsed": time.time() - started, "pid": proc.pid}
    if proc is not None:
        log_path = Path(f"/tmp/review_{arxiv_id}.agy.log")
        tail = ""
        if log_path.exists():
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
        return {
            "status": "error",
            "message": f"生成进程已退出(rc={proc.returncode}),结果未达到要求",
            "log": tail,
        }
    return {"status": "missing"}


def start_review(arxiv_id: str) -> tuple[dict, int]:
    md = REVIEWS_DIR / f"{arxiv_id}.md"
    if md.exists():
        return {"status": "done", "chars": _cjk_count(md)}, 200
    if not (PAPERS_DIR / f"{arxiv_id}.pdf").exists():
        return {"status": "error", "message": f"本地缺少 PDF:papers/{arxiv_id}.pdf"}, 404
    if not GENERATE_SCRIPT.exists():
        return {"status": "error", "message": f"缺少生成脚本:{GENERATE_SCRIPT}"}, 500
    with _review_lock:
        job = _review_jobs.get(arxiv_id)
        if job and job["proc"].poll() is None:
            return {"status": "generating", "elapsed": time.time() - job["started_at"]}, 409
        log = open(f"/tmp/review_{arxiv_id}.server.log", "w", encoding="utf-8")  # noqa: SIM115
        proc = subprocess.Popen(
            [sys.executable, str(GENERATE_SCRIPT), arxiv_id],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(VIEWER_DIR.parent),
        )
        _review_jobs[arxiv_id] = {"proc": proc, "started_at": time.time()}
    return {"status": "generating", "pid": proc.pid}, 202


def get_local_ip() -> str:
    """Best-effort local IP for LAN hint."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def load_favorites() -> list[str]:
    if not FAVORITES_FILE.exists():
        return []
    try:
        data = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    result = []
    seen = set()
    for item in data:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def save_favorites(favorites: list[str]) -> None:
    FAVORITES_FILE.write_text(
        json.dumps(favorites, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve local/LAN viewer")
    parser.add_argument("--host", default=HOST, help="Bind host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=PORT, help="Bind port, default: 8765")
    args = parser.parse_args()

    build_data_main()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

        def _send_json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/api/health":
                self._send_json({"ok": True, "mode": "local"})
                return
            match = REVIEW_PATH_RE.match(self.path)
            if match:
                self._send_json(review_status(match.group("arxiv_id")))
                return
            if self.path == "/api/favorites":
                self._send_json({"favorites": load_favorites()})
                return
            super().do_GET()

        def do_POST(self) -> None:
            match = REVIEW_PATH_RE.match(self.path)
            if match:
                payload, status = start_review(match.group("arxiv_id"))
                self._send_json(payload, status=status)
                return
            if self.path != "/api/favorites":
                self.send_error(404, "Not Found")
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json({"error": "Invalid JSON"}, status=400)
                return

            favorites = payload.get("favorites")
            if not isinstance(favorites, list):
                self._send_json({"error": "favorites must be a list"}, status=400)
                return

            cleaned = []
            seen = set()
            for item in favorites:
                text = str(item).strip()
                if text and text not in seen:
                    seen.add(text)
                    cleaned.append(text)

            save_favorites(cleaned)
            self._send_json({"favorites": cleaned})

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    try:
        with Server((args.host, args.port), Handler) as httpd:
            local_ip = get_local_ip()
            print(f"[OK] Viewer running at http://127.0.0.1:{args.port}")
            print(f"[OK] LAN access: http://{local_ip}:{args.port}")
            print(f"[OK] Favorites file: {FAVORITES_FILE}")
            print("[INFO] Press Ctrl+C to stop")
            httpd.serve_forever()
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(f"[ERROR] Port {args.port} is already in use.")
            print("[HINT] Stop existing process or start with another port, e.g.")
            print("       python3 run_viewer.py --port 8766")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
