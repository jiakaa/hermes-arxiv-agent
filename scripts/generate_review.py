#!/usr/bin/env python3
"""生成单篇论文的中文精读(agy/gemini-3.8-flash-high -> viewer/reviews/<id>.md)。

论文原文直接交给 agy 处理:默认把 **PDF 路径 + arXiv 链接** 写进 prompt,由 agy 自己读,
不再预先把 PDF 转成文本(agy 的 token 便宜,省掉一次转换也省掉信息损失)。
若 agy 无法处理 PDF,自动退回到"提取文本"模式(可用 --source 强制指定)。

用法:
  python3 scripts/generate_review.py 2609.02010
  python3 scripts/generate_review.py 2609.02010 --download-pdf     # 本机没有 PDF 时先下载
  python3 scripts/generate_review.py 2609.02010 --source text      # 强制文本模式
  python3 scripts/generate_review.py 2609.02010 --min-chars 5000 --timeout 30

只处理"点击精读"对应的单篇论文,不做批量;每天不会自动生成任何精读。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PAPERS = BASE / "papers"
REVIEWS = BASE / "viewer" / "reviews"
DEFAULT_MODEL = "gemini-3.8-flash-high"
DEFAULT_MIN_CHARS = 5000
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")

STRUCTURE = """# <论文英文标题>
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
## 对科研人员最值得关注的内容"""

PROMPT_HEAD = """你是计算机视觉 / 自动驾驶 / 3D 重建方向的资深研究者。请精读下面这篇论文,产出一篇中文深度解读。

{source_block}

把最终解读写入文件:{out_path}

必须严格使用以下 Markdown 结构(章节标题保留,不要增删):
{structure}

硬性要求:
1. 中文正文**不少于 {min_chars} 个汉字**(目标 6000-9000 字),少于这个数量视为不合格,必须继续扩写。
2. 面向熟悉 3D 重建 / 3DGS / 世界模型 / 自动驾驶的研究生,不要泛泛而谈。每一节都必须包含该论文的具体内容:模块名、损失函数、训练策略、数据集名称、评价指标数值、对比方法名称。
3. 公式写清符号含义;算法用有序步骤描述。
4. 「数据集与实验」要写明数据集规模/来源、baseline、主要指标数值与消融结论。
5. 「局限性」和「与相关工作的区别」必须具体,禁止"未来可以进一步优化"这类空话。
6. 「对科研人员最值得关注的内容」要回答:(a) 哪些技术可直接用于在线前馈 3D 重建、3DGS/4DGS 场景重建与压缩、世界模型与闭环仿真、精密地面重建;(b) 是否值得复现,复现的关键难点是什么。
7. 专有名词保留英文,其余中文撰写。

排版要求(读者在网页上阅读,必须把 Markdown 的表现力用足):
8. 用 `###` 小标题把长章节拆开;单段不超过 5 行,避免大段文字墙。
9. 关键术语、指标数值、结论用 **加粗**;需要强调的短句用 ==双等号高亮==;确需下划线时写 `<u>文字</u>`。
10. 对比性内容(本文 vs 之前工作、各数据集结果、消融实验)一律用 Markdown 表格,例如:
    | 方法 | 数据集 | 指标 | 说明 |
    | --- | --- | --- | --- |
    | 示例 | 数据集A | 12.3 | 一句话 |
11. 重要结论、容易踩的坑、给读者的提醒用 GitHub 告警块(渲染成彩色卡片):
    > [!IMPORTANT]
    > 内容
    可用的类型:`[!NOTE]` `[!TIP]` `[!IMPORTANT]` `[!WARNING]` `[!CAUTION]`。
12. 公式用 `$...$` 或 `$$...$$`(网页用 KaTeX 渲染),符号必须逐个解释。
13. 冗长的推导、完整参数表、复现步骤放进折叠块,避免打断阅读:
    <details><summary>展开:标题</summary>
    这里写 Markdown 正文
    </details>
14. 用 `---` 分隔大节;用 `- [ ]` / `- [x]` 表示复现清单或检查项。
15. 不要插入图片;除 `#` 与 `##` 外不要用更大层级;不要在正文里贴大段无格式纯文本代码。
16. 写完后不要输出全文到对话里,只回复一行:`DONE <汉字数量>`。
"""

SOURCE_BLOCK_PDF = """论文原文是一份 PDF,直接读取这个本地文件:
  {pdf_path}
也可以从 arXiv 获取同一篇论文:{pdf_url}
请优先读取本地 PDF 全文(必要时分段读取:摘要、引言、方法、实验、附录)。"""

SOURCE_BLOCK_TEXT = """论文全文(已从 PDF 提取为纯文本)位于:{input_path}
请先读取该文件(文件较大时可分段读取:摘要、引言、方法、实验、结论与附录)。"""


def download_pdf(arxiv_id: str) -> Path:
    """本机没有 PDF 时从 arXiv 取一份(monitor.py 的命名规则一致:papers/<id>.pdf)。"""
    PAPERS_DIR = PAPERS
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    pdf = PAPERS_DIR / f"{arxiv_id}.pdf"
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    print(f"[INFO] downloading {url} -> {pdf}")
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-arxiv-agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, pdf.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    print(f"[INFO] downloaded {pdf.stat().st_size} bytes")
    return pdf


def extract_text(arxiv_id: str, max_chars: int) -> tuple[Path, int, int]:
    """文本兜底模式:把 PDF 前若干页转成纯文本供 agy 读取。"""
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
        log.write("[PROMPT]\n" + prompt + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
    return proc.returncode


def rebuild_index() -> None:
    """生成成功后刷新 reviews_index.json,便于前端显示"已精读"徽章。"""
    script = BASE / "viewer" / "build_reviews_index.py"
    if not script.exists():
        return
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    print((result.stdout or result.stderr or "").strip()[:300])


def build_prompt(source: str, arxiv_id: str, out_path: Path, min_chars: int) -> str:
    pdf_path = PAPERS / f"{arxiv_id}.pdf"
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    if source == "pdf":
        block = SOURCE_BLOCK_PDF.format(pdf_path=pdf_path, pdf_url=pdf_url)
    else:
        input_path, n_chars, pages = extract_text(arxiv_id, max_chars=200_000)
        print(f"[INFO] extracted {n_chars} chars from {pages} pages -> {input_path}")
        block = SOURCE_BLOCK_TEXT.format(input_path=input_path)
    return PROMPT_HEAD.format(
        source_block=block, out_path=out_path, structure=STRUCTURE, min_chars=min_chars
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv_id")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    ap.add_argument("--timeout", type=float, default=30.0, help="agy print timeout (minutes)")
    ap.add_argument("--source", choices=["pdf", "text", "auto"], default="auto",
                    help="auto:先让 agy 直接读 PDF,失败再退回文本模式")
    ap.add_argument("--download-pdf", action="store_true", help="本机缺 PDF 时先从 arXiv 下载")
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

    if not (PAPERS / f"{arxiv_id}.pdf").exists():
        if args.download_pdf:
            try:
                download_pdf(arxiv_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] download failed: {exc}", file=sys.stderr)
                return 2
        else:
            print(f"[ERROR] PDF not found: {PAPERS / (arxiv_id + '.pdf')} (可加 --download-pdf)",
                  file=sys.stderr)
            return 2

    log_path = Path(f"/tmp/review_{arxiv_id}.agy.log")
    sources = ["pdf", "text"] if args.source == "auto" else [args.source]

    for source in sources:
        try:
            prompt = build_prompt(source, arxiv_id, out_path, args.min_chars)
        except FileNotFoundError as exc:
            print(f"[WARN] {exc}", file=sys.stderr)
            continue
        for attempt in (1, 2):
            run_prompt = prompt
            if attempt == 2:
                run_prompt += (
                    f"\n\n注意:上一次生成的中文正文不足 {args.min_chars} 个汉字,"
                    f"请务必扩写每一节(尤其是方法、实验、与相关工作的区别),"
                    f"直到正文汉字数明确超过 {args.min_chars} 为止。"
                )
            print(f"[INFO] agy source={source} attempt={attempt} model={args.model} timeout={args.timeout}m")
            rc = run_agy(run_prompt, args.model, args.timeout, log_path)
            if not out_path.exists():
                print(f"[WARN] source={source} attempt={attempt}: 未产出文件 (agy rc={rc})")
                break
            chars = count_cjk(out_path.read_text(encoding="utf-8"))
            print(f"[INFO] source={source} attempt={attempt}: {chars} 汉字 (agy rc={rc})")
            if chars >= args.min_chars:
                rebuild_index()
                print(f"[OK] {out_path} ({chars} 汉字)")
                return 0

    print(
        f"[ERROR] 精读生成失败或字数不足 (<{args.min_chars} 汉字)。日志: {log_path}",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    sys.exit(main())
