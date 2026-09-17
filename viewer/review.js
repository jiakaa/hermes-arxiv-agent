// 精读面板:已生成 -> 直接展示;未生成 -> 若在本地 viewer(有 /api/)则点击后调用 agy 生成。
(function () {
  const panel = document.getElementById("reviewPanel");
  const body = document.getElementById("reviewBody");
  const titleEl = document.getElementById("reviewTitle");
  const linkEl = document.getElementById("reviewArxivLink");
  let indexCache = null;
  let apiAvailable = null;
  let pollTimer = null;
  let currentId = null;

  function esc(s) {
    return (s || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function renderMarkdown(md) {
    const lines = md.split(/\r?\n/);
    let html = "", inCode = false, inList = false;
    const codeBuf = [];
    const inline = (s) => s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    for (const raw of lines) {
      if (raw.trim().startsWith("```")) {
        if (inCode) { html += `<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`; codeBuf.length = 0; }
        inCode = !inCode;
        continue;
      }
      if (inCode) { codeBuf.push(raw); continue; }
      if (!raw.trim()) { if (inList) { html += "</ul>"; inList = false; } continue; }
      const h = raw.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<h${h[1].length}>${inline(esc(h[2]))}</h${h[1].length}>`;
        continue;
      }
      const li = raw.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
      if (li) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${inline(esc(li[1]))}</li>`;
        continue;
      }
      if (/^>\s?/.test(raw)) {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<blockquote>${inline(esc(raw.replace(/^>\s?/, "")))}</blockquote>`;
        continue;
      }
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p>${inline(esc(raw))}</p>`;
    }
    if (inCode) html += `<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`;
    if (inList) html += "</ul>";
    return html;
  }

  async function loadIndex() {
    if (indexCache) return indexCache;
    try {
      const res = await fetch("reviews_index.json", { cache: "no-store" });
      indexCache = res.ok ? await res.json() : { count: 0, reviews: [] };
    } catch (e) {
      indexCache = { count: 0, reviews: [] };
    }
    return indexCache;
  }

  async function detectApi() {
    if (apiAvailable !== null) return apiAvailable;
    try {
      const res = await fetch("api/health", { cache: "no-store" });
      apiAvailable = res.ok;
    } catch (e) {
      apiAvailable = false;
    }
    return apiAvailable;
  }

  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function close() {
    stopPolling();
    panel.hidden = true;
    currentId = null;
  }

  async function showMarkdown(arxivId) {
    const res = await fetch(`reviews/${encodeURIComponent(arxivId)}.md`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    body.innerHTML = renderMarkdown(await res.text());
    indexCache = null;
    await loadIndex();
  }

  function renderGeneratePrompt(arxivId, message) {
    body.innerHTML =
      `<div class="review-empty">` +
      (message ? `<p>${esc(message)}</p>` : "") +
      `<p>该论文还没有精读文档。</p>` +
      `<p><button class="btn btn-primary" id="genReviewBtn">生成精读(约 2-5 分钟)</button></p>` +
      `<p class="hint">生成会调用本机 agy(gemini-3.8-flash-high)阅读全文并写入 <code>viewer/reviews/${esc(arxivId)}.md</code>,完成后自动显示。</p>` +
      `</div>`;
    const btn = document.getElementById("genReviewBtn");
    if (btn) btn.addEventListener("click", () => startGeneration(arxivId));
  }

  async function startGeneration(arxivId) {
    body.innerHTML = `<div class="review-loading">正在启动生成…</div>`;
    try {
      const res = await fetch(`api/review/${encodeURIComponent(arxivId)}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok && res.status !== 409) {
        throw new Error(data.message || `HTTP ${res.status}`);
      }
      pollStatus(arxivId);
    } catch (err) {
      body.innerHTML = `<div class="review-empty">生成请求失败:${esc(err.message)}</div>`;
    }
  }

  async function pollStatus(arxivId) {
    stopPolling();
    try {
      const res = await fetch(`api/review/${encodeURIComponent(arxivId)}`, { cache: "no-store" });
      const data = await res.json();
      if (data.status === "done") {
        await showMarkdown(arxivId);
        return;
      }
      if (data.status === "error") {
        body.innerHTML = `<div class="review-empty">生成失败:${esc(data.message || "未知错误")}
          <p class="hint"><code>${esc((data.log || "").slice(-800))}</code></p></div>`;
        return;
      }
      const elapsed = data.elapsed ? Math.round(data.elapsed) : 0;
      body.innerHTML = `<div class="review-loading">正在生成精读…已用 ${elapsed}s
        <p class="hint">agy 正在阅读全文并撰写(目标 ≥5000 字),请保持本页打开。</p></div>`;
      pollTimer = setTimeout(() => pollStatus(arxivId), 4000);
    } catch (err) {
      body.innerHTML = `<div class="review-empty">状态查询失败:${esc(err.message)}</div>`;
    }
  }

  window.paperReview = {
    loadIndex,
    hasReview(arxivId) {
      return indexCache ? indexCache.reviews.some((r) => r.arxiv_id === String(arxivId)) : false;
    },
    async open(arxivId, title) {
      currentId = String(arxivId);
      titleEl.textContent = title || arxivId;
      linkEl.href = `https://arxiv.org/abs/${arxivId}`;
      panel.hidden = false;
      body.innerHTML = `<div class="review-loading">加载精读…</div>`;
      await loadIndex();
      try {
        await showMarkdown(currentId);
        return;
      } catch (e) { /* 未生成,走下面的分支 */ }
      const hasApi = await detectApi();
      if (hasApi) {
        renderGeneratePrompt(currentId, "当前为本地模式,可以直接生成。");
      } else {
        renderGeneratePrompt(
          currentId,
          "当前是 GitHub Pages 静态站点,无法在此生成精读(生成需要本机 agy)。请在本地运行 viewer/run_viewer.py 后再点生成。"
        );
        const btn = document.getElementById("genReviewBtn");
        if (btn) btn.hidden = true;
      }
    },
    close,
  };

  document.getElementById("reviewCloseBtn").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
})();
