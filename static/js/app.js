let priceChart = null;

const form = document.getElementById("searchForm");
const symbolInput = document.getElementById("symbolInput");
const loading = document.getElementById("loading");
const errorBox = document.getElementById("error");
const result = document.getElementById("result");

function formatMarketCap(value) {
  if (!value) return "-";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return `$${value.toLocaleString()}`;
}

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.classList.remove("hidden");
  result.classList.add("hidden");
}

function hideError() {
  errorBox.classList.add("hidden");
}

async function analyze(symbol) {
  if (!symbol.trim()) {
    showError("종목 코드를 입력해 주세요.");
    return;
  }

  hideError();
  result.classList.add("hidden");
  loading.classList.remove("hidden");

  try {
    const res = await fetch(`/api/analyze?symbol=${encodeURIComponent(symbol.trim())}`);
    const data = await res.json();

    if (!res.ok) {
      showError(data.error || "분석에 실패했습니다.");
      return;
    }

    renderResult(data);
  } catch {
    showError("서버 연결에 실패했습니다.");
  } finally {
    loading.classList.add("hidden");
  }
}

function renderResult(data) {
  document.getElementById("stockName").textContent = data.name;
  document.getElementById("stockSymbol").textContent = data.symbol;
  document.getElementById("stockPrice").textContent = `$${data.price.toLocaleString()}`;

  const changeEl = document.getElementById("stockChange");
  const sign = data.change_pct >= 0 ? "+" : "";
  changeEl.textContent = `${sign}${data.change_pct}%`;
  changeEl.className = "stock-change " + (data.change_pct > 0 ? "up" : data.change_pct < 0 ? "down" : "flat");

  const scoreCircle = document.getElementById("scoreCircle");
  scoreCircle.className = `score-circle ${data.sentiment}`;
  document.getElementById("scoreValue").textContent = data.score;

  const recEl = document.getElementById("recommendation");
  recEl.textContent = data.recommendation;
  recEl.className = `recommendation ${data.sentiment}`;

  const signalsEl = document.getElementById("signals");
  signalsEl.innerHTML = data.signals.map((s) => `<li>${s}</li>`).join("");

  document.getElementById("marketCap").textContent = formatMarketCap(data.market_cap);
  document.getElementById("peRatio").textContent = data.pe_ratio ? data.pe_ratio.toFixed(2) : "-";

  renderChart(data.history);
  result.classList.remove("hidden");
}

function renderChart(history) {
  const ctx = document.getElementById("priceChart").getContext("2d");

  if (priceChart) {
    priceChart.destroy();
  }

  priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: history.map((h) => h.date),
      datasets: [{
        label: "종가",
        data: history.map((h) => h.close),
        borderColor: "#38bdf8",
        backgroundColor: "rgba(56, 189, 248, 0.1)",
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: {
          ticks: { color: "#64748b", font: { size: 10 }, maxTicksLimit: 8 },
          grid: { color: "#334155" },
        },
        y: {
          ticks: { color: "#64748b", font: { size: 10 } },
          grid: { color: "#334155" },
        },
      },
    },
  });
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  analyze(symbolInput.value);
});

document.querySelectorAll(".quick-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const symbol = btn.dataset.symbol;
    symbolInput.value = symbol;
    analyze(symbol);
  });
});
