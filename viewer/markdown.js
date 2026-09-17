// 精读 Markdown 渲染器:支持标题/列表/任务列表/表格/引用与 GitHub 告警块/折叠块/公式(KaTeX)。
// 独立成文件便于维护:review.js 只负责面板逻辑。
(function () {
  const ALLOWED_TAGS = [
    ["&lt;u&gt;", "<u>"], ["&lt;/u&gt;", "</u>"],
    ["&lt;mark&gt;", "<mark>"], ["&lt;/mark&gt;", "</mark>"],
    ["&lt;sub&gt;", "<sub>"], ["&lt;/sub&gt;", "</sub>"],
    ["&lt;sup&gt;", "<sup>"], ["&lt;/sup&gt;", "</sup>"],
  ];
  const CALLOUTS = {
    NOTE: { cls: "note", label: "提示" },
    TIP: { cls: "tip", label: "技巧" },
    IMPORTANT: { cls: "important", label: "重要" },
    WARNING: { cls: "warning", label: "注意" },
    CAUTION: { cls: "caution", label: "警告" },
  };

  function esc(s) {
    return (s || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // 行内:代码段先抽出占位,再按白名单放行少量 HTML,最后处理 markdown 语法。
  // 注意:不处理 _斜体_,因为 LaTeX 下标大量使用下划线,会互相误伤。
  function inline(raw) {
    const codes = [];
    let s = esc(raw).replace(/`([^`]+)`/g, (_m, c) => {
      codes.push(c);
      return `\u0000${codes.length - 1}\u0000`;
    });
    for (const [from, to] of ALLOWED_TAGS) s = s.split(from).join(to);
    s = s
      .replace(/!\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)/g, '<img src="$2" alt="$1">')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>")
      .replace(/==([^=\n]+)==/g, "<mark>$1</mark>")
      .replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => `<code>${codes[Number(i)]}</code>`);
  }

  const isTableSep = (line) => /-/.test(line) && /^\s*\|?[\s:|-]+\|[\s:|-]*\s*$/.test(line);
  const isTableRow = (line) => /^\s*\|.*\|\s*$/.test(line);
  const splitRow = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

  function renderTable(header, rows) {
    const th = header.map((c) => `<th>${inline(c)}</th>`).join("");
    const body = rows
      .map((r) => `<tr>${header.map((_c, i) => `<td>${inline(r[i] || "")}</td>`).join("")}</tr>`)
      .join("");
    return `<div class="md-table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function renderBlocks(lines) {
    let html = "";
    let i = 0;
    let listType = null;
    const closeList = () => {
      if (listType) {
        html += listType === "ol" ? "</ol>" : "</ul>";
        listType = null;
      }
    };

    while (i < lines.length) {
      const raw = lines[i];

      // 代码块
      if (raw.trim().startsWith("```")) {
        closeList();
        const buf = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          buf.push(lines[i]);
          i++;
        }
        i++;
        html += `<pre><code>${esc(buf.join("\n"))}</code></pre>`;
        continue;
      }

      // 折叠块 <details><summary>..</summary> ... </details>
      if (/^\s*<details/i.test(raw)) {
        closeList();
        let summary = "";
        const m0 = raw.match(/<summary>(.*?)<\/summary>/i);
        if (m0) summary = m0[1];
        const inner = [];
        i++;
        while (i < lines.length && !/<\/details>/i.test(lines[i])) {
          const m1 = lines[i].match(/<summary>(.*?)<\/summary>/i);
          if (!summary && m1) {
            summary = m1[1];
            i++;
            continue;
          }
          inner.push(lines[i]);
          i++;
        }
        i++; // 跳过 </details>
        html += `<details><summary>${inline(summary)}</summary><div class="md-details-body">${renderBlocks(inner)}</div></details>`;
        continue;
      }

      // 表格
      if (isTableRow(raw) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        closeList();
        const header = splitRow(raw);
        const rows = [];
        i += 2;
        while (i < lines.length && isTableRow(lines[i])) {
          rows.push(splitRow(lines[i]));
          i++;
        }
        html += renderTable(header, rows);
        continue;
      }

      // 空行
      if (!raw.trim()) {
        closeList();
        i++;
        continue;
      }

      // 水平线
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(raw)) {
        closeList();
        html += "<hr>";
        i++;
        continue;
      }

      // 标题
      const h = raw.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeList();
        const level = Math.min(h[1].length, 6);
        html += `<h${level}>${inline(h[2])}</h${level}>`;
        i++;
        continue;
      }

      // 引用 / GitHub 告警块
      if (/^\s*>/.test(raw)) {
        closeList();
        const buf = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          buf.push(lines[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        const alert = buf[0] && buf[0].trim().match(/^\[!(\w+)\]\s*$/);
        if (alert && CALLOUTS[alert[1].toUpperCase()]) {
          const cfg = CALLOUTS[alert[1].toUpperCase()];
          const rest = buf.slice(1);
          html += `<div class="callout callout-${cfg.cls}"><p class="callout-title">${cfg.label}</p>${renderBlocks(rest)}</div>`;
        } else {
          html += `<blockquote>${renderBlocks(buf)}</blockquote>`;
        }
        continue;
      }

      // 列表(含任务列表)
      const task = raw.match(/^\s*[-*]\s+\[( |x|X)\]\s+(.*)$/);
      const ul = raw.match(/^\s*[-*]\s+(.*)$/);
      const ol = raw.match(/^\s*\d+[.)]\s+(.*)$/);
      if (task || ul || ol) {
        const want = ol ? "ol" : "ul";
        if (listType !== want) {
          closeList();
          html += want === "ol" ? "<ol>" : "<ul class=\"md-list\">";
          listType = want;
        }
        if (task) {
          const checked = task[1].toLowerCase() === "x";
          html += `<li class="md-task${checked ? " done" : ""}"><span class="md-check">${checked ? "☑" : "☐"}</span>${inline(task[2])}</li>`;
        } else {
          html += `<li>${inline((ul || ol)[1])}</li>`;
        }
        i++;
        continue;
      }

      // 普通段落(合并连续行)
      closeList();
      const para = [raw];
      i++;
      while (
        i < lines.length && lines[i].trim() &&
        !/^(#{1,6}\s|```|\s*>|\s*[-*]\s|\s*\d+[.)]\s|\s*<details)/i.test(lines[i]) &&
        !isTableRow(lines[i]) && !/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i])
      ) {
        para.push(lines[i]);
        i++;
      }
      html += `<p>${inline(para.join(" "))}</p>`;
    }
    closeList();
    return html;
  }

  window.mdRender = (md) => renderBlocks((md || "").split(/\r?\n/));

  // 插入 DOM 后再交给 KaTeX(auto-render 会跳过 pre/code)
  window.mdRenderMath = function (el) {
    if (!el || typeof window.renderMathInElement !== "function") return;
    try {
      window.renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
        ],
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
        throwOnError: false,
      });
    } catch (err) {
      console.warn("KaTeX 渲染失败", err);
    }
  };
})();
