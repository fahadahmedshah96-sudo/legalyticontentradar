const DATA_FILES = {
  config: "data/config.json",
  content: "data/competitor_content.json",
  news: "data/competitor_news.json",
  ideas: "data/content_opportunities.json",
  ai_ideas: "data/generated_opportunities.json"
};

const esc = (v = "") => String(v).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
const displayDate = v => {
  if (!v) return "Date not found";
  const d = new Date(v);
  return Number.isNaN(d.valueOf()) ? v : new Intl.DateTimeFormat("en-US", {year:"numeric",month:"short",day:"numeric",timeZone:"UTC"}).format(d);
};
const safeHost = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return "Source"; } };
let state = {config:{}, content:[], news:[], ideas:[]};

async function loadData() {
  const entries = await Promise.all(Object.entries(DATA_FILES).map(async ([key, url]) => {
    const response = await fetch(url, {cache:"no-store"});
    if (!response.ok) throw new Error(`Could not load ${url}: ${response.status}`);
    return [key, await response.json()];
  }));
  state = Object.fromEntries(entries);
  renderAll();
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(tab => {
      const active = tab === button;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.add("hidden"));
    document.getElementById(`panel-${button.dataset.tab}`).classList.remove("hidden");
  }));
}

function populateFilters() {
  const clusters = [...new Set(state.content.map(x => x.query_cluster))].sort();
  const contentFilter = document.getElementById("content-filter");
  clusters.forEach(value => contentFilter.insertAdjacentHTML("beforeend", `<option value="${esc(value)}">${esc(value)}</option>`));
  contentFilter.addEventListener("change", renderContent);
  document.getElementById("content-sort").addEventListener("change", renderContent);

  const competitors = [...new Set(state.news.map(x => x.competitor))].sort();
  const newsFilter = document.getElementById("news-filter");
  competitors.forEach(value => newsFilter.insertAdjacentHTML("beforeend", `<option value="${esc(value)}">${esc(value)}</option>`));
  newsFilter.addEventListener("change", renderNews);

  const allIdeas = [...state.ideas, ...state.ai_ideas];
  const types = [...new Set(allIdeas.map(x => x.content_type))].sort();
  const ideaFilter = document.getElementById("idea-filter");
  types.forEach(value => ideaFilter.insertAdjacentHTML("beforeend", `<option value="${esc(value)}">${esc(value)}</option>`));
  ideaFilter.addEventListener("change", renderIdeas);
}

function renderContent() {
  const cluster = document.getElementById("content-filter").value;
  const sort = document.getElementById("content-sort").value;
  const rows = state.content.filter(x => cluster === "all" || x.query_cluster === cluster);
  rows.sort((a,b) => sort === "discovery"
    ? a.query_cluster.localeCompare(b.query_cluster) || a.discovery_order - b.discovery_order
    : String(b.last_updated || b.published_date || "").localeCompare(String(a.last_updated || a.published_date || "")));
  const el = document.getElementById("content-list");
  if (!rows.length) { el.innerHTML = `<div class="empty">No pages match this filter.</div>`; return; }
  el.innerHTML = rows.map(item => `
    <article class="content-card">
      <div class="card-top">
        <div>
          <h3 class="card-title"><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
          <div class="meta"><span>${esc(item.competitor)}</span><span>${esc(item.page_type)}</span><span>Published ${esc(displayDate(item.published_date))}${item.last_updated ? ` · updated ${esc(displayDate(item.last_updated))}` : ""}</span></div>
        </div>
        <span class="tag purple">${esc(item.relevance)} relevance</span>
      </div>
      <div class="meta"><span>Query cluster: <strong>${esc(item.query_cluster)}</strong></span><span>Seed query: ${esc(item.seed_query)}</span><span>Discovery order ${esc(item.discovery_order)} · not Google rank</span></div>
      <p class="card-summary">${esc(item.observed_summary)}</p>
      <div class="card-grid">
        <div class="detail-box"><div class="detail-label">Why relevant</div><div class="detail-text">${esc(item.relevance_reason)}</div></div>
        <div class="detail-box"><div class="detail-label">Legalyti response hypothesis</div><div class="detail-text">${esc(item.response_hypothesis)}</div></div>
      </div>
    </article>`).join("");
}

function renderNews() {
  const competitor = document.getElementById("news-filter").value;
  const rows = state.news.filter(x => competitor === "all" || x.competitor === competitor).sort((a,b) => String(b.published_date).localeCompare(String(a.published_date)));
  const el = document.getElementById("news-list");
  if (!rows.length) { el.innerHTML = `<div class="empty">No verified competitor company-news items are in this snapshot. Add competitor press or news listing URLs to <code>data/news_sources.json</code>; the refresh workflow can then monitor those sources.</div>`; return; }
  el.innerHTML = rows.map(item => `
    <article class="news-card">
      <div class="card-top"><div><h3 class="card-title"><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3><div class="meta"><span>${esc(item.competitor)}</span><span>${esc(displayDate(item.published_date))}</span><span>${esc(item.source_type)}</span></div></div><span class="tag green">${esc(item.news_type)}</span></div>
      <p class="card-summary">${esc(item.summary)}</p>
      <div class="detail-box" style="margin-top:12px"><div class="detail-label">Why it may matter</div><div class="detail-text">${esc(item.why_it_matters)}</div></div>
    </article>`).join("");
}

function renderIdeas() {
  const type = document.getElementById("idea-filter").value;
  const rows = [...state.ideas, ...state.ai_ideas].filter(x => type === "all" || x.content_type === type);
  const el = document.getElementById("opportunity-list");
  if (!rows.length) { el.innerHTML = `<div class="empty">No recommendations match this filter.</div>`; return; }
  el.innerHTML = rows.map(item => `
    <article class="idea-card">
      <div class="idea-header"><div><h3>${esc(item.title)}</h3><p>${esc(item.action)} · ${esc(item.content_type)} · ${esc(item.query_cluster)}</p></div><span class="priority ${item.priority === "Medium" ? "medium" : ""}">${esc(item.priority)} priority</span></div>
      <div class="idea-details">
        <div class="detail-box"><div class="detail-label">Observed competitor pattern</div><div class="detail-text">${esc(item.observed_competitor_pattern)}</div></div>
        <div class="detail-box"><div class="detail-label">Possible Legalyti angle</div><div class="detail-text">${esc(item.legalyti_angle)}</div></div>
        <div class="detail-box"><div class="detail-label">Next step and review</div><div class="detail-text">${esc(item.next_step)} <strong>Review:</strong> ${esc(item.review_required.join(", "))}.</div></div>
      </div>
      <div class="meta"><span>Demand: ${esc(item.search_demand)}</span><span>Priority basis: ${esc(item.priority_basis)}</span><span>${esc(item.status)}</span></div>
      <div class="source-links">${item.evidence_urls.map(url => `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(safeHost(url))} ↗</a>`).join("")}</div>
    </article>`).join("");
}

function renderAll() {
  document.getElementById("count-content").textContent = state.content.length;
  document.getElementById("count-news").textContent = state.news.length;
  document.getElementById("count-ideas").textContent = state.ideas.length + state.ai_ideas.length;
  document.getElementById("tab-count-content").textContent = state.content.length;
  document.getElementById("tab-count-news").textContent = state.news.length;
  document.getElementById("tab-count-ideas").textContent = state.ideas.length + state.ai_ideas.length;
  document.getElementById("data-status").textContent = state.config.data_status;
  populateFilters(); renderContent(); renderNews(); renderIdeas();
}

setupTabs();
loadData().catch(error => {
  document.getElementById("data-status").textContent = "Could not load dashboard data.";
  document.getElementById("content-list").innerHTML = `<div class="empty">${esc(error.message)} Start a local server from the project folder to load the JSON files.</div>`;
});
