#!/usr/bin/env python3
"""扫描 viewer/reviews/*.md,生成 reviews_index.json(前端据此显示"已精读"徽章)。

Usage:
  python3 viewer/build_reviews_index.py
"""
from __future__ import annotations

import json
from pathlib import Path

VIEWER = Path(__file__).resolve().parent
REVIEWS = VIEWER / "reviews"
OUTPUT = VIEWER / "reviews_index.json"


def main() -> None:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    items = []
    for f in sorted(REVIEWS.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        title = ""
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        items.append({
            "arxiv_id": f.stem,
            "title": title,
            "updated": f.stat().st_mtime,
            "chars": len(text),
        })
    payload = {"count": len(items), "reviews": items}
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote reviews index: {len(items)} reviews -> {OUTPUT}")


if __name__ == "__main__":
    main()
