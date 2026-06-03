const statusBody = document.getElementById("status-body");
const statusCount = document.getElementById("status-count");
const overrideSelect = document.getElementById("override-select");
const logStream = document.getElementById("log-stream");
const latencyCanvas = document.getElementById("latency-chart");
const throughputCanvas = document.getElementById("throughput-chart");

function fmt(value, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${Number(value).toFixed(1)}${suffix}`;
}

function dot(status) {
  const color = status === "healthy" ? "bg-emerald-400" : status === "degraded" ? "bg-amber-400" : status === "waiting_for_credentials" ? "bg-sky-400" : "bg-red-500";
  return `<span class="status-dot ${color}"></span>`;
}

async function refreshStatus() {
  const res = await fetch("/api/status");
  if (!res.ok) return;
  const data = await res.json();
  const rows = data.status || [];
  statusCount.textContent = `${rows.length} transports`;
  statusBody.innerHTML = rows.map(row => `
    <tr class="${row.active ? "bg-cyan-950/30" : ""}">
      <td class="px-3 py-2">${dot(row.status)}</td>
      <td class="px-3 py-2 font-medium">${row.name}<div class="text-xs text-zinc-500">${row.status}${row.last_error ? " · " + row.last_error : ""}</div></td>
      <td class="px-3 py-2 text-zinc-300">${row.mode}</td>
      <td class="px-3 py-2">${fmt(row.latency_ms, " ms")}</td>
      <td class="px-3 py-2">${fmt(row.jitter_ms, " ms")}</td>
      <td class="px-3 py-2">${fmt(row.packet_loss_pct, "%")}</td>
      <td class="px-3 py-2">${fmt(row.throughput_mbps, " Mb/s")}</td>
      <td class="px-3 py-2">${fmt(row.score)}</td>
      <td class="px-3 py-2">${row.active ? "Yes" : ""}</td>
    </tr>
  `).join("");
  const selected = data.manual_override || window.ATX_MANUAL_OVERRIDE || "";
  overrideSelect.innerHTML = `<option value="">Automatic</option>` + rows.map(row => `<option value="${row.name}" ${row.name === selected ? "selected" : ""}>${row.name}</option>`).join("");
}

async function refreshCharts() {
  const res = await fetch("/api/history?limit=160");
  if (!res.ok) return;
  const data = await res.json();
  drawChart(latencyCanvas, data.history || [], "latency_ms", "#22d3ee");
  drawChart(throughputCanvas, data.history || [], "throughput_mbps", "#34d399");
}

function drawChart(canvas, rows, key, color) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width = canvas.clientWidth * devicePixelRatio;
  const height = canvas.height = canvas.clientHeight * devicePixelRatio;
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#3f3f46";
  ctx.lineWidth = 1 * devicePixelRatio;
  for (let i = 0; i < 4; i++) {
    const y = (height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  const points = rows.filter(row => row[key] !== null && row[key] !== undefined).slice(-80);
  if (points.length < 2) return;
  const max = Math.max(...points.map(row => Number(row[key])), 1);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2 * devicePixelRatio;
  ctx.beginPath();
  points.forEach((row, idx) => {
    const x = (idx / (points.length - 1)) * width;
    const y = height - (Number(row[key]) / max) * (height - 8 * devicePixelRatio) - 4 * devicePixelRatio;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function connectLogs() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws/logs`);
  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    const line = `[${payload.ts || ""}] ${payload.level || "INFO"} ${payload.message || ""}`;
    logStream.textContent += `${line}\n`;
    logStream.scrollTop = logStream.scrollHeight;
  };
  ws.onclose = () => setTimeout(connectLogs, 3000);
}

refreshStatus();
refreshCharts();
setInterval(refreshStatus, 5000);
setInterval(refreshCharts, 15000);
connectLogs();
