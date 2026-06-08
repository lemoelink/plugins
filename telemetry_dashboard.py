"""
Telemetry & Dashboard Plugin for l3mcore (Enterprise Edition)
"""
import os
import json
import time
import threading
import tempfile
import csv
from io import StringIO
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string, Response, request as flask_request

TELEMETRY_FILE = os.path.join("logs", "telemetry.json")
HOURLY_BUCKETS = 24 * 7  # Keep up to 7 days
_lock = threading.Lock()

os.makedirs("logs", exist_ok=True)

# Price table: cost per 1M tokens in USD (Input, Output)
_COST_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o":              (5.0, 15.0),
    "gpt-4o-mini":         (0.15, 0.6),
    "gpt-4-turbo":         (10.0, 30.0),
    "gpt-3.5-turbo":       (0.5, 1.5),
    "claude-3-5-sonnet":   (3.0, 15.0),
    "claude-3-haiku":      (0.25, 1.25),
    "gemini-1.5-pro":      (3.5, 10.5),
    "gemini-1.5-flash":    (0.075, 0.3),
    "gemini-2.0-flash":    (0.1, 0.4),
}


def _empty_data():
    return {"experts": {}, "total_requests": 0, "hourly": {}}


def _read():
    try:
        with open(TELEMETRY_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if "hourly" not in d:
            d["hourly"] = {}
        return d
    except Exception:
        return _empty_data()


def _write(data: dict):
    fd, tmp = tempfile.mkstemp(dir="logs", prefix=".tel_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, TELEMETRY_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _hour_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")


def _prune_hourly(hourly: dict) -> dict:
    now_ts = time.time()
    cutoff = now_ts - HOURLY_BUCKETS * 3600
    return {
        k: v for k, v in hourly.items()
        if datetime.strptime(k, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc).timestamp() >= cutoff
    }


def record_telemetry(expert_label: str, latency_ms: float, prompt_tokens: int, completion_tokens: int, success: bool = True) -> None:
    if not isinstance(expert_label, str):
        return

    # Calculate precise cost
    cost_usd = 0.0
    try:
        import sys
        core_mod = sys.modules.get("api_server")
        if core_mod:
            from modules.config_manager import ConfigManager
            experts_cfg_path = ConfigManager().get("router", {}).get("categories_file", "config/experts.json")
            with open(experts_cfg_path, encoding="utf-8") as f:
                import json as _j
                experts_list = _j.load(f).get("experts", [])
            for exp in experts_list:
                if exp.get("label") == expert_label and exp.get("type") == "api":
                    model_name = exp.get("model_name", "")
                    rates = _COST_PER_1M.get(model_name, (0.0, 0.0))
                    cost_usd = ((prompt_tokens / 1_000_000) * rates[0]) + ((completion_tokens / 1_000_000) * rates[1])
                    break
    except Exception:
        pass

    with _lock:
        data = _read()
        data["total_requests"] = data.get("total_requests", 0) + 1
        experts = data.setdefault("experts", {})
        
        entry = experts.get(expert_label)
        if not isinstance(entry, dict):
            entry = {
                "requests": 0, "successes": 0, "failures": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                "latency_sum_ms": 0.0, "cost_usd": 0.0
            }
        
        entry["requests"] = entry.get("requests", 0) + 1
        if success:
            entry["successes"] = entry.get("successes", 0) + 1
        else:
            entry["failures"] = entry.get("failures", 0) + 1
            
        entry["prompt_tokens"] = entry.get("prompt_tokens", 0) + prompt_tokens
        entry["completion_tokens"] = entry.get("completion_tokens", 0) + completion_tokens
        entry["total_tokens"] = entry["prompt_tokens"] + entry["completion_tokens"]
        
        entry["latency_sum_ms"] = entry.get("latency_sum_ms", 0.0) + latency_ms
        entry["cost_usd"] = entry.get("cost_usd", 0.0) + cost_usd
        
        experts[expert_label] = entry
        
        # Track hourly usage
        hourly = _prune_hourly(data.get("hourly", {}))
        key = _hour_key()
        if key not in hourly:
            hourly[key] = {"requests": 0, "cost_usd": 0.0, "tokens": 0}
            
        hourly[key]["requests"] += 1
        hourly[key]["cost_usd"] += cost_usd
        hourly[key]["tokens"] += (prompt_tokens + completion_tokens)
        
        data["hourly"] = hourly
        _write(data)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

dashboard_app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>l3mcore · Telemetry</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg-main: #0a0a0f;
            --bg-secondary: #14141c;
            --bg-tertiary: #1f1f2e;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-color: #7c3aed;
            --border-color: #2a2a3e;
            --success: #10b981;
            --error: #ef4444;
            --font: 'Inter', system-ui, sans-serif;
            --mono: 'JetBrains Mono', monospace;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: var(--bg-main);
            color: var(--text-primary);
            font-family: var(--font);
            min-height: 100vh;
            padding: 3rem 2rem;
            display: flex;
            justify-content: center;
        }
        .wrap { width: 100%; max-width: 1200px; }

        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 3rem; border-bottom: 1px solid var(--border-color); padding-bottom: 1.5rem; }
        header h1 { font-size: 2rem; font-weight: 800; }
        header h1 span { color: var(--accent-color); font-weight: 300; }
        
        .header-actions { display: flex; gap: 1rem; }
        .btn {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.6rem 1.2rem;
            border-radius: 8px;
            font-family: var(--font);
            font-size: 0.9rem;
            cursor: pointer;
            display: inline-flex; align-items: center; gap: 8px;
            transition: all 0.2s;
            text-decoration: none;
        }
        .btn:hover { background: var(--bg-tertiary); border-color: var(--accent-color); }
        .btn-primary { background: var(--accent-color); border-color: transparent; }
        .btn-primary:hover { background: #2563eb; }

        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2.5rem;
        }
        .kpi {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 1.25rem;
        }
        .kpi-val { font-family: var(--mono); font-size: 1.75rem; font-weight: 700; margin-bottom: 0.25rem; color: var(--text-primary); }
        .kpi-lbl { font-size: 0.8rem; color: var(--text-secondary); }

        .charts-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
            margin-bottom: 3rem;
        }
        @media (max-width: 900px) { .charts-grid { grid-template-columns: 1fr; } }
        
        .chart-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 1.25rem;
        }
        .chart-title { font-size: 0.9rem; font-weight: 600; margin-bottom: 1rem; color: var(--text-secondary); border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem; }

        table { width: 100%; border-collapse: collapse; background: var(--bg-secondary); border-radius: 6px; border: 1px solid var(--border-color); }
        th, td { padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid var(--border-color); font-size: 0.9rem; }
        th { background: var(--bg-tertiary); color: var(--text-secondary); font-size: 0.8rem; font-weight: 600; }
        tr:last-child td { border-bottom: none; }
        
        .badge { color: var(--accent-color); font-weight: 600; }
        .num { font-family: var(--mono); font-weight: 700; }
        .success-rate { color: var(--success); }
        .error-rate { color: var(--error); }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <div>
                <h1>LEMoE Telemetry</h1>
                <p style="color: var(--text-secondary); margin-top: 0.25rem;">Server Metrics</p>
            </div>
            <div class="header-actions">
                <a href="/api/export" class="btn">Export CSV</a>
                <button class="btn btn-primary" onclick="loadData()">Refresh</button>
            </div>
        </header>

        <div class="kpi-grid">
            <div class="kpi">
                <div class="kpi-lbl">Total Requests</div>
                <div class="kpi-val" id="kpi-reqs">0</div>
            </div>
            <div class="kpi">
                <div class="kpi-lbl">Total API Cost</div>
                <div class="kpi-val" id="kpi-cost" style="color: #f59e0b;">$0.00</div>
            </div>
            <div class="kpi">
                <div class="kpi-lbl">Tokens Processed</div>
                <div class="kpi-val" id="kpi-tokens">0M</div>
            </div>
            <div class="kpi" id="kpi-health-box">
                <div class="kpi-lbl">Global Success Rate</div>
                <div class="kpi-val" id="kpi-success">100%</div>
            </div>
        </div>

        <div class="charts-grid">
            <div class="chart-card">
                <div class="chart-title">Requests & Cost (Last 24h)</div>
                <canvas id="timelineChart" style="max-height: 250px;"></canvas>
            </div>
            <div class="chart-card">
                <div class="chart-title">Cost Distribution</div>
                <canvas id="costChart" style="max-height: 250px;"></canvas>
            </div>
        </div>

        <div class="chart-card" style="padding:0; overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Expert Router</th>
                        <th>Reqs</th>
                        <th>Tokens (In/Out)</th>
                        <th>Throughput</th>
                        <th>Avg Latency</th>
                        <th>Cost</th>
                        <th>Health</th>
                    </tr>
                </thead>
                <tbody id="table-body">
                    <tr><td colspan="7" style="text-align:center; color: var(--text-secondary);">Loading metrics...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let timelineChart, costChart;

        async function loadData() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                
                document.getElementById('kpi-reqs').textContent = data.total_requests.toLocaleString();
                
                // Process Experts
                let totalCost = 0;
                let totalTokens = 0;
                let totalSuccess = 0;
                let totalFails = 0;
                
                const tableBody = document.getElementById('table-body');
                tableBody.innerHTML = '';
                
                const costData = [];
                const costLabels = [];

                for (const [label, stats] of Object.entries(data.experts)) {
                    totalCost += (stats.cost_usd || 0);
                    totalTokens += (stats.total_tokens || 0);
                    totalSuccess += (stats.successes || 0);
                    totalFails += (stats.failures || 0);
                    
                    if ((stats.cost_usd || 0) > 0) {
                        costLabels.push(label);
                        costData.push(stats.cost_usd);
                    }

                    const reqs = stats.requests || 0;
                    const avgLatencyMs = reqs > 0 ? (stats.latency_sum_ms / reqs) : 0;
                    const avgLatencyS = avgLatencyMs / 1000;
                    const tps = avgLatencyS > 0 ? ((stats.completion_tokens || 0) / reqs) / avgLatencyS : 0;
                    
                    const successRate = reqs > 0 ? ((stats.successes || 0) / reqs * 100).toFixed(1) : 100;
                    const healthClass = successRate > 95 ? 'success-rate' : 'error-rate';

                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><span class="badge">${label}</span></td>
                        <td class="num">${reqs.toLocaleString()}</td>
                        <td class="num" style="font-size:0.85rem; color:var(--text-secondary)">
                            ${(stats.prompt_tokens||0).toLocaleString()} / <span style="color:var(--text-primary)">${(stats.completion_tokens||0).toLocaleString()}</span>
                        </td>
                        <td class="num">${tps > 0 ? tps.toFixed(1) + ' T/s' : '-'}</td>
                        <td class="num">${avgLatencyMs > 0 ? avgLatencyMs.toFixed(0) + ' ms' : '-'}</td>
                        <td class="num" style="color: #f59e0b;">$${(stats.cost_usd || 0).toFixed(4)}</td>
                        <td class="num ${healthClass}">${successRate}%</td>
                    `;
                    tableBody.appendChild(tr);
                }
                
                if (Object.keys(data.experts).length === 0) {
                    tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-secondary);">No telemetry data available yet.</td></tr>';
                }

                document.getElementById('kpi-cost').textContent = '$' + totalCost.toFixed(2);
                document.getElementById('kpi-tokens').textContent = (totalTokens / 1000000).toFixed(2) + 'M';
                
                const globalRate = (totalSuccess + totalFails) > 0 ? (totalSuccess / (totalSuccess + totalFails) * 100) : 100;
                document.getElementById('kpi-success').textContent = globalRate.toFixed(1) + '%';
                
                const hb = document.getElementById('kpi-health-box');
                const successElem = document.getElementById('kpi-success');
                if(globalRate < 95) { successElem.style.color = 'var(--error)'; }
                else { successElem.style.color = 'var(--success)'; }

                // Charts
                renderTimeline(data.hourly);
                renderCost(costLabels, costData);

            } catch (err) {
                console.error(err);
            }
        }

        function renderTimeline(hourlyData) {
            const keys = Object.keys(hourlyData).sort().slice(-24); // Last 24 hours
            const labels = keys.map(k => k.split('T')[1] + ':00');
            const reqs = keys.map(k => hourlyData[k].requests);
            
            const ctx = document.getElementById('timelineChart').getContext('2d');
            if (timelineChart) timelineChart.destroy();
            
            Chart.defaults.color = '#94a3b8';
            timelineChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Requests',
                        data: reqs,
                        backgroundColor: '#7c3aed',
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, grid: { color: '#334155' } },
                        x: { grid: { display: false } }
                    }
                }
            });
        }

        function renderCost(labels, data) {
            const ctx = document.getElementById('costChart').getContext('2d');
            if (costChart) costChart.destroy();
            
            if(data.length === 0) {
                data = [1]; labels = ['No Cost'];
            }

            costChart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: ['#7c3aed', '#60a5fa', '#10b981', '#f59e0b', '#ef4444'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    cutout: '70%',
                    plugins: {
                        legend: { position: 'right', labels: { color: '#f8fafc', font: {family: "'Inter', sans-serif"} } }
                    }
                }
            });
        }

        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""

@dashboard_app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@dashboard_app.route("/api/data")
def api_data():
    return jsonify(_read())

@dashboard_app.route("/api/export")
def api_export():
    data = _read()
    si = StringIO()
    cw = csv.writer(si)
    
    # Write header
    cw.writerow(["Expert", "Requests", "Success", "Failures", "Prompt Tokens", "Completion Tokens", "Total Tokens", "Cost USD", "Avg Latency MS", "Throughput T/s"])
    
    for label, stats in data.get("experts", {}).items():
        reqs = stats.get("requests", 0)
        avg_lat = (stats.get("latency_sum_ms", 0) / reqs) if reqs > 0 else 0
        tps = ((stats.get("completion_tokens", 0) / reqs) / (avg_lat / 1000)) if avg_lat > 0 else 0
        
        cw.writerow([
            label,
            reqs,
            stats.get("successes", 0),
            stats.get("failures", 0),
            stats.get("prompt_tokens", 0),
            stats.get("completion_tokens", 0),
            stats.get("total_tokens", 0),
            round(stats.get("cost_usd", 0), 6),
            round(avg_lat, 2),
            round(tps, 2)
        ])
        
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=telemetry_export.csv"}
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _start_dashboard():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    dashboard_app.run(host="127.0.0.1", port=8081, debug=False, use_reloader=False)

if __name__ == "__main__":
    print("Starting l3mcore Enterprise Telemetry dashboard on http://127.0.0.1:8081")
    _start_dashboard()
else:
    t = threading.Thread(target=_start_dashboard, daemon=True)
    t.start()
    try:
        from modules.logger import app_logger
        app_logger.info("Enterprise Telemetry dashboard running on http://127.0.0.1:8081")
    except ImportError:
        pass
