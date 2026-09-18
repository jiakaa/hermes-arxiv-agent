let allPapers = [];
let localMode = false;
let favorites = new Set();
const FAVORITES_STORAGE_KEY = "hermes-arxiv-agent:favorites";

const state = {
  dateMode: "crawled_date",
  start: "",
  end: "",
  keyword: "",
  ratingSet: new Set(),
  tagSet: new Set(),
  favoriteOnly: false,
};

function loadFavorites() {
  try {
    const raw = window.localStorage.getItem(FAVORITES_STORAGE_KEY);
    const payload = raw ? JSON.parse(raw) : [];
    const arr = Array.isArray(payload) ? payload : [];
    favorites = new Set(arr.map((x) => String(x)));
  } catch (err) {
    console.warn("加载本地收藏失败", err);
    favorites = new Set();
  }
}

function saveFavorites() {
  try {
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(Array.from(favorites)));
  } catch (err) {
    throw new Error(`保存收藏失败: ${err.message || err}`);
  }
}

function isFavorite(arxivId) {
  return favorites.has(String(arxivId));
}

async function toggleFavorite(arxivId) {
  const key = String(arxivId);
  if (favorites.has(key)) {
    favorites.delete(key);
  } else {
    favorites.add(key);
  }
  await saveFavorites();
}

function text(v) {
  return (v || "").toString();
}

function formatDate(date) {
  const y = date.getFullYear();
  const m = `${date.getMonth() + 1}`.padStart(2, "0");
  const d = `${date.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function daysAgo(baseDate, days) {
  const d = new Date(baseDate);
  d.setDate(d.getDate() - days);
  return d;
}

function inRange(dateValue, start, end) {
  if (!dateValue) {
    return false;
  }
  if (start && dateValue < start) {
    return false;
  }
  if (end && dateValue > end) {
    return false;
  }
  return true;
}

function renderRatingBadge(node, rating) {
  const el = node.querySelector(".rating-badge");
  el.textContent = rating || "";
  el.dataset.r = rating || "";
  el.hidden = !rating;
}

function renderTags(node, paper, onTagClick) {
  const wrap = node.querySelector(".tags");
  wrap.innerHTML = "";

  (paper.keywords || []).forEach((kw) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tag tag-clickable" + (state.tagSet.has(kw) ? " active" : "");
    b.textContent = kw;
    b.addEventListener("click", () => onTagClick(kw));
    wrap.appendChild(b);
  });

  text(paper.categories)
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .forEach((cat) => {
      const span = document.createElement("span");
      span.className = "tag tag-cat";
      span.textContent = cat;
      wrap.appendChild(span);
    });
}

function renderCards(papers) {
  const container = document.getElementById("cards");
  container.innerHTML = "";

  if (!papers.length) {
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = "当前筛选条件下没有论文。";
    container.appendChild(div);
    return;
  }

  const tpl = document.getElementById("paperTpl");
  papers.forEach((p) => {
    const node = tpl.content.cloneNode(true);

    node.querySelector(".pill").textContent = p.arxiv_id;
    renderRatingBadge(node, p.rating);

    const title = node.querySelector(".title");
    title.textContent = text(p.title) || p.arxiv_id;
    // 本地模式(有本机服务)优先打开已下载的 PDF;远端 Pages 上退回 arXiv 摘要页
    title.href = localMode
      ? `pdf/${encodeURIComponent(p.arxiv_id)}`
      : `https://arxiv.org/abs/${p.arxiv_id}`;
    title.title = localMode ? "打开本机已下载的 PDF" : "打开 arXiv 摘要页";

    const favBtn = node.querySelector(".favorite-btn");
    const favored = isFavorite(p.arxiv_id);
    favBtn.classList.toggle("active", favored);
    favBtn.textContent = favored ? "★ 已收藏" : "☆ 收藏";
    favBtn.addEventListener("click", async () => {
      favBtn.disabled = true;
      try {
        await toggleFavorite(p.arxiv_id);
        applyFilter();
      } catch (err) {
        alert(err.message || "保存收藏失败");
      } finally {
        favBtn.disabled = false;
      }
    });

    node.querySelector(".meta").textContent =
      `抓取: ${text(p.crawled_date) || "-"} | 发表: ${text(p.published_date) || "-"}` +
      `\n单位: ${text(p.affiliations) || "未提供"}` +
      `\n作者: ${text(p.authors) || "-"}`;

    renderTags(node, p, (kw) => {
      if (state.tagSet.has(kw)) {
        state.tagSet.delete(kw);
      } else {
        state.tagSet.add(kw);
      }
      syncTagCloud();
      applyFilter();
    });

    node.querySelector(".summary-cn").textContent = text(p.summary_cn) || "未提供";
    node.querySelector(".abstract").textContent = text(p.abstract) || "未提供";

    const rvBtn = node.querySelector(".review-btn");
    if (window.paperReview.hasReview(p.arxiv_id)) {
      rvBtn.textContent = "精读(已有)";
      rvBtn.classList.add("has-review");
    }
    rvBtn.addEventListener("click", () => window.paperReview.open(p.arxiv_id, p.title));

    container.appendChild(node);
  });
}

function renderTagCloud(tags) {
  const el = document.getElementById("tagCloud");
  el.innerHTML = "";
  if (!tags.length) {
    el.textContent = "暂无标签";
    return;
  }
  tags.forEach((t) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tag-chip" + (state.tagSet.has(t.name) ? " active" : "");
    b.dataset.tag = t.name;
    b.textContent = `${t.name} ${t.count}`;
    b.addEventListener("click", () => {
      if (state.tagSet.has(t.name)) {
        state.tagSet.delete(t.name);
      } else {
        state.tagSet.add(t.name);
      }
      syncTagCloud();
      applyFilter();
    });
    el.appendChild(b);
  });
}

function syncTagCloud() {
  document.querySelectorAll("#tagCloud .tag-chip").forEach((b) => {
    b.classList.toggle("active", state.tagSet.has(b.dataset.tag));
  });
}

function ratingSummary() {
  if (!state.ratingSet.size) return "全部";
  return Array.from(state.ratingSet).sort().join("+");
}

function tagOverlap(paper) {
  if (!state.tagSet.size) return 0;
  return (paper.keywords || []).filter((k) => state.tagSet.has(k)).length;
}

function applyFilter() {
  const s = state;
  let papers = allPapers.filter((p) =>
    inRange(text(p[s.dateMode]), s.start, s.end) &&
    (s.ratingSet.size === 0 || s.ratingSet.has(text(p.rating))) &&
    tagOverlap(p) === s.tagSet.size &&
    (!s.favoriteOnly || isFavorite(p.arxiv_id))
  );
  papers = window.paperSearch.filter(papers, s.keyword);
  renderCards(papers);

  const summary = document.getElementById("summary");
  summary.textContent = [
    `共 ${allPapers.length} 篇`,
    `当前展示 ${papers.length} 篇`,
    `评级: ${ratingSummary()}`,
    s.tagSet.size ? `标签: ${Array.from(s.tagSet).join(" + ")}` : "标签: 不限",
    `日期: ${s.dateMode === "crawled_date" ? "抓取" : "发表"} ${s.start || "…"} ~ ${s.end || "…"}`,
    `收藏 ${favorites.size} 篇`,
  ].join(" | ");
}

function resetFilter(defaultMin, defaultMax) {
  state.dateMode = "crawled_date";
  state.start = defaultMin || "";
  state.end = defaultMax || "";
  state.keyword = "";
  state.favoriteOnly = false;
  state.ratingSet.clear();
  state.tagSet.clear();

  document.getElementById("dateMode").value = state.dateMode;
  document.getElementById("startDate").value = state.start;
  document.getElementById("endDate").value = state.end;
  document.getElementById("keyword").value = "";
  document.getElementById("favoriteOnly").checked = false;
  document.querySelectorAll("#ratingChips .chip").forEach((b) => {
    b.classList.toggle("active", b.dataset.rating === "");
  });
  syncTagCloud();
  applyFilter();
}

function applyQuickRange(range) {
  const today = new Date();
  const end = formatDate(today);
  if (range === "all") {
    state.start = "";
    state.end = "";
  } else if (range === "today") {
    state.start = end;
    state.end = end;
  } else if (range === "3d") {
    state.start = formatDate(daysAgo(today, 2));
    state.end = end;
  } else if (range === "7d") {
    state.start = formatDate(daysAgo(today, 6));
    state.end = end;
  }
  document.getElementById("startDate").value = state.start;
  document.getElementById("endDate").value = state.end;
  applyFilter();
}

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function init() {
  const res = await fetch("papers_data.json", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`加载 papers_data.json 失败: HTTP ${res.status}`);
  }

  const payload = await res.json();
  allPapers = payload.papers || [];
  loadFavorites();
  await window.paperReview.loadIndex();
  localMode = await window.paperReview.detectApi();

  const defaultMin = payload.crawled_date_min || "";
  const defaultMax = payload.crawled_date_max || "";
  state.start = defaultMin;
  state.end = defaultMax;

  const counts = payload.rating_counts || {};
  document.getElementById("metaText").textContent =
    `收录 ${payload.count || allPapers.length} 篇 | 抓取区间 ${defaultMin || "-"} ~ ${defaultMax || "-"}` +
    ` | S ${counts.S || 0} / A ${counts.A || 0} / B ${counts.B || 0} / C ${counts.C || 0}`;

  document.getElementById("startDate").value = defaultMin;
  document.getElementById("endDate").value = defaultMax;

  renderTagCloud(payload.tags || []);

  document.getElementById("ratingChips").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-rating]");
    if (!btn) return;
    const r = btn.dataset.rating;
    if (r === "") {
      state.ratingSet.clear();
    } else if (state.ratingSet.has(r)) {
      state.ratingSet.delete(r);
    } else {
      state.ratingSet.add(r);
    }
    document.querySelectorAll("#ratingChips .chip").forEach((b) => {
      const active = b.dataset.rating === "" ? state.ratingSet.size === 0 : state.ratingSet.has(b.dataset.rating);
      b.classList.toggle("active", active);
    });
    applyFilter();
  });

  document.getElementById("dateMode").addEventListener("change", (e) => {
    state.dateMode = e.target.value;
    applyFilter();
  });
  document.getElementById("startDate").addEventListener("change", (e) => {
    state.start = e.target.value;
    applyFilter();
  });
  document.getElementById("endDate").addEventListener("change", (e) => {
    state.end = e.target.value;
    applyFilter();
  });
  document.getElementById("resetBtn").addEventListener("click", () => resetFilter(defaultMin, defaultMax));
  document.getElementById("favoriteOnly").addEventListener("change", (e) => {
    state.favoriteOnly = e.target.checked;
    applyFilter();
  });
  document.getElementById("quickRange").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-range]");
    if (!btn) return;
    applyQuickRange(btn.dataset.range);
  });

  const keywordInput = document.getElementById("keyword");
  keywordInput.addEventListener("input", debounce((e) => {
    state.keyword = e.target.value;
    applyFilter();
  }, 250));
  keywordInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.keyword = keywordInput.value;
      applyFilter();
    }
  });

  // 精读生成完成后刷新卡片徽章("精读" -> "精读(已有)")
  document.addEventListener("review:generated", () => applyFilter());

  applyFilter();
}

init().catch((err) => {
  const summary = document.getElementById("summary");
  if (summary) summary.textContent = err.message;
});
