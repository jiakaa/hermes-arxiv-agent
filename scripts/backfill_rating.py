#!/usr/bin/env python3
"""规则化回填 rating 列(S/A/B/C)。默认只填空值;--force 覆盖。先 --dry-run 看分布。

规则与 cronjob_prompt 第九步的 S 级条件 a-e 同源。S 分两类:
  - S_ALWAYS:明确点名(VGGT/DGGT/RoadBEV/CARD/前馈重建/坑洼/道路高程…),单独出现即 S
  - S_CONTEXT:主题词(3DGS/世界模型/闭环/policy learning/scenario)需要周边上下文才算 S,
    否则降级到 A —— 这是为了让规则近似"直接涉及我的方向"的语义,而不是命中一个泛词就给 S
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

BASE = Path(__file__).resolve().parent.parent
EXCEL = BASE / "papers_record.xlsx"

# 单独出现即 S:论文点名了用户方向的核心方法/任务
S_ALWAYS = [
    r"\bvggt\b", r"\bdggt\b", r"\bworlddrive\b", r"\broadbev\b",
    r"feed[- ]?forward.{0,25}3d.{0,15}reconstruct", r"前馈重建",
    r"sparse[- ]?view.{0,25}reconstruct", r"few[- ]?view.{0,25}reconstruct",
    r"online.{0,15}reconstruct", r"增量式重建",
    r"dynamic scene.{0,25}reconstruct", r"动态场景重建",
    r"road (surface|elevation|geometry|height|profile).{0,25}(reconstruct|estimat)",
    r"道路高程", r"路面重建", r"\bpothole\b", r"坑洼",
    r"ground.{0,20}reconstruct", r"地面重建",
    r"三维高斯泼溅",
]

# (主题词, 上下文词):两者同时出现才算 S。上下文只用用户方向的强信号词
# (AD 场景 / 压缩 / 闭环 / world model),避免"命中一个泛词就给 S"。
S_CONTEXT = [
    (r"gaussian splatting|3d gaussian|3dgs|4dgs",
     r"autonomous|self[- ]?driving|driving scene|compress"),
    (r"world model|世界模型",
     r"closed[- ]?loop|autonomous driving|scenario (generation|simulation)"),
    (r"closed[- ]?loop|闭环",
     r"autonomous|driving|world model"),
]

A_RULES = [
    r"3d reconstruct", r"gaussian", r"splatting", r"autonomous driving",
    r"\boccupancy\b", r"\bbev\b", r"neural radiance", r"\bnerf\b", r"depth estimation",
    r"monocular", r"\bslam\b", r"\blidar\b", r"end[- ]to[- ]end driving", r"simulator",
    r"video generation", r"4d reconstruct", r"point cloud", r"world model",
    r"reinforcement learning", r"policy learning", r"motion planning", r"diffusion policy",
    r"reconstruct", r"novel view synthesis", r"scene representation",
    r"三维重建", r"重建", r"高斯", r"点云", r"自动驾驶", r"深度估计", r"单目", r"世界模型",
]

B_CATS = {"cs.CV", "cs.RO", "cs.LG", "cs.AI", "eess.IV", "cs.GR", "cs.MA"}


def grade(title: str, abstract: str, summary_cn: str, cats: str) -> str:
    text = " ".join([title, abstract, summary_cn]).lower()
    if any(re.search(r, text) for r in S_ALWAYS):
        return "S"
    for main, ctx in S_CONTEXT:
        if re.search(main, text) and re.search(ctx, text):
            return "S"
    if any(re.search(r, text) for r in A_RULES):
        return "A"
    cat_set = {c.strip() for c in cats.split(",") if c.strip()}
    if cat_set & B_CATS:
        return "B"
    return "C"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    wb = load_workbook(EXCEL)
    ws = wb["Papers"]
    header = [str(c.value) for c in next(ws.iter_rows(min_row=1, max_row=1))]
    idx = {h: i + 1 for i, h in enumerate(header)}
    assert "arxiv_id" in idx and "rating" in idx, "missing arxiv_id/rating column"

    dist, changed = Counter(), 0
    for r in range(2, ws.max_row + 1):
        def get(name):
            v = ws.cell(row=r, column=idx[name]).value
            return "" if v is None else str(v)

        if not get("arxiv_id"):
            continue
        if get("rating") and not args.force:
            dist["<kept>"] += 1
            continue
        g = grade(get("title"), get("abstract"), get("summary_cn"), get("categories"))
        dist[g] += 1
        if get("rating") != g:
            changed += 1
            if not args.dry_run:
                ws.cell(row=r, column=idx["rating"], value=g)

    print(f"[INFO] distribution={dict(dist)} changed={changed} dry_run={args.dry_run}")
    if not args.dry_run and changed:
        wb.save(EXCEL)
        print(f"[OK] rating backfilled, {changed} rows written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
