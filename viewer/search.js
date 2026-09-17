// 轻量检索:中文按"非重叠二元组"切分,英文按词;同一查询词的所有子串必须命中(AND)。
// 例:"道路高程" -> 需要同时包含「道路」与「高程」,而不是死板要求连续出现。
(function () {
  function subTerms(part) {
    if (part.length <= 3) return [part];
    const subs = [];
    for (let i = 0; i + 1 < part.length; i += 2) subs.push(part.slice(i, i + 2));
    if (part.length % 2 === 1) subs.push(part.slice(-2));
    return Array.from(new Set(subs));
  }

  function tokenize(query) {
    const terms = [];
    const q = (query || "").trim().toLowerCase();
    if (!q) return terms;
    for (const part of q.split(/[\s,，、;；]+/)) {
      if (!part) continue;
      terms.push(subTerms(part));
    }
    return terms;
  }

  function matches(paper, terms) {
    const text = paper.search_text || "";
    const title = (paper.title || "").toLowerCase();
    const kws = (paper.keywords || []).join(" ").toLowerCase();
    let score = 0;
    for (const subs of terms) {
      for (const s of subs) {
        if (!text.includes(s)) return null;
        score += s.length;
        if (title.includes(s) || kws.includes(s)) score += 4; // 标题/标签命中优先
      }
    }
    return score;
  }

  window.paperSearch = {
    tokenize,
    filter(papers, query) {
      const terms = tokenize(query);
      if (!terms.length) return papers;
      const scored = [];
      papers.forEach((p, idx) => {
        const s = matches(p, terms);
        if (s !== null) scored.push({ p, s, idx });
      });
      scored.sort((a, b) => (b.s - a.s) || (a.idx - b.idx));
      return scored.map((x) => x.p);
    },
  };
})();
