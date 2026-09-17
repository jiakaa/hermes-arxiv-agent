#!/usr/bin/env python3
"""生成单篇论文的中文精读(PDF -> 全文提取 -> agy/gemini-3.8-flash-high -> viewer/reviews/<id>.md)。

用法:
  python3 scripts/generate_review.py 2609.02010
  python3 scripts/generate_review.py 2609.02010 --min-chars 5000 --timeout 2400

只处理"点击精读"所对应的单篇论文,不做批量;每天不会自动生成任何精读。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PAPERS = BASE / "papers"
REVIEWS = BASE / "viewer" / "reviews"
DEFAULT_MODEL = "gemini-3.8-flash-high"
DEFAULT_MIN_CHARS = 5000
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")

PROMPT_TEMPLATE = """你是计算机视觉 / 自动驾驶 / 3D 重建方向的资深研究者。请对下面这篇论文做一次深度精读,产出一篇中文技术解读。

论文全文(已从 PDF 提取为纯文本)位于:{input_path}
请先读取该文件(文件较大时可分段读取:摘要、引言、方法、实验、结论与附录)。

把最终解读写入文件:{out_path}

必须严格使用以下 Markdown 结构(章节标题保留,不要增删):
# <论文英文标题>
> <中文标题意译>
## 一句话总结
## 论文解决什么问题
## 核心思想
## 方法/网络结构
## 关键公式或算法
## 数据集与实验
## 主要结果
## 创新点
## 局限性
## 与相关工作的区别
## 对科研人员最值得关注的内容

硬性要求:
1. 中文正文**不少于 {min_chars} 个汉字**(目标 6000-9000 字),少于这个数量视为不合格,必须继续扩写。
2. 面向熟悉 3D 重建 / 3DGS / 世界模型 / 自动驾驶的研究生,不要泛泛而谈。每一节都必须包含该论文的具体内容:模块名、损失函数、训练策略、数据集名称、评价指标数值、对比方法名称。
3. 公式写清符号含义(LaTeX 或纯文本均可);算法用有序步骤描述。
4. 「数据集与实验」要写明数据集规模/来源、baseline、主要指标数值与消融结论。
5. 「局限性」和「与相关工作的区别」必须具体,禁止"未来可以进一步优化"这类空话。
6. 「对科研人员最值得关注的内容」要回答:(a) 哪些技术可直接用于在线前馈 3D 重建、3DGS/4DGS 场景重建与压缩、世界模型与闭环仿真、精密地面重建;(b) 是否值得复现,复现的关键难点是什么。
7. 专有名词保留英文,其余中文撰写。
8. 写完后不要输出全文到对话里,只回复一行:`DONE <汉字数量>`。
"""


def extract_text(arxiv_id: str, max_chars: int) -> tuple[Path, int, int]:
    pdf = PAPERS / f"{arxiv_id}.pdf"
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")
    import fitz  # PyMuPDF

    doc = fitz.open(pdf)
    parts: list[str] = []
    total = 0
    for i, page in enumerate(doc):
        chunk = f"\n===== PAGE {i + 1} =====\n" + page.get_text()
        parts.append(chunk)
        total += len(chunk)
        if total >= max_chars:
            break
    out = Path(f"/tmp/review_input_{arxiv_id}.txt")
    out.write_text("".join(parts), encoding="utf-8")
    return out, min(total, max_chars), doc.page_count


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text))


def run_agy(prompt: str, model: str, timeout_min: float, log_path: Path) -> int:
    agy = shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy")
    cmd = [
        agy,
        "--model", model,
        "--effort", "high",
        "--dangerously-skip-permissions",
        "--add-dir", str(BASE),
        "--print-timeout", f"{int(timeout_min)}m",
        "--print", prompt,
    ]
    with log_path.open("w", encoding="utf-8") as log:
        log.write("[CMD] " + " ".join(cmd[:-1]) + " <PROMPT>\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv_id")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    ap.add_argument("--timeout", type=float, default=30.0, help="agy print timeout (minutes)")
    ap.add_argument("--force", action="store_true", help="已存在精读时也重新生成")
    args = ap.parse_args()

    arxiv_id = args.arxiv_id.strip()
    if not ID_RE.match(arxiv_id):
        print(f"[ERROR] invalid arxiv_id: {arxiv_id!r}", file=sys.stderr)
        return 1

    REVIEWS.mkdir(parents=True, exist_ok=True)
    out_path = REVIEWS / f"{arxiv_id}.md"
    if out_path.exists() and not args.force:
        chars = count_cjk(out_path.read_text(encoding="utf-8"))
        print(f"[SKIP] review exists ({chars} 汉字): {out_path}")
        return 0

    try:
        input_path, n_chars, pages = extract_text(arxiv_id, max_chars=200_000)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2
    print(f"[INFO] extracted {n_chars} chars from {pages} pages -> {input_path}")

    log_path = Path(f"/tmp/review_{arxiv_id}.agy.log")
    prompt = PROMPT_TEMPLATE.format(
        input_path=input_path, out_path=out_path, min_chars=args.min_chars
    )

    for attempt in (1, 2):
        if attempt == 2:
            prompt += (
                f"\n\n注意:上一次生成的中文正文不足 {args.min_chars} 个汉字,"
                f"请务必扩写每一节(尤其是方法、实验、与相关工作的区别),"
                f"直到正文汉字数明确超过 {args.min_chars} 为止。"
            )
        print(f"[INFO] agy attempt {attempt} (model={args.model}, timeout={args.timeout}m)")
        rc = run_agy(prompt, args.model, args.timeout, log_path)
        if out_path.exists():
            chars = count_cjk(out_path.read_text(encoding="utf-8"))
            print(f"[INFO] attempt {attempt}: wrote {chars} 汉字 (agy rc={rc})")
            if chars >= args.min_chars:
                print(f"[OK] {out_path} ({chars} 汉字)")
                return 0
        else:
            print(f"[WARN] attempt {attempt}: no output file (agy rc={rc})")

    print(
        f"[ERROR] review generation failed or too short (<{args.min_chars} 汉字). "
        f"See log: {log_path}",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    sys.exit(main())
