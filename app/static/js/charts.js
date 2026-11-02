// Chart.js views. Data comes from the server as JSON in #chart-data; amounts
// arrive as exact decimal strings and are only converted to numbers to draw.
(() => {
  const dataElement = document.getElementById("chart-data");
  if (!dataElement || typeof Chart === "undefined") return;

  const data = JSON.parse(dataElement.textContent);
  const currency = { style: "currency", currency: data.currency.code };
  const money = new Intl.NumberFormat(data.currency.locale, currency);
  const compact = new Intl.NumberFormat(data.currency.locale, {
    ...currency, notation: "compact", maximumFractionDigits: 1,
  });

  const css = getComputedStyle(document.documentElement);
  const token = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  const GAIN = token("--gain", "#1f7a55");
  const LOSS = token("--loss", "#b4452f");
  const BRAND = token("--brand", "#1f5c4a");
  const INK = token("--ink", "#16241f");
  const SOFT = token("--ink-soft", "#55645d");
  const GRID = "rgba(22, 36, 31, 0.08)";
  // Distinct hues for category slices; the last (grey) is reserved for "Other".
  const PALETTE = ["#1f5c4a", "#b4452f", "#c58b2a", "#3d6f9e", "#7a4d8c", "#4f9a8a", "#8a6d3b", "#9a9a8e"];

  Chart.defaults.font.family = token("--font-body", "system-ui, sans-serif").replace(/^"|"$/g, "");
  Chart.defaults.color = SOFT;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) Chart.defaults.animation = false;

  // null stays null (a gap in a line); Number(null) would silently become 0.
  const numbers = (values) => values.map((v) => (v === null ? null : Number(v)));
  const legendMarkers = { usePointStyle: true, boxWidth: 9, boxHeight: 9, padding: 14 };
  const baseOptions = { responsive: true, maintainAspectRatio: false };
  const moneyAxis = {
    beginAtZero: true,
    grid: { color: GRID },
    ticks: { callback: (value) => compact.format(value) },
  };

  const builders = {
    // Grouped bars: income next to expenses for each month.
    incomeExpense(canvas, d) {
      new Chart(canvas, {
        type: "bar",
        data: {
          labels: d.labels,
          datasets: [
            { label: "Income", data: numbers(d.income), backgroundColor: GAIN, borderRadius: 4 },
            { label: "Expenses", data: numbers(d.expenses), backgroundColor: LOSS, borderRadius: 4 },
          ],
        },
        options: {
          ...baseOptions,
          scales: { y: moneyAxis, x: { grid: { display: false } } },
          plugins: {
            legend: { position: "bottom", labels: { ...legendMarkers, pointStyle: "rectRounded" } },
            tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${money.format(c.parsed.y)}` } },
          },
        },
      });
    },

    // Net cash flow each month, plus the running total.
    netFlow(canvas, d) {
      new Chart(canvas, {
        type: "line",
        data: {
          labels: d.labels,
          datasets: [
            { label: "Net per month", data: numbers(d.net), borderColor: BRAND, backgroundColor: BRAND,
              tension: 0.25, pointRadius: 3 },
            { label: "Running net", data: numbers(d.cumulative), borderColor: INK, backgroundColor: INK,
              borderDash: [6, 4], tension: 0.25, pointRadius: 0 },
          ],
        },
        options: {
          ...baseOptions,
          interaction: { mode: "index", intersect: false },
          scales: { y: { ...moneyAxis, beginAtZero: false }, x: { grid: { display: false } } },
          plugins: {
            legend: { position: "bottom", labels: { ...legendMarkers, pointStyle: "line" } },
            tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${money.format(c.parsed.y)}` } },
          },
        },
      });
    },

    // Share of spending by category.
    category(canvas, d) {
      new Chart(canvas, {
        type: "doughnut",
        data: {
          labels: d.labels,
          datasets: [{
            data: numbers(d.values),
            backgroundColor: d.labels.map((_, i) => PALETTE[i % PALETTE.length]),
            borderColor: "#fffdf8", borderWidth: 2,
          }],
        },
        options: {
          ...baseOptions, cutout: "58%",
          plugins: {
            legend: { position: "bottom", labels: { ...legendMarkers, pointStyle: "rectRounded" } },
            tooltip: { callbacks: { label: (c) => ` ${c.label}: ${money.format(c.parsed)} (${d.shares[c.dataIndex]}%)` } },
          },
        },
      });
    },

  };

  document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
    const build = builders[canvas.dataset.chart];
    const source = data[canvas.dataset.source || canvas.dataset.chart];
    if (build && source) build(canvas, source);
  });
})();
