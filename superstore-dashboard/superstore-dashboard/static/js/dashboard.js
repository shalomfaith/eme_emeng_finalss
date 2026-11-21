/* Dashboard front end: reads filter state, calls /api/dashboard, redraws charts. */
(() => {
  "use strict";

  const COLORS = { sales: "#2f5d8a", profit: "#0f766e", quantity: "#6b5b95", loss: "#b42318", grid: "#e3e8ec", muted: "#5a6b7b" };
  const LABELS = { sales: "Sales", profit: "Profit", quantity: "Units sold" };
  const DIM_LABELS = {
    category: "category", sub_category: "sub-category", region: "region",
    segment: "segment", ship_mode: "ship mode", state: "state",
  };

  const state = { years: [], allYears: [], region: "", category: "", segment: "", metric: "sales", dim: "category" };
  const charts = {};
  const $ = (sel) => document.querySelector(sel);

  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const moneyCompact = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
  const integer = new Intl.NumberFormat("en-US");
  const fmt = (metric, v, compact = false) =>
    metric === "quantity" ? integer.format(v) : (compact ? moneyCompact : money).format(v);
  const pct = (v) => `${v.toFixed(1)}%`;

  if (window.Chart) {
    Chart.defaults.font.family = '"Manrope", system-ui, sans-serif';
    Chart.defaults.color = COLORS.muted;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) Chart.defaults.animation = false;
  }

  /* ---------- filters ---------- */
  function fillSelect(el, label, values) {
    el.innerHTML = "";
    el.append(new Option(`All ${label}`, ""));
    values.forEach((v) => el.append(new Option(v, v)));
  }

  async function initFilters() {
    const res = await fetch("/api/filters");
    if (!res.ok) throw new Error("Could not load filter options.");
    const f = await res.json();
    state.allYears = f.years;
    state.years = [...f.years];

    const box = $("#yearChecks");
    box.innerHTML = "";
    f.years.forEach((y) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox"; input.value = y; input.checked = true;
      label.append(input, String(y));
      box.append(label);
    });
    box.addEventListener("change", (e) => {
      const checked = [...box.querySelectorAll("input:checked")].map((i) => Number(i.value));
      if (!checked.length) { e.target.checked = true; return; }   // always keep at least one year
      state.years = checked;
      load();
    });

    fillSelect($("#region"), "regions", f.regions);
    fillSelect($("#category"), "categories", f.categories);
    fillSelect($("#segment"), "segments", f.segments);
    ["region", "category", "segment"].forEach((k) =>
      $("#" + k).addEventListener("change", (e) => { state[k] = e.target.value; load(); }));

    $("#reset").addEventListener("click", () => {
      state.years = [...state.allYears]; state.region = state.category = state.segment = "";
      box.querySelectorAll("input").forEach((i) => (i.checked = true));
      ["region", "category", "segment"].forEach((k) => ($("#" + k).value = ""));
      load();
    });

    document.querySelectorAll("[data-metric]").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.metric = btn.dataset.metric;
        document.querySelectorAll("[data-metric]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        load();
      }));
    $("#dim").addEventListener("change", (e) => { state.dim = e.target.value; load(); });
  }

  /* ---------- data loading ---------- */
  let controller = null;
  function query() {
    const p = new URLSearchParams({ metric: state.metric, dim: state.dim });
    if (state.years.length && state.years.length < state.allYears.length) p.set("years", state.years.join(","));
    if (state.region) p.set("regions", state.region);
    if (state.category) p.set("categories", state.category);
    if (state.segment) p.set("segments", state.segment);
    return p.toString();
  }

  function setStatus(kind, text = "") {
    const el = $("#status");
    el.hidden = !kind;
    el.className = "status" + (kind === "loading" ? " loading" : "");
    el.textContent = text;
  }

  async function load() {
    if (controller) controller.abort();          // ignore stale responses when filters change quickly
    controller = new AbortController();
    setStatus("loading", "Updating…");
    try {
      const res = await fetch("/api/dashboard?" + query(), { signal: controller.signal });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || res.statusText);
      }
      render(await res.json());
      setStatus(null);
    } catch (err) {
      if (err.name === "AbortError") return;
      setStatus("error", `Could not update the dashboard: ${err.message}`);
    }
  }

  /* ---------- rendering ---------- */
  function mount(id, config) {
    if (charts[id]) {
      charts[id].data = config.data;
      charts[id].options = config.options;
      charts[id].update();
    } else {
      charts[id] = new Chart($("#" + id), config);
    }
  }

  const baseScales = (metric, horizontal = false) => {
    const value = { grid: { color: COLORS.grid }, ticks: { callback: (v) => fmt(metric, v, true) }, border: { display: false } };
    const cat = { grid: { display: false }, ticks: { autoSkip: false } };
    return horizontal ? { x: value, y: cat } : { x: cat, y: value };
  };

  function renderSummary(d) {
    const yrs = state.years.length === state.allYears.length
      ? `${state.allYears[0]} to ${state.allYears.at(-1)}`
      : [...state.years].sort().join(", ");
    const parts = [yrs, state.region || "all regions", state.category || "all categories", state.segment ? `${state.segment} customers` : "all segments"];
    $("#summary").textContent = `Showing ${parts.join(", ")}.`;
    $("#rowCount").textContent = `${integer.format(d.rows)} order lines match.`;
  }

  function renderKpis(k) {
    const growth = (g, label) => g == null ? "" : `<span class="${g >= 0 ? "up" : "down"}">${g >= 0 ? "+" : ""}${g}%</span> ${label}`;
    const items = [
      ["Sales", fmt("sales", k.sales, true), growth(k.sales_growth, k.growth_label || "")],
      ["Profit", fmt("profit", k.profit, true), growth(k.profit_growth, k.growth_label || ""), k.profit < 0],
      ["Profit margin", pct(k.margin), `${pct(k.loss_share)} of lines lose money`],
      ["Orders", integer.format(k.orders), `${integer.format(k.customers)} customers`],
      ["Average order", money.format(k.avg_order_value), ""],
      ["Time to ship", `${k.avg_ship_days} days`, "order date to ship date"],
    ];
    $("#kpis").innerHTML = items.map(([label, value, delta, neg]) =>
      `<div class="fig"><div class="label">${label}</div><div class="value${neg ? " neg" : ""}">${value}</div><div class="delta">${delta}</div></div>`
    ).join("");
  }

  function renderInsights(list) {
    const ul = $("#insights");
    ul.innerHTML = "";
    list.forEach((t) => { const li = document.createElement("li"); li.textContent = t; ul.append(li); });
  }

  function renderTrend(t) {
    const m = state.metric, color = COLORS[m];
    $("#trendTitle").textContent = `Monthly ${LABELS[m].toLowerCase()}`;
    mount("trendChart", {
      type: "line",
      data: {
        labels: t.labels,
        datasets: [
          { label: LABELS[m], data: t.values, borderColor: color, backgroundColor: color + "22", fill: true, tension: 0.25, pointRadius: 2, pointHoverRadius: 5, borderWidth: 2 },
          { label: "3-month average", data: t.moving_avg, borderColor: color, borderDash: [6, 4], pointRadius: 0, borderWidth: 2, tension: 0.3 },
          { label: "Linear trend", data: t.trend, borderColor: COLORS.muted, borderDash: [2, 3], pointRadius: 0, borderWidth: 1.5 },
        ],
      },
      options: {
        maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 12 } }, y: { grid: { color: COLORS.grid }, border: { display: false }, ticks: { callback: (v) => fmt(m, v, true) } } },
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(m, c.parsed.y)}` } } },
      },
    });
  }

  const signColors = (values, base) => values.map((v) => (v < 0 ? COLORS.loss : base));

  function renderBreakdown(b) {
    const m = state.metric;
    $("#breakTitle").textContent = `${LABELS[m]} by ${DIM_LABELS[state.dim]}`;
    const data = b[m];
    mount("breakChart", {
      type: "bar",
      data: { labels: b.labels, datasets: [{ label: LABELS[m], data, backgroundColor: signColors(data, COLORS[m]), borderRadius: 3 }] },
      options: {
        indexAxis: "y", maintainAspectRatio: false, scales: baseScales(m, true),
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: (c) => `${LABELS[m]}: ${fmt(m, c.parsed.x)}`,
          afterLabel: (c) => [`Sales: ${money.format(b.sales[c.dataIndex])}`, `Profit: ${money.format(b.profit[c.dataIndex])}`, `Margin: ${pct(b.margin[c.dataIndex])}`],
        } } },
      },
    });
  }

  function renderDiscount(rows) {
    const margins = rows.map((r) => r.margin);
    mount("discountChart", {
      type: "bar",
      data: { labels: rows.map((r) => r.band), datasets: [{ label: "Profit margin", data: margins, backgroundColor: signColors(margins, COLORS.profit), borderRadius: 3 }] },
      options: {
        maintainAspectRatio: false,
        scales: { x: { grid: { display: false }, title: { display: true, text: "Discount given" } }, y: { grid: { color: COLORS.grid }, border: { display: false }, ticks: { callback: (v) => v + "%" } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: (c) => `Margin: ${pct(c.parsed.y)}`,
          afterLabel: (c) => { const r = rows[c.dataIndex]; return [`Order lines: ${integer.format(r.lines)}`, `Sales: ${money.format(r.sales)}`, `Profit: ${money.format(r.profit)}`, `Lines at a loss: ${pct(r.loss_share)}`]; },
        } } },
      },
    });
  }

  function renderSubcategories(s) {
    const order = s.labels.map((l, i) => ({ l, p: s.profit[i], sales: s.sales[i], mg: s.margin[i] })).sort((a, b) => b.p - a.p);
    mount("subChart", {
      type: "bar",
      data: { labels: order.map((o) => o.l), datasets: [{ label: "Profit", data: order.map((o) => o.p), backgroundColor: signColors(order.map((o) => o.p), COLORS.profit), borderRadius: 3 }] },
      options: {
        indexAxis: "y", maintainAspectRatio: false, scales: baseScales("profit", true),
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: (c) => `Profit: ${money.format(c.parsed.x)}`,
          afterLabel: (c) => [`Sales: ${money.format(order[c.dataIndex].sales)}`, `Margin: ${pct(order[c.dataIndex].mg)}`],
        } } },
      },
    });
  }

  function renderWorst(rows) {
    const body = $("#worstBody");
    body.innerHTML = "";
    if (!rows.length) { body.innerHTML = '<tr><td colspan="4">No products match these filters.</td></tr>'; return; }
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      const name = document.createElement("td");
      name.textContent = r.product;
      const small = document.createElement("small");
      small.textContent = r.sub_category;
      name.append(small);
      tr.append(name);
      [`${r.avg_discount}%`, money.format(r.sales), money.format(r.profit)].forEach((txt, i) => {
        const td = document.createElement("td");
        td.className = "num" + (i === 2 ? " down" : "");
        td.textContent = txt;
        tr.append(td);
      });
      body.append(tr);
    });
  }

  function render(d) {
    renderSummary(d);
    renderKpis(d.kpis);
    renderInsights(d.insights);
    renderTrend(d.trend);
    renderBreakdown(d.breakdown);
    renderDiscount(d.discount);
    renderSubcategories(d.subcategories);
    renderWorst(d.worst_products);
  }

  /* ---------- start ---------- */
  document.addEventListener("DOMContentLoaded", async () => {
    if (!window.Chart) { setStatus("error", "Charts could not load. Check your internet connection (Chart.js is loaded from a CDN) and refresh."); return; }
    try { await initFilters(); await load(); }
    catch (err) { setStatus("error", err.message); }
  });
})();
