"""app.py — Real-time observability dashboard for the Think Tank multi-agent system.

A FastAPI single-page application that:
  • serves an embedded React/SVG dashboard at GET /
  • streams structured events from build_think_tank_graph() over a websocket
    at /observe, mapped from LangGraph's stream_mode="updates" payloads to a
    flat event schema the frontend understands
  • runs a built-in demo at GET /?demo=1 (no API key required)

Run with:
    uv run uvicorn app:app --reload --host 0.0.0.0 --port 7860

Constraints honoured:
  • Single file — all HTML/CSS/JS live in this module as one embedded string.
  • Live view only — no auth, no persistence, in-memory state.
  • Sub-second updates — events are forwarded as soon as graph.astream() yields.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Embedded single-page frontend.
# Edit the .jsx/.html source files in the project and re-bundle to refresh.
# ─────────────────────────────────────────────────────────────────────────────
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Think Tank · Observability</title>
<meta name="viewport" content="width=1440">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

<style>
:root{
  --bg:#0a0b0d;
  --bg-elev:#101216;
  --bg-card:#13161b;
  --bg-card-2:#181b21;
  --bg-hover:#1c2027;
  --border:#22262d;
  --border-strong:#2c3138;
  --text:#e7eaef;
  --text-2:#a3a9b3;
  --text-3:#6b7280;
  --text-4:#4a4f57;

  /* severity */
  --sev-debug:#6b7280;
  --sev-info:#4d8cff;
  --sev-warn:#f5a623;
  --sev-error:#ef4444;

  /* edge / status */
  --ok:#22c55e;
  --err:#ef4444;
  --warn:#f5a623;
  --pending:#5c6370;

  /* accents */
  --accent:#7c5cff;        /* think tank purple */
  --accent-2:#22d3ee;      /* live cyan */
  --accent-3:#ff8a3d;      /* researcher */
  --accent-4:#ef4444;      /* skeptic */
  --accent-5:#f5cf00;      /* visionary */
  --accent-6:#7c5cff;      /* synthesizer */
  --accent-7:#22d3ee;      /* arbiter */
  --accent-8:#94a3b8;      /* vector store */

  --radius:8px;
  --radius-sm:6px;

  --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --sans: 'Geist', ui-sans-serif, -apple-system, BlinkMacSystemFont, sans-serif;
}

*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:13px;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body{min-width:1440px}
button{font-family:inherit;color:inherit;background:none;border:0;padding:0;cursor:default}
input,select,textarea{font-family:inherit;color:inherit}

.app{
  width:1440px;margin:0 auto;
  display:flex;flex-direction:column;
  min-height:100vh;
}

/* ─── Header ─────────────────────────────────────────────── */
.hdr{
  display:flex;align-items:center;gap:24px;
  height:56px;padding:0 24px;
  border-bottom:1px solid var(--border);
  background:linear-gradient(180deg, rgba(124,92,255,0.04) 0%, transparent 100%), var(--bg);
}
.hdr-brand{display:flex;align-items:center;gap:10px}
.hdr-mark{
  width:26px;height:26px;border-radius:7px;
  background:conic-gradient(from 220deg at 50% 50%, #7c5cff, #22d3ee, #f5cf00, #ff8a3d, #ef4444, #7c5cff);
  position:relative;
  box-shadow:0 0 0 1px rgba(255,255,255,0.05) inset, 0 4px 14px rgba(124,92,255,0.35);
}
.hdr-mark::after{content:'';position:absolute;inset:5px;background:var(--bg);border-radius:3px}
.hdr-mark::before{content:'';position:absolute;inset:9px;background:var(--text);border-radius:1px;width:8px;height:8px}
.hdr-title{font-weight:600;font-size:14px;letter-spacing:-0.01em}
.hdr-sub{font-family:var(--mono);font-size:11px;color:var(--text-3);margin-left:8px}

.hdr-runbar{
  display:flex;align-items:center;gap:14px;
  flex:1;
  padding:0 14px;height:34px;
  background:var(--bg-card);
  border:1px solid var(--border);
  border-radius:var(--radius);
}
.hdr-pulse{display:flex;align-items:center;gap:7px;font-family:var(--mono);font-size:11px;color:var(--ok);font-weight:500}
.hdr-pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 rgba(34,197,94,0.6);animation:pulse 1.4s ease-out infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(34,197,94,0.55)}70%{box-shadow:0 0 0 7px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
.hdr-runlabel{font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:0.07em;font-weight:600}
.hdr-runtopic{font-size:13px;color:var(--text);font-weight:500;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hdr-runid{font-family:var(--mono);font-size:11px;color:var(--text-3)}
.hdr-runid b{color:var(--text-2);font-weight:500}

.hdr-actions{display:flex;gap:6px}
.hdr-btn{
  height:30px;padding:0 11px;display:inline-flex;align-items:center;gap:7px;
  background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius-sm);
  font-size:12px;color:var(--text-2);
}
.hdr-btn:hover{background:var(--bg-hover);color:var(--text);border-color:var(--border-strong)}
.hdr-btn.primary{background:var(--accent);color:#fff;border-color:transparent}
.hdr-btn.primary:hover{filter:brightness(1.08)}
.hdr-btn.danger{color:var(--err)}
.hdr-btn .kbd{
  font-family:var(--mono);font-size:10px;color:var(--text-3);
  border:1px solid var(--border);border-radius:3px;padding:0 4px;height:16px;display:inline-flex;align-items:center
}

/* ─── Section frame ───────────────────────────────────────── */
.sec{
  background:var(--bg-card);
  border:1px solid var(--border);
  border-radius:var(--radius);
  display:flex;flex-direction:column;
  overflow:hidden;
}
.sec-hdr{
  display:flex;align-items:center;gap:12px;
  padding:10px 14px;
  border-bottom:1px solid var(--border);
  background:linear-gradient(180deg, var(--bg-card-2), var(--bg-card));
}
.sec-title{font-size:12px;font-weight:600;letter-spacing:0.02em;color:var(--text)}
.sec-badge{
  font-family:var(--mono);font-size:10px;color:var(--text-3);
  padding:2px 6px;border-radius:4px;background:var(--bg-elev);border:1px solid var(--border)
}
.sec-spacer{flex:1}

/* ─── Layout ──────────────────────────────────────────────── */
.body{
  padding:14px;display:flex;flex-direction:column;gap:12px;
}
.row-mid{
  display:grid;grid-template-columns:1fr 380px;gap:12px;
  height:480px;
}

/* ─── Agent Graph ─────────────────────────────────────────── */
.graph{height:340px}
.graph-canvas{flex:1;position:relative;overflow:hidden}
.graph-canvas svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.graph-grid{
  position:absolute;inset:0;
  background-image:
    radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0);
  background-size:20px 20px;
  mask-image:radial-gradient(ellipse 80% 70% at 50% 50%, #000 40%, transparent 100%);
}
.graph-legend{
  position:absolute;right:14px;bottom:12px;
  display:flex;gap:14px;
  background:rgba(16,18,22,0.85);
  border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:7px 11px;backdrop-filter:blur(6px);
  font-family:var(--mono);font-size:10px;color:var(--text-2);
}
.graph-legend .lg{display:flex;align-items:center;gap:6px}
.graph-legend .lg-dot{width:8px;height:2px;border-radius:1px}

.graph-clock{
  position:absolute;left:14px;top:12px;
  display:flex;align-items:center;gap:10px;
  font-family:var(--mono);font-size:11px;color:var(--text-3);
}
.graph-clock b{color:var(--text);font-weight:500}

/* node */
.node-label{font-family:var(--sans);font-size:11px;font-weight:500;fill:var(--text);text-anchor:middle;dominant-baseline:middle}
.node-role{font-family:var(--mono);font-size:9px;fill:var(--text-3);text-anchor:middle;dominant-baseline:middle;letter-spacing:0.05em;text-transform:uppercase}
.edge-label{font-family:var(--mono);font-size:9.5px;fill:var(--text-2);dominant-baseline:middle;letter-spacing:0.02em}
.edge-label.bg{fill:var(--bg-card);stroke:var(--bg-card);stroke-width:5px}

/* ─── Event Stream ────────────────────────────────────────── */
.stream{flex:1;min-width:0}
.stream-toolbar{
  display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);
  background:var(--bg-card);
}
.stream-search{
  display:flex;align-items:center;gap:6px;flex:1;
  height:28px;padding:0 10px;
  background:var(--bg-elev);border:1px solid var(--border);border-radius:var(--radius-sm);
}
.stream-search input{
  flex:1;background:transparent;border:0;outline:0;font-size:12px;color:var(--text);font-family:var(--mono)
}
.stream-search input::placeholder{color:var(--text-4)}
.chip{
  display:inline-flex;align-items:center;gap:6px;
  height:24px;padding:0 8px;border-radius:5px;
  background:var(--bg-elev);border:1px solid var(--border);
  font-family:var(--mono);font-size:10.5px;color:var(--text-2);
  letter-spacing:0.02em;text-transform:uppercase;font-weight:500;
}
.chip.on{background:rgba(124,92,255,0.12);border-color:rgba(124,92,255,0.35);color:#c4b5fd}
.chip.sev-DEBUG.on{background:rgba(107,114,128,0.18);border-color:rgba(107,114,128,0.45);color:#d1d5db}
.chip.sev-INFO.on{background:rgba(77,140,255,0.14);border-color:rgba(77,140,255,0.40);color:#9ec0ff}
.chip.sev-WARN.on{background:rgba(245,166,35,0.14);border-color:rgba(245,166,35,0.40);color:#fbcc77}
.chip.sev-ERROR.on{background:rgba(239,68,68,0.14);border-color:rgba(239,68,68,0.40);color:#fca5a5}
.chip-dot{width:6px;height:6px;border-radius:50%}

.stream-count{font-family:var(--mono);font-size:11px;color:var(--text-3);margin-left:auto}
.stream-count b{color:var(--text-2);font-weight:500}

.stream-list{
  flex:1;overflow-y:auto;
  font-family:var(--mono);font-size:11.5px;
  scrollbar-width:thin;scrollbar-color:#2c3138 transparent;
}
.stream-list::-webkit-scrollbar{width:10px}
.stream-list::-webkit-scrollbar-thumb{background:#2c3138;border-radius:5px;border:2px solid var(--bg-card);background-clip:content-box}

.evt{
  display:grid;
  grid-template-columns:118px 56px 130px 1fr 30px;
  gap:10px;align-items:start;
  padding:6px 12px;
  border-bottom:1px solid rgba(34,38,45,0.5);
  position:relative;
}
.evt:hover{background:rgba(255,255,255,0.018)}
.evt-new{animation:evtIn 220ms ease-out}
@keyframes evtIn{from{background:rgba(124,92,255,0.10)}to{background:transparent}}
.evt-ts{color:var(--text-3);font-size:11px;letter-spacing:-0.01em;white-space:nowrap}
.evt-ts b{color:var(--text-2);font-weight:500}
.evt-sev{
  display:inline-flex;align-items:center;justify-content:center;
  height:18px;padding:0 6px;border-radius:3px;
  font-size:9.5px;font-weight:600;letter-spacing:0.07em;
}
.evt-sev.DEBUG{background:rgba(107,114,128,0.15);color:#9ca3af}
.evt-sev.INFO{background:rgba(77,140,255,0.14);color:#9ec0ff}
.evt-sev.WARN{background:rgba(245,166,35,0.14);color:#fbcc77}
.evt-sev.ERROR{background:rgba(239,68,68,0.16);color:#fca5a5}
.evt-agent{display:flex;align-items:center;gap:6px;min-width:0;color:var(--text-2);font-size:11px}
.evt-agent .dot{width:7px;height:7px;border-radius:50%;flex:none}
.evt-agent .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.evt-body{min-width:0;overflow:hidden}
.evt-type{color:var(--text);font-weight:500;font-size:11.5px;letter-spacing:-0.005em}
.evt-payload{margin-top:3px;color:var(--text-3);font-size:11px;line-height:1.55;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.evt.exp .evt-payload{white-space:pre-wrap;text-overflow:initial;overflow:auto;max-height:240px;background:#0a0b0d;border:1px solid var(--border);padding:8px 10px;border-radius:5px;color:var(--text-2);font-size:11px}
.evt-payload .k{color:#7c8aff}
.evt-payload .s{color:#a5e6a5}
.evt-payload .n{color:#fbcc77}
.evt-payload .b{color:#ff8c8c}
.evt-actions{display:flex;gap:4px;justify-content:flex-end}
.icon-btn{
  width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;
  border-radius:4px;color:var(--text-3);
}
.icon-btn:hover{background:var(--bg-hover);color:var(--text)}
.icon-btn.copied{color:var(--ok)}

/* ─── Agent Sidebar ───────────────────────────────────────── */
.sidebar{display:flex;flex-direction:column}
.sidebar-list{flex:1;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:8px;
  scrollbar-width:thin;scrollbar-color:#2c3138 transparent}
.sidebar-list::-webkit-scrollbar{width:8px}
.sidebar-list::-webkit-scrollbar-thumb{background:#2c3138;border-radius:4px;border:2px solid var(--bg-card);background-clip:content-box}

.acard{
  background:var(--bg-card-2);
  border:1px solid var(--border);
  border-radius:var(--radius-sm);
  padding:10px 11px;
  display:flex;flex-direction:column;gap:8px;
  position:relative;
  transition:border-color .2s, background .2s;
}
.acard.running{border-color:rgba(124,92,255,0.45);background:linear-gradient(180deg, rgba(124,92,255,0.08), var(--bg-card-2))}
.acard.error{border-color:rgba(239,68,68,0.45)}
.acard.completed{border-color:rgba(34,197,94,0.30)}
.acard-bar{position:absolute;left:0;top:0;bottom:0;width:2px;border-radius:2px 0 0 2px;background:transparent}
.acard.running .acard-bar{background:var(--accent)}
.acard.error .acard-bar{background:var(--err)}
.acard.completed .acard-bar{background:var(--ok)}

.acard-row{display:flex;align-items:center;gap:8px}
.acard-icon{
  width:28px;height:28px;border-radius:7px;
  display:flex;align-items:center;justify-content:center;
  font-family:var(--mono);font-size:13px;font-weight:600;color:#fff;
  flex:none;
}
.acard-name{font-size:12.5px;font-weight:600;letter-spacing:-0.005em}
.acard-role{font-family:var(--mono);font-size:9.5px;color:var(--text-3);letter-spacing:0.06em;text-transform:uppercase}
.acard-state{
  margin-left:auto;
  display:inline-flex;align-items:center;gap:5px;
  font-family:var(--mono);font-size:9.5px;font-weight:600;
  padding:2px 6px;border-radius:3px;letter-spacing:0.07em;text-transform:uppercase;
}
.acard-state .sd{width:6px;height:6px;border-radius:50%}
.acard-state.idle{background:rgba(107,114,128,0.13);color:#9ca3af}
.acard-state.idle .sd{background:#6b7280}
.acard-state.running{background:rgba(124,92,255,0.18);color:#c4b5fd}
.acard-state.running .sd{background:var(--accent);box-shadow:0 0 0 0 rgba(124,92,255,0.6);animation:pulse-acc 1.4s ease-out infinite}
@keyframes pulse-acc{0%{box-shadow:0 0 0 0 rgba(124,92,255,0.6)}70%{box-shadow:0 0 0 6px rgba(124,92,255,0)}100%{box-shadow:0 0 0 0 rgba(124,92,255,0)}}
.acard-state.error{background:rgba(239,68,68,0.16);color:#fca5a5}
.acard-state.error .sd{background:var(--err)}
.acard-state.completed{background:rgba(34,197,94,0.16);color:#86efac}
.acard-state.completed .sd{background:var(--ok)}

.acard-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}
.acard-stat{
  background:rgba(0,0,0,0.18);border:1px solid var(--border);border-radius:5px;
  padding:5px 7px;
}
.acard-stat-k{font-family:var(--mono);font-size:9px;color:var(--text-3);letter-spacing:0.06em;text-transform:uppercase}
.acard-stat-v{font-family:var(--mono);font-size:13px;color:var(--text);font-weight:500;font-variant-numeric:tabular-nums;margin-top:1px}
.acard-stat-v.err{color:var(--err)}
.acard-stat-v.ok{color:var(--ok)}

.acard-last{
  font-family:var(--mono);font-size:10.5px;color:var(--text-2);
  background:rgba(0,0,0,0.18);border:1px solid var(--border);border-radius:5px;
  padding:6px 8px;line-height:1.4;
  overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
}
.acard-last .lbl{color:var(--text-3);font-size:9px;letter-spacing:0.06em;text-transform:uppercase;display:block;margin-bottom:2px}

.acard-spark{height:18px;display:flex;align-items:flex-end;gap:1.5px}
.acard-spark .b{flex:1;background:var(--accent);opacity:0.4;border-radius:1px 1px 0 0;min-height:1px}
.acard.running .acard-spark .b{opacity:0.8}

/* ─── Metrics Strip ───────────────────────────────────────── */
.metrics{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr)) 1.6fr 1.4fr;gap:0;
  height:132px;
}
.metric{
  padding:14px 18px;
  border-right:1px solid var(--border);
  display:flex;flex-direction:column;justify-content:center;gap:5px;
  position:relative;
}
.metric:last-child{border-right:0}
.metric-k{font-family:var(--mono);font-size:10px;color:var(--text-3);letter-spacing:0.07em;text-transform:uppercase;font-weight:600}
.metric-v{font-family:var(--mono);font-size:30px;font-weight:500;color:var(--text);letter-spacing:-0.01em;font-variant-numeric:tabular-nums;line-height:1.05}
.metric-v .u{font-size:14px;color:var(--text-3);margin-left:4px;font-weight:400}
.metric-sub{font-family:var(--mono);font-size:10.5px;color:var(--text-3)}
.metric-sub .delta-up{color:var(--ok)}
.metric-sub .delta-dn{color:var(--err)}

.spark-wrap{padding:14px 18px;display:flex;flex-direction:column;gap:6px;border-right:1px solid var(--border);justify-content:center}
.spark-hd{display:flex;align-items:baseline;gap:8px}
.spark-hd .k{font-family:var(--mono);font-size:10px;color:var(--text-3);letter-spacing:0.07em;text-transform:uppercase;font-weight:600}
.spark-hd .v{font-family:var(--mono);font-size:18px;color:var(--text);font-weight:500}
.spark-hd .v .u{color:var(--text-3);font-size:11px;margin-left:3px}
.spark-svg{width:100%;height:48px;display:block}

.gauges{padding:14px 18px;display:flex;flex-direction:column;gap:9px;justify-content:center}
.gauges-hd{font-family:var(--mono);font-size:10px;color:var(--text-3);letter-spacing:0.07em;text-transform:uppercase;font-weight:600;margin-bottom:1px}
.gauge{display:grid;grid-template-columns:34px 1fr 60px;gap:10px;align-items:center}
.gauge-k{font-family:var(--mono);font-size:10.5px;color:var(--text-2);font-weight:500}
.gauge-bar{height:6px;border-radius:3px;background:var(--bg-elev);overflow:hidden;position:relative}
.gauge-fill{height:100%;border-radius:3px;background:linear-gradient(90deg, #4d8cff, #22d3ee)}
.gauge-fill.warn{background:linear-gradient(90deg, #f5a623, #ef4444)}
.gauge-v{font-family:var(--mono);font-size:11px;color:var(--text);text-align:right;font-variant-numeric:tabular-nums}
.gauge-v .u{color:var(--text-3);font-size:10px;margin-left:2px}

/* ─── Footer ─── */
.foot{
  padding:8px 24px;display:flex;align-items:center;gap:14px;
  font-family:var(--mono);font-size:10.5px;color:var(--text-3);
  border-top:1px solid var(--border);height:30px;background:var(--bg);
}
.foot .sep{width:1px;height:11px;background:var(--border)}
.foot b{color:var(--text-2);font-weight:500}

/* ─── density modes ─── */
.density-compact .evt{padding:3px 12px;grid-template-columns:118px 56px 130px 1fr 30px}
.density-compact .evt .evt-payload{margin-top:2px}
.density-compact .acard{padding:8px 10px;gap:6px}
.density-compact .acard-stat{padding:4px 6px}
.density-comfy .evt{padding:9px 12px}

/* ─── light theme override ─── */
.theme-light{
  --bg:#f7f8fa;--bg-elev:#ffffff;--bg-card:#ffffff;--bg-card-2:#fafbfc;--bg-hover:#f1f3f6;
  --border:#e3e6ec;--border-strong:#d4d8df;
  --text:#0e1116;--text-2:#3a4150;--text-3:#6b7280;--text-4:#9ca3af;
}
.theme-light .graph-grid{background-image:radial-gradient(circle at 1px 1px, rgba(0,0,0,0.06) 1px, transparent 0)}
.theme-light .edge-label.bg{fill:#ffffff;stroke:#ffffff}

/* utility */
.spin{animation:spin 1.4s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

</style>

<!-- Mini SVG icon set as <symbol> -->
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <symbol id="ic-copy" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="M5.5 5.5h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-6a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1Z M3.5 10.5h-1a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v1"/></symbol>
    <symbol id="ic-check" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M3 8.2 6.5 11.5 13 5"/></symbol>
    <symbol id="ic-chev" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="m4 6.5 4 4 4-4"/></symbol>
    <symbol id="ic-search" viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path stroke="currentColor" stroke-width="1.4" stroke-linecap="round" d="m10.5 10.5 3 3"/></symbol>
    <symbol id="ic-pause" viewBox="0 0 16 16"><rect x="4.5" y="3.5" width="2.6" height="9" rx="0.6" fill="currentColor"/><rect x="8.9" y="3.5" width="2.6" height="9" rx="0.6" fill="currentColor"/></symbol>
    <symbol id="ic-play" viewBox="0 0 16 16"><path fill="currentColor" d="M5 3.5v9l8-4.5z"/></symbol>
    <symbol id="ic-stop" viewBox="0 0 16 16"><rect x="4" y="4" width="8" height="8" rx="1" fill="currentColor"/></symbol>
    <symbol id="ic-clear" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="M3 4h10 M5 4l.7 9a1 1 0 0 0 1 .9h2.6a1 1 0 0 0 1-.9L11 4 M6.5 4V2.5a.8.8 0 0 1 .8-.8h1.4a.8.8 0 0 1 .8.8V4"/></symbol>
    <symbol id="ic-dl" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="M8 2.5v8 M5 7.5l3 3 3-3 M3 13.5h10"/></symbol>
    <symbol id="ic-grip" viewBox="0 0 16 16"><circle cx="6" cy="4" r="1.1" fill="currentColor"/><circle cx="10" cy="4" r="1.1" fill="currentColor"/><circle cx="6" cy="8" r="1.1" fill="currentColor"/><circle cx="10" cy="8" r="1.1" fill="currentColor"/><circle cx="6" cy="12" r="1.1" fill="currentColor"/><circle cx="10" cy="12" r="1.1" fill="currentColor"/></symbol>
  </defs>
</svg>

<script src="https://unpkg.com/react@18.3.1/umd/react.development.js" integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L" crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm" crossorigin="anonymous"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y" crossorigin="anonymous"></script>
</head>
<body>
<div id="root"></div>

<script >
/* ─── simulation.js ─────────────────────────────────────── */
// simulation.js — Generates a realistic streaming sequence of events from a
// LangGraph-style Think Tank deliberation. Loops through 3 rounds + final synthesis.
// Plain JS (no JSX) so it loads quickly. Exposes window.ThinkTankSim.

(function () {
  'use strict';

  const AGENTS = [
    { id: 'orchestrator', name: 'Orchestrator', role: 'graph.runner',     color: '#94a3b8' },
    { id: 'vector_store', name: 'Vector Store', role: 'kb.chroma',        color: '#94a3b8' },
    { id: 'researcher',   name: 'Researcher',   role: 'evidence.grounding', color: '#ff8a3d' },
    { id: 'skeptic',      name: 'Skeptic',      role: 'claim.challenger',  color: '#ef4444' },
    { id: 'visionary',    name: 'Visionary',    role: 'lateral.thinker',   color: '#f5cf00' },
    { id: 'synthesizer',  name: 'Synthesizer',  role: 'merger',            color: '#7c5cff' },
    { id: 'arbiter',      name: 'Arbiter',      role: 'convergence.judge', color: '#22d3ee' },
  ];

  const TOPIC = 'Should mid-sized engineering teams move to a hybrid 3-2 RTO policy?';
  const RUN_ID = 'run_8e2c4a91-rT';

  // ── Realistic structured payloads ──────────────────────────────────────────
  const claimSamples = [
    { content: "Stanford's 9-month productivity study (n=16k) shows +13% throughput from remote work, attributed to fewer interruptions and reduced sick leave.", confidence: "HIGH", evidence: "stanford_remote_2015.pdf §3.1" },
    { content: "Hybrid arrangements (2–3 days in-office) consistently produce the most balanced outcomes across HBR's 45-study meta-analysis.", confidence: "HIGH", evidence: "hbr_meta_2023.pdf §5" },
    { content: "Microsoft's 60k-employee telemetry study found cross-team tie-strength fell 25% in fully-remote cohorts.", confidence: "MEDIUM", evidence: "ms_collab_signals.pdf §2.4" },
    { content: "Average per-employee real-estate savings of ~$11k/yr on full-remote (Global Workplace Analytics 2023).", confidence: "MEDIUM", evidence: "gwa_estimate_2023.pdf" },
    { content: "Onboarding takes 32% longer remotely (Gartner 2022 HR survey, n=500). Knowledge transfer cited as primary blocker.", confidence: "HIGH", evidence: "gartner_onboarding.pdf §4" },
  ];
  const challengeSamples = [
    { stance: "oppose",  content: "The Stanford figure is from a call-center cohort; generalising to engineering is unsound.", reasoning: "Population validity gap; engineering work is interrupt-driven by review cycles." },
    { stance: "refine",  content: "Productivity gains decay after 6 months in fully-remote teams (follow-up data, Bloom 2023).", reasoning: "Time-bounded effect; need to qualify the claim." },
    { stance: "support", content: "Tie-strength loss is corroborated by Yang et al. 2022 in Nature Human Behaviour.", reasoning: "Independent corroboration strengthens confidence band." },
    { stance: "oppose",  content: "Cost savings ignore stipend, equipment, and security costs that grow ~$3.4k/yr per remote IC.", reasoning: "Net figure differs materially when fully accounted." },
    { stance: "refine",  content: "Onboarding penalty drops to <8% with structured pairing programs (Gitlab 2023 internal).", reasoning: "Mitigation exists; claim should not be unconditional." },
  ];
  const lateralSamples = [
    { content: "What if 'days in office' is the wrong unit? Measure by interaction-density per project-phase instead.", novelty: "Reframes the policy axis from time-presence to interaction-need." },
    { content: "Pair every IC with one rotating 'embed week' per quarter at a customer site.", novelty: "Imports a consulting pattern into product engineering." },
    { content: "Treat the office as a deliberate-design tool: only open it for cross-team weeks every 6 weeks.", novelty: "Inverts default — office becomes the exception, not the rule." },
    { content: "Asynchronous-only review weeks alternated with high-bandwidth in-person 'jam' weeks.", novelty: "Macro-scale rhythm rather than per-day flexibility." },
  ];

  function fmtJSON(obj){
    return JSON.stringify(obj, null, 2);
  }

  // ── Build the deterministic event sequence (rounds 1..3) ───────────────────
  function buildSequence() {
    const seq = [];
    let t = 0;
    const push = (dt, ev) => { t += dt; seq.push({ ...ev, dt: dt, _t: t }); };

    // boot
    push(  0, { sev: 'INFO',  agent: 'system',       type: 'graph.compile',
      payload: { nodes: ['researcher','skeptic','visionary','synthesizer','arbiter'], edges: 9, checkpoint: 'in_memory' } });
    push( 80, { sev: 'INFO',  agent: 'orchestrator', type: 'run.start',
      payload: { run_id: RUN_ID, topic: TOPIC, config: { alignment_threshold: 0.65, min_rounds: 2, max_rounds: 6 } }, edge: { from:'orchestrator', to:'researcher', kind:'dispatch', size:248, rtt:4, status:'success' } });
    push( 40, { sev: 'DEBUG', agent: 'orchestrator', type: 'state.init',
      payload: { claims:[], challenges:[], expansions:[], syntheses:[], current_round: 0, alignment_score: 0.0 } });

    // ROUND 1
    push( 50, { sev: 'INFO',  agent: 'orchestrator', type: 'round.start', payload: { round: 1 } });
    push( 30, { sev: 'INFO',  agent: 'researcher',   type: 'node.enter',  payload: { node: 'researcher', round: 1 }, activate: 'researcher' });
    push( 60, { sev: 'DEBUG', agent: 'researcher',   type: 'vector_store.query',
      payload: { query: 'remote work productivity engineering teams', k: 4, embedding_model: 'openai/text-embedding-3-small' },
      edge: { from:'researcher', to:'vector_store', kind:'kb.query', size:74, rtt:0, status:'pending' } });
    push(180, { sev: 'DEBUG', agent: 'vector_store', type: 'vector_store.result',
      payload: { docs_returned: 4, top_score: 0.847, latency_ms: 178, ids: ['doc_0','doc_3','doc_4','doc_5'] },
      edge: { from:'vector_store', to:'researcher', kind:'docs', size:3214, rtt:178, status:'success' } });
    push(120, { sev: 'DEBUG', agent: 'researcher',   type: 'llm.call.start',
      payload: { model:'anthropic/claude-sonnet-4.5', prompt_tokens: 1284, temperature: 0.2 } });
    push(940, { sev: 'INFO',  agent: 'researcher',   type: 'llm.call.complete',
      payload: { completion_tokens: 412, total_tokens: 1696, latency_ms: 932, finish_reason: 'stop' } });
    push( 30, { sev: 'INFO',  agent: 'researcher',   type: 'claim.emitted',
      payload: { id: 'claim_r1_01', round: 1, agent_id: 'researcher', confidence: 'HIGH', content: claimSamples[0].content, evidence_summary: claimSamples[0].evidence },
      edge: { from:'researcher', to:'synthesizer', kind:'claim', size:512, rtt:5, status:'success' } });
    push( 25, { sev: 'INFO',  agent: 'researcher',   type: 'claim.emitted',
      payload: { id: 'claim_r1_02', round: 1, agent_id: 'researcher', confidence: 'MEDIUM', content: claimSamples[2].content, evidence_summary: claimSamples[2].evidence },
      edge: { from:'researcher', to:'synthesizer', kind:'claim', size:498, rtt:4, status:'success' } });
    push( 20, { sev: 'INFO',  agent: 'researcher',   type: 'node.exit',  payload: { node:'researcher', round:1, duration_ms:1287 }, deactivate: 'researcher' });

    push( 40, { sev: 'INFO',  agent: 'skeptic',      type: 'node.enter', payload: { node:'skeptic', round:1 }, activate: 'skeptic' });
    push(110, { sev: 'DEBUG', agent: 'skeptic',      type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 1620, temperature: 0.4 } });
    push(810, { sev: 'INFO',  agent: 'skeptic',      type: 'llm.call.complete',
      payload: { completion_tokens: 388, total_tokens: 2008, latency_ms: 803, finish_reason: 'stop' } });
    push( 25, { sev: 'INFO',  agent: 'skeptic',      type: 'challenge.emitted',
      payload: { id: 'chal_r1_01', round: 1, agent_id: 'skeptic', stance: 'OPPOSE', target: 'claim_r1_01', content: challengeSamples[0].content, reasoning: challengeSamples[0].reasoning },
      edge: { from:'skeptic', to:'synthesizer', kind:'challenge', size:472, rtt:5, status:'error' } });
    push( 20, { sev: 'INFO',  agent: 'skeptic',      type: 'node.exit', payload: { node:'skeptic', round:1, duration_ms: 935 }, deactivate: 'skeptic' });

    push( 30, { sev: 'INFO',  agent: 'visionary',    type: 'node.enter', payload: { node:'visionary', round:1 }, activate: 'visionary' });
    push(150, { sev: 'WARN',  agent: 'visionary',    type: 'llm.call.timeout',
      payload: { model: 'anthropic/claude-sonnet-4.5', timeout_ms: 8000, attempt: 1, action: 'retry' },
      edge: { from:'visionary', to:'synthesizer', kind:'lateral_idea', size:0, rtt:8000, status:'warn' } });
    push(280, { sev: 'INFO',  agent: 'visionary',    type: 'llm.call.retry.success',
      payload: { attempt: 2, completion_tokens: 304, latency_ms: 1142 } });
    push( 25, { sev: 'INFO',  agent: 'visionary',    type: 'lateral_idea.emitted',
      payload: { id: 'idea_r1_01', round: 1, agent_id: 'visionary', content: lateralSamples[0].content, novelty_rationale: lateralSamples[0].novelty },
      edge: { from:'visionary', to:'synthesizer', kind:'lateral_idea', size:540, rtt:1142, status:'success' } });
    push( 20, { sev: 'INFO',  agent: 'visionary',    type: 'node.exit', payload: { node:'visionary', round:1, duration_ms: 1497 }, deactivate: 'visionary' });

    push( 30, { sev: 'INFO',  agent: 'synthesizer',  type: 'node.enter', payload: { node:'synthesizer', round:1 }, activate: 'synthesizer' });
    push(120, { sev: 'DEBUG', agent: 'synthesizer',  type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 2148, temperature: 0.3, inputs: { claims: 2, challenges: 1, ideas: 1 } } });
    push(1180, { sev: 'INFO', agent: 'synthesizer',  type: 'llm.call.complete',
      payload: { completion_tokens: 524, total_tokens: 2672, latency_ms: 1174, finish_reason: 'stop' } });
    push( 25, { sev: 'INFO',  agent: 'synthesizer',  type: 'synthesis.attempt',
      payload: { id: 'synth_r1', round: 1, confidence: 'LOW', content: 'Preliminary merge: hybrid policy plausible, but tie-strength concern unaddressed; productivity claim contested.', contributing_claim_ids: ['claim_r1_01','claim_r1_02'] },
      edge: { from:'synthesizer', to:'arbiter', kind:'synthesis', size:684, rtt:6, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'synthesizer',  type: 'node.exit', payload: { node:'synthesizer', round:1, duration_ms: 1323 }, deactivate: 'synthesizer' });

    push( 30, { sev: 'INFO',  agent: 'arbiter',      type: 'node.enter', payload: { node:'arbiter', round:1 }, activate: 'arbiter' });
    push(220, { sev: 'INFO',  agent: 'arbiter',      type: 'alignment.scored',
      payload: { round: 1, score: 0.4127, threshold: 0.65, decision: 'CONTINUE', reasoning: 'Below threshold; major challenges unresolved.' } });
    push( 30, { sev: 'INFO',  agent: 'arbiter',      type: 'round.complete', payload: { round: 1, alignment_score: 0.4127, claims: 2, challenges: 1, ideas: 1 },
      edge: { from:'arbiter', to:'orchestrator', kind:'control', size:120, rtt:3, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'arbiter',      type: 'node.exit', payload: { node:'arbiter', round:1, duration_ms: 271 }, deactivate: 'arbiter' });

    // ROUND 2
    push( 60, { sev: 'INFO',  agent: 'orchestrator', type: 'round.start', payload: { round: 2 } });
    push( 30, { sev: 'INFO',  agent: 'researcher',   type: 'node.enter', payload: { node:'researcher', round:2 }, activate: 'researcher' });
    push( 60, { sev: 'DEBUG', agent: 'researcher',   type: 'vector_store.query',
      payload: { query: 'hybrid work meta-analysis innovation tie strength', k: 4 },
      edge: { from:'researcher', to:'vector_store', kind:'kb.query', size:88, rtt:0, status:'pending' } });
    push(160, { sev: 'DEBUG', agent: 'vector_store', type: 'vector_store.result',
      payload: { docs_returned: 4, top_score: 0.812, latency_ms: 156, ids: ['doc_3','doc_5','doc_7','doc_1'] },
      edge: { from:'vector_store', to:'researcher', kind:'docs', size:3088, rtt:156, status:'success' } });
    push(120, { sev: 'DEBUG', agent: 'researcher',   type: 'llm.call.start',
      payload: { model:'anthropic/claude-sonnet-4.5', prompt_tokens: 2240, temperature: 0.2 } });
    push(990, { sev: 'INFO',  agent: 'researcher',   type: 'llm.call.complete',
      payload: { completion_tokens: 478, total_tokens: 2718, latency_ms: 982, finish_reason: 'stop' } });
    push( 25, { sev: 'INFO',  agent: 'researcher',   type: 'claim.emitted',
      payload: { id: 'claim_r2_01', round: 2, agent_id: 'researcher', confidence: 'HIGH', content: claimSamples[1].content, evidence_summary: claimSamples[1].evidence },
      edge: { from:'researcher', to:'synthesizer', kind:'claim', size:534, rtt:5, status:'success' } });
    push( 22, { sev: 'INFO',  agent: 'researcher',   type: 'claim.emitted',
      payload: { id: 'claim_r2_02', round: 2, agent_id: 'researcher', confidence: 'HIGH', content: claimSamples[4].content, evidence_summary: claimSamples[4].evidence },
      edge: { from:'researcher', to:'synthesizer', kind:'claim', size:520, rtt:4, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'researcher',   type: 'node.exit', payload: { node:'researcher', round:2, duration_ms: 1395 }, deactivate: 'researcher' });

    push( 30, { sev: 'INFO',  agent: 'skeptic',      type: 'node.enter', payload: { node:'skeptic', round:2 }, activate: 'skeptic' });
    push(110, { sev: 'DEBUG', agent: 'skeptic',      type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 1840, temperature: 0.4 } });
    push(880, { sev: 'INFO',  agent: 'skeptic',      type: 'llm.call.complete',
      payload: { completion_tokens: 402, total_tokens: 2242, latency_ms: 873, finish_reason: 'stop' } });
    push( 22, { sev: 'INFO',  agent: 'skeptic',      type: 'challenge.emitted',
      payload: { id: 'chal_r2_01', round: 2, agent_id: 'skeptic', stance: 'REFINE', target: 'claim_r2_02', content: challengeSamples[4].content, reasoning: challengeSamples[4].reasoning },
      edge: { from:'skeptic', to:'synthesizer', kind:'challenge', size:498, rtt:5, status:'warn' } });
    push( 22, { sev: 'WARN',  agent: 'skeptic',      type: 'rate_limit.deferred',
      payload: { provider:'openrouter', remaining_rpm: 2, retry_after_ms: 250, action: 'queue' } });
    push(280, { sev: 'INFO',  agent: 'skeptic',      type: 'challenge.emitted',
      payload: { id: 'chal_r2_02', round: 2, agent_id: 'skeptic', stance: 'SUPPORT', target: 'claim_r2_01', content: challengeSamples[2].content, reasoning: challengeSamples[2].reasoning },
      edge: { from:'skeptic', to:'synthesizer', kind:'challenge', size:484, rtt:6, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'skeptic',      type: 'node.exit', payload: { node:'skeptic', round:2, duration_ms: 1260 }, deactivate: 'skeptic' });

    push( 30, { sev: 'INFO',  agent: 'visionary',    type: 'node.enter', payload: { node:'visionary', round:2 }, activate: 'visionary' });
    push(120, { sev: 'DEBUG', agent: 'visionary',    type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 1980, temperature: 0.7 } });
    push(1020, { sev: 'INFO', agent: 'visionary',    type: 'llm.call.complete',
      payload: { completion_tokens: 356, total_tokens: 2336, latency_ms: 1014, finish_reason: 'stop' } });
    push( 22, { sev: 'INFO',  agent: 'visionary',    type: 'lateral_idea.emitted',
      payload: { id: 'idea_r2_01', round: 2, agent_id: 'visionary', content: lateralSamples[2].content, novelty_rationale: lateralSamples[2].novelty },
      edge: { from:'visionary', to:'synthesizer', kind:'lateral_idea', size:516, rtt:7, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'visionary',    type: 'node.exit', payload: { node:'visionary', round:2, duration_ms: 1180 }, deactivate: 'visionary' });

    push( 30, { sev: 'INFO',  agent: 'synthesizer',  type: 'node.enter', payload: { node:'synthesizer', round:2 }, activate: 'synthesizer' });
    push(110, { sev: 'DEBUG', agent: 'synthesizer',  type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 3120, temperature: 0.3, inputs: { claims: 4, challenges: 3, ideas: 2 } } });
    push(1320, { sev: 'INFO', agent: 'synthesizer',  type: 'llm.call.complete',
      payload: { completion_tokens: 612, total_tokens: 3732, latency_ms: 1314, finish_reason: 'stop' } });
    push( 22, { sev: 'INFO',  agent: 'synthesizer',  type: 'synthesis.attempt',
      payload: { id: 'synth_r2', round: 2, confidence: 'MEDIUM', content: 'Hybrid 2–3 policy supported by HBR meta-analysis; pair with structured onboarding to neutralise Gartner penalty; tie-strength remains the primary risk for fully-remote weeks.', contributing_claim_ids: ['claim_r1_01','claim_r2_01','claim_r2_02'] },
      edge: { from:'synthesizer', to:'arbiter', kind:'synthesis', size:846, rtt:7, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'synthesizer',  type: 'node.exit', payload: { node:'synthesizer', round:2, duration_ms: 1480 }, deactivate: 'synthesizer' });

    push( 30, { sev: 'INFO',  agent: 'arbiter',      type: 'node.enter', payload: { node:'arbiter', round:2 }, activate: 'arbiter' });
    push(180, { sev: 'INFO',  agent: 'arbiter',      type: 'alignment.scored',
      payload: { round: 2, score: 0.5891, threshold: 0.65, decision: 'CONTINUE', reasoning: 'Synthesis improving but tie-strength challenge still partially unaddressed.' } });
    push( 30, { sev: 'INFO',  agent: 'arbiter',      type: 'round.complete', payload: { round: 2, alignment_score: 0.5891, claims: 4, challenges: 3, ideas: 2 },
      edge: { from:'arbiter', to:'orchestrator', kind:'control', size:128, rtt:3, status:'success' } });
    push( 16, { sev: 'INFO',  agent: 'arbiter',      type: 'node.exit', payload: { node:'arbiter', round:2, duration_ms: 256 }, deactivate: 'arbiter' });

    // ROUND 3 — converges
    push( 60, { sev: 'INFO',  agent: 'orchestrator', type: 'round.start', payload: { round: 3 } });
    push( 30, { sev: 'INFO',  agent: 'researcher',   type: 'node.enter', payload: { node:'researcher', round:3 }, activate: 'researcher' });
    push( 50, { sev: 'DEBUG', agent: 'researcher',   type: 'vector_store.query',
      payload: { query: 'cost analysis hybrid work onboarding mitigations', k: 3 },
      edge: { from:'researcher', to:'vector_store', kind:'kb.query', size:78, rtt:0, status:'pending' } });
    push(140, { sev: 'DEBUG', agent: 'vector_store', type: 'vector_store.result',
      payload: { docs_returned: 3, top_score: 0.793, latency_ms: 138, ids: ['doc_6','doc_7','doc_2'] },
      edge: { from:'vector_store', to:'researcher', kind:'docs', size:2890, rtt:138, status:'success' } });
    push(120, { sev: 'DEBUG', agent: 'researcher',   type: 'llm.call.start',
      payload: { model:'anthropic/claude-sonnet-4.5', prompt_tokens: 2680, temperature: 0.2 } });
    push(880, { sev: 'INFO',  agent: 'researcher',   type: 'llm.call.complete',
      payload: { completion_tokens: 354, total_tokens: 3034, latency_ms: 875, finish_reason: 'stop' } });
    push( 22, { sev: 'INFO',  agent: 'researcher',   type: 'claim.emitted',
      payload: { id: 'claim_r3_01', round: 3, agent_id: 'researcher', confidence: 'MEDIUM', content: claimSamples[3].content, evidence_summary: claimSamples[3].evidence },
      edge: { from:'researcher', to:'synthesizer', kind:'claim', size:472, rtt:5, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'researcher',   type: 'node.exit', payload: { node:'researcher', round:3, duration_ms: 1208 }, deactivate: 'researcher' });

    push( 28, { sev: 'INFO',  agent: 'skeptic',      type: 'node.enter', payload: { node:'skeptic', round:3 }, activate: 'skeptic' });
    push(110, { sev: 'DEBUG', agent: 'skeptic',      type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 2100, temperature: 0.4 } });
    push(840, { sev: 'INFO',  agent: 'skeptic',      type: 'llm.call.complete',
      payload: { completion_tokens: 312, total_tokens: 2412, latency_ms: 832, finish_reason: 'stop' } });
    push( 22, { sev: 'INFO',  agent: 'skeptic',      type: 'challenge.emitted',
      payload: { id: 'chal_r3_01', round: 3, agent_id: 'skeptic', stance: 'OPPOSE', target: 'claim_r3_01', content: challengeSamples[3].content, reasoning: challengeSamples[3].reasoning },
      edge: { from:'skeptic', to:'synthesizer', kind:'challenge', size:506, rtt:6, status:'error' } });
    push( 18, { sev: 'INFO',  agent: 'skeptic',      type: 'node.exit', payload: { node:'skeptic', round:3, duration_ms: 998 }, deactivate: 'skeptic' });

    push( 28, { sev: 'INFO',  agent: 'visionary',    type: 'node.enter', payload: { node:'visionary', round:3 }, activate: 'visionary' });
    push(120, { sev: 'DEBUG', agent: 'visionary',    type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 2240, temperature: 0.7 } });
    push(960, { sev: 'INFO',  agent: 'visionary',    type: 'llm.call.complete',
      payload: { completion_tokens: 318, total_tokens: 2558, latency_ms: 954, finish_reason: 'stop' } });
    push( 22, { sev: 'INFO',  agent: 'visionary',    type: 'lateral_idea.emitted',
      payload: { id: 'idea_r3_01', round: 3, agent_id: 'visionary', content: lateralSamples[3].content, novelty_rationale: lateralSamples[3].novelty },
      edge: { from:'visionary', to:'synthesizer', kind:'lateral_idea', size:528, rtt:6, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'visionary',    type: 'node.exit', payload: { node:'visionary', round:3, duration_ms: 1126 }, deactivate: 'visionary' });

    push( 28, { sev: 'INFO',  agent: 'synthesizer',  type: 'node.enter', payload: { node:'synthesizer', round:3 }, activate: 'synthesizer' });
    push(120, { sev: 'DEBUG', agent: 'synthesizer',  type: 'llm.call.start',
      payload: { model: 'anthropic/claude-sonnet-4.5', prompt_tokens: 3680, temperature: 0.3, inputs: { claims: 5, challenges: 4, ideas: 3 } } });
    push(1280, { sev: 'INFO', agent: 'synthesizer',  type: 'synthesis.attempt',
      payload: { id: 'synth_r3', round: 3, confidence: 'HIGH', content: 'Adopt hybrid 3-2 (3 in-office days/wk) for 6-month trial. Bookend with structured onboarding pair-programs and quarterly cross-team in-person weeks. Net cost neutral after stipend offset.', contributing_claim_ids: ['claim_r1_01','claim_r2_01','claim_r2_02','claim_r3_01'] },
      edge: { from:'synthesizer', to:'arbiter', kind:'synthesis', size:912, rtt:6, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'synthesizer',  type: 'node.exit', payload: { node:'synthesizer', round:3, duration_ms: 1418 }, deactivate: 'synthesizer' });

    push( 24, { sev: 'INFO',  agent: 'arbiter',      type: 'node.enter', payload: { node:'arbiter', round:3 }, activate: 'arbiter' });
    push(160, { sev: 'INFO',  agent: 'arbiter',      type: 'alignment.scored',
      payload: { round: 3, score: 0.7842, threshold: 0.65, decision: 'CONVERGE', reasoning: 'Score exceeds threshold; major challenges resolved or refined into the synthesis.' } });
    push( 30, { sev: 'INFO',  agent: 'arbiter',      type: 'run.complete',
      payload: { run_id: RUN_ID, rounds: 3, alignment_score: 0.7842, total_claims: 5, total_challenges: 4, total_ideas: 3, duration_ms: 13420, status: 'CONVERGED' },
      edge: { from:'arbiter', to:'orchestrator', kind:'control', size:188, rtt:3, status:'success' } });
    push( 18, { sev: 'INFO',  agent: 'arbiter',      type: 'node.exit', payload: { node:'arbiter', round:3, duration_ms: 208 }, deactivate: 'arbiter' });

    push(800, { sev: 'INFO',  agent: 'system',       type: 'idle', payload: { reason: 'awaiting next run' } });

    return seq;
  }

  const SEQUENCE = buildSequence();

  // ── Player ─────────────────────────────────────────────────────────────────
  // Drives event emission against a wall-clock; supports speed multiplier and pause.
  function createPlayer({ onEvent, speed = 1, paused = false }) {
    let idx = 0;
    let speedMul = speed;
    let isPaused = paused;
    let timer = null;
    let cycle = 0;

    function schedule() {
      if (isPaused) return;
      if (idx >= SEQUENCE.length) {
        idx = 0;
        cycle++;
      }
      const ev = SEQUENCE[idx];
      const wait = Math.max(8, ev.dt / speedMul);
      timer = setTimeout(() => {
        const stamped = { ...ev, _cycle: cycle, _seq: idx + cycle * SEQUENCE.length };
        idx++;
        onEvent(stamped);
        schedule();
      }, wait);
    }

    return {
      start(){ schedule(); },
      stop(){ if(timer){clearTimeout(timer);timer=null;} },
      pause(){ isPaused = true; if(timer){clearTimeout(timer);timer=null;} },
      resume(){ if(isPaused){ isPaused = false; schedule(); } },
      setSpeed(m){ speedMul = m; },
      get index(){ return idx; },
    };
  }

  window.ThinkTankSim = {
    AGENTS, TOPIC, RUN_ID, SEQUENCE, createPlayer, fmtJSON,
  };
})();

</script><script type="text/babel">
/* ─── tweaks-panel.jsx ─────────────────────────────────────── */

// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;width:100%;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null
      ? keyOrEdits : { [keyOrEdits]: val };
    setValues((prev) => ({ ...prev, ...edits }));
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', { detail: edits }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({ title = 'Tweaks', noDeckControls = false, children }) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  // Auto-inject a rail toggle when a <deck-stage> is on the page. The
  // toggle drives the deck's per-viewer _railVisible via window message;
  // state is mirrored from the same localStorage key the deck reads so
  // the control reflects reality across reloads. The mechanism is the
  // message — authors who want custom placement can post it directly
  // and pass noDeckControls to suppress this one.
  const hasDeckStage = React.useMemo(
    () => typeof document !== 'undefined' && !!document.querySelector('deck-stage'),
    [],
  );
  // Hide the toggle until the host has actually enabled the rail (the
  // __omelette_rail_enabled window message, posted only when the
  // omelette_deck_rail_enabled flag is on for this user). The initial read
  // covers TweaksPanel mounting after the message already arrived; the
  // listener covers the common case of mounting first.
  const [railEnabled, setRailEnabled] = React.useState(
    () => hasDeckStage && !!document.querySelector('deck-stage')?._railEnabled,
  );
  React.useEffect(() => {
    if (!hasDeckStage || railEnabled) return undefined;
    const onMsg = (e) => {
      if (e.data && e.data.type === '__omelette_rail_enabled') setRailEnabled(true);
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, [hasDeckStage, railEnabled]);
  const [railVisible, setRailVisible] = React.useState(() => {
    try { return localStorage.getItem('deck-stage.railVisible') !== '0'; } catch (e) { return true; }
  });
  const toggleRail = (on) => {
    setRailVisible(on);
    window.postMessage({ type: '__deck_rail_visible', on }, '*');
  };
  const offsetRef = React.useRef({ x: 16, y: 16 });
  const PAD = 16;

  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth, h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y)),
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);

  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);

  React.useEffect(() => {
    const onMsg = (e) => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);
      else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({ type: '__edit_mode_dismissed' }, '*');
  };

  const onDragStart = (e) => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX, sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = (ev) => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy),
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  if (!open) return null;
  return (
    <>
      <style>{__TWEAKS_STYLE}</style>
      <div ref={dragRef} className="twk-panel" data-noncommentable=""
           style={{ right: offsetRef.current.x, bottom: offsetRef.current.y }}>
        <div className="twk-hd" onMouseDown={onDragStart}>
          <b>{title}</b>
          <button className="twk-x" aria-label="Close tweaks"
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={dismiss}>✕</button>
        </div>
        <div className="twk-body">
          {children}
          {hasDeckStage && railEnabled && !noDeckControls && (
            <TweakSection label="Deck">
              <TweakToggle label="Thumbnail rail" value={railVisible} onChange={toggleRail} />
            </TweakSection>
          )}
        </div>
      </div>
    </>
  );
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({ label, children }) {
  return (
    <>
      <div className="twk-sect">{label}</div>
      {children}
    </>
  );
}

function TweakRow({ label, value, children, inline = false }) {
  return (
    <div className={inline ? 'twk-row twk-row-h' : 'twk-row'}>
      <div className="twk-lbl">
        <span>{label}</span>
        {value != null && <span className="twk-val">{value}</span>}
      </div>
      {children}
    </div>
  );
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({ label, value, min = 0, max = 100, step = 1, unit = '', onChange }) {
  return (
    <TweakRow label={label} value={`${value}${unit}`}>
      <input type="range" className="twk-slider" min={min} max={max} step={step}
             value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </TweakRow>
  );
}

function TweakToggle({ label, value, onChange }) {
  return (
    <div className="twk-row twk-row-h">
      <div className="twk-lbl"><span>{label}</span></div>
      <button type="button" className="twk-toggle" data-on={value ? '1' : '0'}
              role="switch" aria-checked={!!value}
              onClick={() => onChange(!value)}><i /></button>
    </div>
  );
}

function TweakRadio({ label, value, options, onChange }) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = (o) => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({ 2: 16, 3: 10 }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = (s) => {
      const m = options.find((o) => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return <TweakSelect label={label} value={value} options={options}
                        onChange={(s) => onChange(resolve(s))} />;
  }
  const opts = options.map((o) => (typeof o === 'object' ? o : { value: o, label: o }));
  const idx = Math.max(0, opts.findIndex((o) => o.value === value));
  const n = opts.length;

  const segAt = (clientX) => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor(((clientX - r.left - 2) / inner) * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };

  const onPointerDown = (e) => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = (ev) => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <TweakRow label={label}>
      <div ref={trackRef} role="radiogroup" onPointerDown={onPointerDown}
           className={dragging ? 'twk-seg dragging' : 'twk-seg'}>
        <div className="twk-seg-thumb"
             style={{ left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
                      width: `calc((100% - 4px) / ${n})` }} />
        {opts.map((o) => (
          <button key={o.value} type="button" role="radio" aria-checked={o.value === value}>
            {o.label}
          </button>
        ))}
      </div>
    </TweakRow>
  );
}

function TweakSelect({ label, value, options, onChange }) {
  return (
    <TweakRow label={label}>
      <select className="twk-field" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => {
          const v = typeof o === 'object' ? o.value : o;
          const l = typeof o === 'object' ? o.label : o;
          return <option key={v} value={v}>{l}</option>;
        })}
      </select>
    </TweakRow>
  );
}

function TweakText({ label, value, placeholder, onChange }) {
  return (
    <TweakRow label={label}>
      <input className="twk-field" type="text" value={value} placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)} />
    </TweakRow>
  );
}

function TweakNumber({ label, value, min, max, step = 1, unit = '', onChange }) {
  const clamp = (n) => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({ x: 0, val: 0 });
  const onScrubStart = (e) => {
    e.preventDefault();
    startRef.current = { x: e.clientX, val: value };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = (ev) => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <div className="twk-num">
      <span className="twk-num-lbl" onPointerDown={onScrubStart}>{label}</span>
      <input type="number" value={value} min={min} max={max} step={step}
             onChange={(e) => onChange(clamp(Number(e.target.value)))} />
      {unit && <span className="twk-num-unit">{unit}</span>}
    </div>
  );
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, (c) => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}

const __TwkCheck = ({ light }) => (
  <svg viewBox="0 0 14 14" aria-hidden="true">
    <path d="M3 7.2 5.8 10 11 4.2" fill="none" strokeWidth="2.2"
          strokeLinecap="round" strokeLinejoin="round"
          stroke={light ? 'rgba(0,0,0,.78)' : '#fff'} />
  </svg>
);

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({ label, value, options, onChange }) {
  if (!options || !options.length) {
    return (
      <div className="twk-row twk-row-h">
        <div className="twk-lbl"><span>{label}</span></div>
        <input type="color" className="twk-swatch" value={value}
               onChange={(e) => onChange(e.target.value)} />
      </div>
    );
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = (o) => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return (
    <TweakRow label={label}>
      <div className="twk-chips" role="radiogroup">
        {options.map((o, i) => {
          const colors = Array.isArray(o) ? o : [o];
          const [hero, ...rest] = colors;
          const sup = rest.slice(0, 4);
          const on = key(o) === cur;
          return (
            <button key={i} type="button" className="twk-chip" role="radio"
                    aria-checked={on} data-on={on ? '1' : '0'}
                    aria-label={colors.join(', ')} title={colors.join(' · ')}
                    style={{ background: hero }}
                    onClick={() => onChange(o)}>
              {sup.length > 0 && (
                <span>
                  {sup.map((c, j) => <i key={j} style={{ background: c }} />)}
                </span>
              )}
              {on && <__TwkCheck light={__twkIsLight(hero)} />}
            </button>
          );
        })}
      </div>
    </TweakRow>
  );
}

function TweakButton({ label, onClick, secondary = false }) {
  return (
    <button type="button" className={secondary ? 'twk-btn secondary' : 'twk-btn'}
            onClick={onClick}>{label}</button>
  );
}

Object.assign(window, {
  useTweaks, TweaksPanel, TweakSection, TweakRow,
  TweakSlider, TweakToggle, TweakRadio, TweakSelect,
  TweakText, TweakNumber, TweakColor, TweakButton,
});

</script><script type="text/babel">
/* ─── graph.jsx ─────────────────────────────────────── */
// graph.jsx — Section 1: Agent Interaction Graph
// Renders a curated SVG network of the Think Tank agents. Edges animate when
// fired by the simulator; idle agents (>5s since last activity) dim.

const NODE_POSITIONS = {
  // canvas is normalized 1400 x 300, padded internally
  vector_store: { x: 130,  y: 150, r: 26, kind: 'svc', accent: '#94a3b8' },
  researcher:   { x: 320,  y: 80,  r: 34, kind: 'agt', accent: '#ff8a3d' },
  skeptic:      { x: 320,  y: 220, r: 34, kind: 'agt', accent: '#ef4444' },
  visionary:    { x: 600,  y: 150, r: 34, kind: 'agt', accent: '#f5cf00' },
  synthesizer:  { x: 880,  y: 150, r: 38, kind: 'agt', accent: '#7c5cff' },
  arbiter:      { x: 1180, y: 150, r: 34, kind: 'agt', accent: '#22d3ee' },
};

const NODE_LABELS = {
  vector_store: { name: 'Vector Store', role: 'kb · chroma' },
  researcher:   { name: 'Researcher',   role: 'evidence' },
  skeptic:      { name: 'Skeptic',      role: 'challenger' },
  visionary:    { name: 'Visionary',    role: 'lateral' },
  synthesizer:  { name: 'Synthesizer',  role: 'merger' },
  arbiter:      { name: 'Arbiter',      role: 'judge' },
};

// Static edges that always exist (for the resting topology)
const STATIC_EDGES = [
  { from: 'researcher',  to: 'vector_store', curve: -0.20, kind: 'kb.query',     bidir: true },
  { from: 'researcher',  to: 'synthesizer',  curve:  0.10, kind: 'claim' },
  { from: 'skeptic',     to: 'synthesizer',  curve: -0.10, kind: 'challenge' },
  { from: 'visionary',   to: 'synthesizer',  curve:  0.00, kind: 'lateral_idea' },
  { from: 'synthesizer', to: 'arbiter',      curve:  0.00, kind: 'synthesis' },
  { from: 'arbiter',     to: 'researcher',   curve:  0.40, kind: 'next_round' },
];

function edgeKey(from, to){ return from + '→' + to; }

function curvedPath(p1, p2, curve){
  const mx = (p1.x + p2.x) / 2;
  const my = (p1.y + p2.y) / 2;
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  const nx = -dy, ny = dx;
  const len = Math.sqrt(nx*nx + ny*ny) || 1;
  const cx = mx + (nx/len) * curve * 100;
  const cy = my + (ny/len) * curve * 100;
  return { d: `M ${p1.x} ${p1.y} Q ${cx} ${cy} ${p2.x} ${p2.y}`, midX: cx, midY: cy };
}

// Trim a line by a radius from each endpoint (so arrows don't sit on top of nodes)
function trimEnds(p1, p2, r1, r2){
  const dx = p2.x - p1.x, dy = p2.y - p1.y;
  const len = Math.sqrt(dx*dx + dy*dy) || 1;
  const ux = dx/len, uy = dy/len;
  return {
    a: { x: p1.x + ux*r1, y: p1.y + uy*r1 },
    b: { x: p2.x - ux*r2, y: p2.y - uy*r2 },
  };
}

function statusColor(status){
  switch(status){
    case 'success': return '#22c55e';
    case 'error':   return '#ef4444';
    case 'warn':    return '#f5a623';
    case 'pending':
    default:        return '#5c6370';
  }
}

function AgentGraph({ agentStates, liveEdges, elapsedMs, runStatus }){
  const nodes = Object.keys(NODE_POSITIONS);

  // resolve edge highlights — keep most recent fire of each edge
  const edgeFx = {};
  liveEdges.forEach(e => {
    edgeFx[edgeKey(e.from, e.to)] = e;
  });

  const fmtMs = (ms) => {
    if (ms < 1000) return ms + 'ms';
    return (ms/1000).toFixed(2) + 's';
  };
  const fmtBytes = (b) => {
    if (!b && b !== 0) return '—';
    if (b < 1024) return b + 'B';
    return (b/1024).toFixed(1) + 'KB';
  };

  return (
    <div className="sec graph">
      <div className="sec-hdr">
        <span className="sec-title">Agent Interaction Graph</span>
        <span className="sec-badge">5 agents · 1 service</span>
        <div className="sec-spacer"/>
        <span style={{display:'flex',alignItems:'center',gap:7,fontFamily:'var(--mono)',fontSize:11,color:'var(--ok)'}}>
          <span className="hdr-pulse-dot"/> live topology
        </span>
      </div>
      <div className="graph-canvas">
        <div className="graph-grid"/>
        <div className="graph-clock">
          <span>elapsed</span>
          <b>{fmtMs(elapsedMs)}</b>
          <span style={{color:'var(--text-4)'}}>·</span>
          <span>round</span>
          <b>{Math.max(1, agentStates.__round || 1)}/6</b>
          <span style={{color:'var(--text-4)'}}>·</span>
          <span>status</span>
          <b style={{color: runStatus==='converged' ? 'var(--ok)' : 'var(--accent)'}}>{runStatus}</b>
        </div>

        <svg viewBox="0 0 1400 300" preserveAspectRatio="xMidYMid meet">
          <defs>
            <marker id="arr-ok"   viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" fill="#22c55e"/>
            </marker>
            <marker id="arr-err"  viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" fill="#ef4444"/>
            </marker>
            <marker id="arr-warn" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" fill="#f5a623"/>
            </marker>
            <marker id="arr-pend" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" fill="#5c6370"/>
            </marker>
            <marker id="arr-idle" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" fill="#33383f"/>
            </marker>
            <radialGradient id="gNodeAct" cx="0.5" cy="0.5" r="0.5">
              <stop offset="0%" stopColor="rgba(124,92,255,0.45)"/>
              <stop offset="100%" stopColor="rgba(124,92,255,0)"/>
            </radialGradient>
          </defs>

          {/* Edges (static base + live overrides) */}
          {STATIC_EDGES.map((e, i) => {
            const p1 = NODE_POSITIONS[e.from];
            const p2 = NODE_POSITIONS[e.to];
            const trimmed = trimEnds(p1, p2, p1.r, p2.r);
            const path = curvedPath(trimmed.a, trimmed.b, e.curve);
            const fx = edgeFx[edgeKey(e.from, e.to)];
            const isHot = !!fx && (Date.now() - fx._firedAt < 1400);
            const status = isHot ? fx.status : 'idle';
            const color = isHot ? statusColor(status) : '#33383f';
            const marker = isHot ? `url(#arr-${status === 'pending' ? 'pend' : status === 'success' ? 'ok' : status === 'error' ? 'err' : 'warn'})` : 'url(#arr-idle)';
            const sw = isHot ? 1.6 : 1;
            const dashOff = isHot ? '0;-32' : '0';

            return (
              <g key={i}>
                <path d={path.d} fill="none" stroke={color} strokeWidth={sw}
                      markerEnd={marker}
                      strokeDasharray={isHot && status==='pending' ? '4 5' : (isHot ? 'none' : 'none')}
                      style={{transition:'stroke 220ms, stroke-width 220ms'}}/>
                {/* shimmer overlay for hot edges */}
                {isHot && (
                  <path d={path.d} fill="none" stroke={color} strokeWidth={3} opacity="0.35"
                        strokeDasharray="6 14"
                        style={{filter:'blur(1.5px)'}}>
                    <animate attributeName="stroke-dashoffset" from="0" to="-40" dur="1s" repeatCount="indefinite"/>
                  </path>
                )}
                {/* edge label (only render when hot, clearly visible) */}
                {isHot && (
                  <g>
                    <text x={path.midX} y={path.midY - 9} className="edge-label bg" textAnchor="middle">
                      {fx.kind} · {fmtBytes(fx.size)} · {fmtMs(fx.rtt)}
                    </text>
                    <text x={path.midX} y={path.midY - 9} className="edge-label" textAnchor="middle" fill={color}>
                      {fx.kind} · {fmtBytes(fx.size)} · {fmtMs(fx.rtt)}
                    </text>
                  </g>
                )}
                {/* resting label, dim */}
                {!isHot && (
                  <text x={path.midX} y={path.midY - 7} className="edge-label" textAnchor="middle" fill="#4a4f57" opacity="0.85">
                    {e.kind}
                  </text>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((id) => {
            const p = NODE_POSITIONS[id];
            const lbl = NODE_LABELS[id];
            const a = agentStates[id] || { state: 'idle', lastSeen: 0 };
            const sinceMs = Date.now() - (a.lastSeen || 0);
            const idle = sinceMs > 5000 && a.state !== 'running';
            const running = a.state === 'running';
            const erred = a.state === 'error';
            const completed = a.state === 'completed';
            const stroke = running ? p.accent : (erred ? '#ef4444' : (completed ? '#22c55e' : '#2c3138'));
            const fill   = running ? '#181b21' : (idle ? '#0f1115' : '#13161b');
            const opacity = idle ? 0.55 : 1;

            return (
              <g key={id} opacity={opacity} style={{transition:'opacity 280ms'}}>
                {running && <circle cx={p.x} cy={p.y} r={p.r + 22} fill="url(#gNodeAct)"/>}
                {running && (
                  <circle cx={p.x} cy={p.y} r={p.r + 4} fill="none" stroke={p.accent} strokeWidth="1" opacity="0.5">
                    <animate attributeName="r" values={`${p.r+4};${p.r+12};${p.r+4}`} dur="1.6s" repeatCount="indefinite"/>
                    <animate attributeName="opacity" values="0.55;0;0.55" dur="1.6s" repeatCount="indefinite"/>
                  </circle>
                )}
                <circle cx={p.x} cy={p.y} r={p.r} fill={fill} stroke={stroke} strokeWidth={running ? 2 : 1.2}
                        style={{transition:'stroke 220ms, fill 220ms, stroke-width 220ms'}}/>
                {/* tiny status dot */}
                <circle cx={p.x + p.r - 4} cy={p.y - p.r + 4} r="4"
                        fill={running ? p.accent : (erred ? '#ef4444' : (completed ? '#22c55e' : '#3a3f47'))}/>
                <circle cx={p.x + p.r - 4} cy={p.y - p.r + 4} r="2"
                        fill={running ? '#fff' : 'transparent'}/>
                <text x={p.x} y={p.y - 4} className="node-label">{lbl.name}</text>
                <text x={p.x} y={p.y + 10} className="node-role">{lbl.role}</text>
                {/* tasks badge */}
                {a.tasks > 0 && (
                  <g>
                    <rect x={p.x - 14} y={p.y + p.r + 4} width="28" height="14" rx="3" fill="#0f1115" stroke="#22262d"/>
                    <text x={p.x} y={p.y + p.r + 11} textAnchor="middle"
                          style={{fontFamily:'var(--mono)', fontSize:'9px', fill:'var(--text-2)'}}>
                      {a.tasks} tasks
                    </text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>

        <div className="graph-legend">
          <span className="lg"><span className="lg-dot" style={{background:'#22c55e'}}/>success</span>
          <span className="lg"><span className="lg-dot" style={{background:'#ef4444'}}/>error</span>
          <span className="lg"><span className="lg-dot" style={{background:'#f5a623'}}/>timeout / retry</span>
          <span className="lg"><span className="lg-dot" style={{background:'#5c6370'}}/>pending</span>
          <span className="lg"><span className="lg-dot" style={{background:'#33383f'}}/>idle</span>
        </div>
      </div>
    </div>
  );
}

window.AgentGraph = AgentGraph;
window.NODE_POSITIONS = NODE_POSITIONS;
window.NODE_LABELS = NODE_LABELS;

</script><script type="text/babel">
/* ─── stream.jsx ─────────────────────────────────────── */
// stream.jsx — Section 2: Structured Event Stream
// Reverse-chronological, filterable, searchable. Each row has copy + expand.

const SEVERITIES = ['DEBUG', 'INFO', 'WARN', 'ERROR'];

function fmtTs(d){
  // "12:48:03.247Z" UTC ms-precision
  const hh = String(d.getUTCHours()).padStart(2,'0');
  const mm = String(d.getUTCMinutes()).padStart(2,'0');
  const ss = String(d.getUTCSeconds()).padStart(2,'0');
  const ms = String(d.getUTCMilliseconds()).padStart(3,'0');
  return { hms: `${hh}:${mm}:${ss}`, ms };
}

function truncate(s, n){
  if (s.length <= n) return s;
  return s.slice(0, n) + '…';
}

// Lightly-coloured pretty-printed JSON
function colorJson(obj){
  const s = JSON.stringify(obj, null, 2);
  // basic tokenizer; safe-ish since we control inputs
  return s
    .replace(/&/g, '&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"([^"\\]+)":/g, '<span class="k">"$1"</span>:')
    .replace(/: "([^"\\]*)"/g, ': <span class="s">"$1"</span>')
    .replace(/: (-?\d+(?:\.\d+)?)/g, ': <span class="n">$1</span>')
    .replace(/: (true|false|null)/g, ': <span class="b">$1</span>');
}

function inlinePayload(obj){
  // one-liner for collapsed view
  const s = JSON.stringify(obj);
  return s
    .replace(/&/g, '&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"([^"\\]+)":/g, '<span class="k">$1</span>:')
    .replace(/"([^"\\]*)"/g, '<span class="s">"$1"</span>')
    .replace(/(?<=[:,\[\s])(-?\d+(?:\.\d+)?)/g, '<span class="n">$1</span>')
    .replace(/(?<=[:,\[\s])(true|false|null)/g, '<span class="b">$1</span>');
}

function EventRow({ evt, expanded, onToggle, onCopy, copiedId }){
  const ts = fmtTs(evt.timestamp);
  const agentMeta = window.NODE_LABELS[evt.agent] || { name: evt.agent === 'system' ? 'system' : evt.agent, role: '' };
  const dotColor = (window.NODE_POSITIONS[evt.agent]?.accent) || '#6b7280';

  const inline = inlinePayload(evt.payload);
  const truncated = inline.length > 200 ? truncate(inline, 200) : inline;

  return (
    <div className={`evt ${evt._isNew ? 'evt-new' : ''} ${expanded ? 'exp' : ''}`}>
      <div className="evt-ts">
        <b>{ts.hms}</b>.{ts.ms}<span style={{color:'var(--text-4)'}}>Z</span>
      </div>
      <div>
        <span className={`evt-sev ${evt.sev}`}>{evt.sev}</span>
      </div>
      <div className="evt-agent">
        <span className="dot" style={{background:dotColor}}/>
        <span className="nm">{agentMeta.name}</span>
      </div>
      <div className="evt-body">
        <div className="evt-type">{evt.type}</div>
        {expanded ? (
          <pre className="evt-payload" dangerouslySetInnerHTML={{__html: colorJson(evt.payload)}}/>
        ) : (
          <div className="evt-payload" dangerouslySetInnerHTML={{__html: truncated}}/>
        )}
      </div>
      <div className="evt-actions">
        <button className={`icon-btn ${copiedId === evt._seq ? 'copied' : ''}`}
                title="Copy payload"
                onClick={() => onCopy(evt)}>
          <svg width="14" height="14"><use href={copiedId === evt._seq ? '#ic-check' : '#ic-copy'}/></svg>
        </button>
        <button className="icon-btn" title={expanded ? 'Collapse' : 'Expand'}
                onClick={() => onToggle(evt._seq)}
                style={{transform: expanded ? 'rotate(180deg)' : 'none'}}>
          <svg width="14" height="14"><use href="#ic-chev"/></svg>
        </button>
      </div>
    </div>
  );
}

function EventStream({
  events, paused, onTogglePause, onClear,
  filterAgents, setFilterAgents,
  filterSev, setFilterSev,
  filterType, setFilterType,
  search, setSearch,
}){
  const [expandedSet, setExpandedSet] = React.useState(new Set());
  const [copiedId, setCopiedId] = React.useState(null);

  const toggleExpanded = (seq) => {
    setExpandedSet(prev => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq); else next.add(seq);
      return next;
    });
  };

  const onCopy = (evt) => {
    try { navigator.clipboard.writeText(JSON.stringify(evt.payload, null, 2)); } catch(e){}
    setCopiedId(evt._seq);
    setTimeout(() => setCopiedId(c => c === evt._seq ? null : c), 1200);
  };

  // Filtering
  const allTypes = React.useMemo(() => {
    const s = new Set();
    events.forEach(e => s.add(e.type));
    return Array.from(s).sort();
  }, [events]);

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return events.filter(e => {
      if (filterSev.size > 0 && !filterSev.has(e.sev)) return false;
      if (filterAgents.size > 0 && !filterAgents.has(e.agent)) return false;
      if (filterType && e.type !== filterType) return false;
      if (q) {
        const blob = (e.type + ' ' + e.agent + ' ' + JSON.stringify(e.payload)).toLowerCase();
        if (!blob.includes(q)) return false;
      }
      return true;
    });
  }, [events, filterSev, filterAgents, filterType, search]);

  const toggleSev = (s) => {
    setFilterSev(prev => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s); else next.add(s);
      return next;
    });
  };
  const toggleAgent = (a) => {
    setFilterAgents(prev => {
      const next = new Set(prev);
      if (next.has(a)) next.delete(a); else next.add(a);
      return next;
    });
  };

  const agents = ['researcher','skeptic','visionary','synthesizer','arbiter','vector_store','orchestrator'];

  return (
    <div className="sec stream">
      <div className="sec-hdr">
        <span className="sec-title">Event Stream</span>
        <span className="sec-badge">graph.stream() · reverse-chronological</span>
        <div className="sec-spacer"/>
        <button className="hdr-btn" onClick={onTogglePause} title={paused ? 'Resume' : 'Pause'}>
          <svg width="12" height="12"><use href={paused ? '#ic-play' : '#ic-pause'}/></svg>
          {paused ? 'Resume' : 'Pause'}
        </button>
        <button className="hdr-btn" onClick={onClear} title="Clear">
          <svg width="12" height="12"><use href="#ic-clear"/></svg>
          Clear
        </button>
        <button className="hdr-btn" title="Export NDJSON">
          <svg width="12" height="12"><use href="#ic-dl"/></svg>
          Export
        </button>
      </div>
      <div className="stream-toolbar">
        <div className="stream-search">
          <svg width="13" height="13" style={{color:'var(--text-3)'}}><use href="#ic-search"/></svg>
          <input
            value={search}
            placeholder="search payloads, types, ids…  (e.g. claim_r2 · alignment_score · synthesizer)"
            onChange={(e)=>setSearch(e.target.value)}
          />
          {search && (
            <button className="icon-btn" onClick={()=>setSearch('')} title="Clear">
              <svg width="12" height="12"><path stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" d="M3 3l8 8 M11 3l-8 8"/></svg>
            </button>
          )}
        </div>
        {SEVERITIES.map(s => (
          <button key={s} className={`chip sev-${s} ${filterSev.has(s) ? 'on' : ''}`}
                  onClick={()=>toggleSev(s)}>
            <span className="chip-dot" style={{background:`var(--sev-${s.toLowerCase()})`}}/>
            {s}
          </button>
        ))}
      </div>
      <div className="stream-toolbar" style={{paddingTop:0,paddingBottom:8,gap:6,flexWrap:'wrap'}}>
        <span style={{fontFamily:'var(--mono)',fontSize:10,color:'var(--text-3)',letterSpacing:'0.06em',textTransform:'uppercase',marginRight:4}}>agents</span>
        {agents.map(a => {
          const lbl = window.NODE_LABELS[a] || { name: a };
          const on = filterAgents.has(a);
          return (
            <button key={a} className={`chip ${on ? 'on' : ''}`} onClick={()=>toggleAgent(a)}>
              <span className="chip-dot" style={{background: window.NODE_POSITIONS[a]?.accent || '#6b7280'}}/>
              {lbl.name.toLowerCase()}
            </button>
          );
        })}
        <div style={{flex:1}}/>
        <span className="stream-count">
          showing <b>{filtered.length}</b> / <b>{events.length}</b> events
          {paused && <span style={{color:'var(--warn)',marginLeft:8}}>· paused</span>}
        </span>
      </div>
      <div className="stream-list">
        {filtered.length === 0 && (
          <div style={{padding:'28px 14px',color:'var(--text-3)',fontFamily:'var(--mono)',fontSize:11.5,textAlign:'center'}}>
            no events match the current filters
          </div>
        )}
        {filtered.map((evt) => (
          <EventRow
            key={evt._seq}
            evt={evt}
            expanded={expandedSet.has(evt._seq)}
            onToggle={toggleExpanded}
            onCopy={onCopy}
            copiedId={copiedId}
          />
        ))}
      </div>
    </div>
  );
}

window.EventStream = EventStream;

</script><script type="text/babel">
/* ─── sidebar.jsx ─────────────────────────────────────── */
// sidebar.jsx — Section 3: Agent Status Panel (right sidebar)

const AGENT_ORDER = ['researcher','skeptic','visionary','synthesizer','arbiter','vector_store'];

function fmtUptime(ms){
  const s = Math.floor(ms/1000);
  const m = Math.floor(s/60);
  const r = s % 60;
  return `${String(m).padStart(2,'0')}:${String(r).padStart(2,'0')}`;
}

function AgentCard({ id, agent }){
  const meta = window.NODE_LABELS[id] || { name: id, role: '' };
  const accent = window.NODE_POSITIONS[id]?.accent || '#6b7280';
  const state = agent.state || 'idle';
  const initials = meta.name.split(/\s+/).map(w => w[0]).join('').slice(0,2).toUpperCase();

  // sparkline of activity bins (last 16 ticks)
  const spark = (agent.spark || new Array(16).fill(0));
  const max = Math.max(1, ...spark);

  return (
    <div className={`acard ${state}`}>
      <div className="acard-bar"/>
      <div className="acard-row">
        <div className="acard-icon" style={{background: accent, color:'#0a0b0d'}}>{initials}</div>
        <div style={{display:'flex',flexDirection:'column',minWidth:0,flex:1}}>
          <div className="acard-name">{meta.name}</div>
          <div className="acard-role">{meta.role}</div>
        </div>
        <div className={`acard-state ${state}`}>
          <span className="sd"/>{state}
        </div>
      </div>
      <div className="acard-stats">
        <div className="acard-stat">
          <div className="acard-stat-k">tasks</div>
          <div className="acard-stat-v">{agent.tasks || 0}</div>
        </div>
        <div className="acard-stat">
          <div className="acard-stat-k">uptime</div>
          <div className="acard-stat-v">{fmtUptime(agent.uptime || 0)}</div>
        </div>
        <div className="acard-stat">
          <div className="acard-stat-k">errors</div>
          <div className={`acard-stat-v ${agent.errors > 0 ? 'err' : ''}`}>{agent.errors || 0}</div>
        </div>
      </div>
      <div className="acard-last">
        <span className="lbl">Last action</span>
        {agent.lastAction || <span style={{color:'var(--text-4)'}}>— awaiting first event —</span>}
      </div>
      <div className="acard-spark" title="Recent activity">
        {spark.map((v, i) => (
          <div key={i} className="b" style={{
            height: `${(v/max)*100}%`,
            background: accent,
            opacity: state === 'running' ? (0.4 + (v/max)*0.6) : (0.2 + (v/max)*0.4),
          }}/>
        ))}
      </div>
    </div>
  );
}

function AgentSidebar({ agentStates }){
  const running = AGENT_ORDER.filter(id => (agentStates[id]?.state) === 'running').length;
  return (
    <div className="sec sidebar">
      <div className="sec-hdr">
        <span className="sec-title">Agents</span>
        <span className="sec-badge">{running} running · {AGENT_ORDER.length} total</span>
      </div>
      <div className="sidebar-list">
        {AGENT_ORDER.map(id => (
          <AgentCard key={id} id={id} agent={agentStates[id] || {}}/>
        ))}
      </div>
    </div>
  );
}

window.AgentSidebar = AgentSidebar;

</script><script type="text/babel">
/* ─── metrics.jsx ─────────────────────────────────────── */
// metrics.jsx — Section 4: System Metrics strip
// Elapsed · messages · error rate · active agents · throughput sparkline · latency gauges

function fmtElapsed(ms){
  const s = Math.floor(ms/1000);
  const m = Math.floor(s/60);
  const r = s % 60;
  const ms3 = String(ms % 1000).padStart(3,'0');
  return `${String(m).padStart(2,'0')}:${String(r).padStart(2,'0')}.${ms3}`;
}

function Sparkline({ data, color = '#7c5cff' }){
  // data: array of numbers, render last 60 bins
  const w = 220, h = 48, pad = 2;
  const slice = data.slice(-60);
  const max = Math.max(1, ...slice);
  const stepX = (w - pad*2) / Math.max(1, slice.length - 1);

  // Area path
  const points = slice.map((v, i) => {
    const x = pad + i * stepX;
    const y = pad + (h - pad*2) * (1 - v/max);
    return [x, y];
  });
  const linePath = points.length === 0 ? '' :
    'M ' + points.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L ');
  const areaPath = points.length === 0 ? '' :
    linePath + ` L ${pad + (slice.length-1)*stepX} ${h-pad} L ${pad} ${h-pad} Z`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="spark-svg">
      <defs>
        <linearGradient id="sparkGrad" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.5"/>
          <stop offset="100%" stopColor={color} stopOpacity="0"/>
        </linearGradient>
      </defs>
      {/* y gridlines */}
      {[0.25, 0.5, 0.75].map((g, i) => (
        <line key={i} x1={pad} x2={w-pad} y1={pad + (h-pad*2)*g} y2={pad + (h-pad*2)*g}
              stroke="rgba(255,255,255,0.04)" strokeWidth="1"/>
      ))}
      <path d={areaPath} fill="url(#sparkGrad)"/>
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round"/>
      {points.length > 0 && (
        <circle cx={points[points.length-1][0]} cy={points[points.length-1][1]} r="2.4" fill={color}/>
      )}
    </svg>
  );
}

function Gauge({ k, value, max, unit, warn }){
  const pct = Math.min(1, value / max);
  const v = Math.round(value);
  return (
    <div className="gauge">
      <div className="gauge-k">{k}</div>
      <div className="gauge-bar">
        <div className={`gauge-fill ${warn ? 'warn' : ''}`} style={{width: (pct*100).toFixed(1) + '%', transition:'width 320ms'}}/>
      </div>
      <div className="gauge-v">{v}<span className="u"> {unit}</span></div>
    </div>
  );
}

function MetricsStrip({ metrics, throughput, latency, runStatus }){
  const errPct = metrics.totalEvents > 0 ? (metrics.errors / metrics.totalEvents * 100) : 0;
  const trips = throughput.slice(-1)[0] || 0;

  return (
    <div className="sec metrics">
      <div className="metric">
        <div className="metric-k">Total Elapsed</div>
        <div className="metric-v">{fmtElapsed(metrics.elapsed)}</div>
        <div className="metric-sub">{runStatus === 'converged' ? <span className="delta-up">✓ converged after 3 rounds</span> : 'wall-clock since run.start'}</div>
      </div>
      <div className="metric">
        <div className="metric-k">Messages Exchanged</div>
        <div className="metric-v">{metrics.messages.toLocaleString()}</div>
        <div className="metric-sub">{metrics.bytesExchanged > 1024 ? (metrics.bytesExchanged/1024).toFixed(1) + ' KB' : metrics.bytesExchanged + ' B'} on the wire</div>
      </div>
      <div className="metric">
        <div className="metric-k">Error Rate</div>
        <div className="metric-v" style={{color: errPct > 5 ? 'var(--err)' : (errPct > 1 ? 'var(--warn)' : 'var(--ok)')}}>
          {errPct.toFixed(1)}<span className="u">%</span>
        </div>
        <div className="metric-sub">{metrics.errors} errors · {metrics.warns} warnings</div>
      </div>
      <div className="metric">
        <div className="metric-k">Active Agents</div>
        <div className="metric-v">
          {metrics.activeAgents}<span className="u">/{metrics.totalAgents}</span>
        </div>
        <div className="metric-sub">{metrics.completed} completed · {metrics.idle} idle</div>
      </div>
      <div className="spark-wrap">
        <div className="spark-hd">
          <span className="k">Throughput · 60s</span>
          <span style={{flex:1}}/>
          <span className="v">{trips}<span className="u">ev/s</span></span>
        </div>
        <Sparkline data={throughput} color="#7c5cff"/>
        <div style={{display:'flex',justifyContent:'space-between',fontFamily:'var(--mono)',fontSize:10,color:'var(--text-3)'}}>
          <span>−60s</span><span>peak {Math.max(0, ...throughput)} ev/s</span><span>now</span>
        </div>
      </div>
      <div className="gauges">
        <div className="gauges-hd">LLM Latency · ms</div>
        <Gauge k="p50" value={latency.p50} max={2000} unit="ms"/>
        <Gauge k="p95" value={latency.p95} max={2000} unit="ms" warn={latency.p95 > 1500}/>
        <Gauge k="p99" value={latency.p99} max={2000} unit="ms" warn={latency.p99 > 1800}/>
      </div>
    </div>
  );
}

window.MetricsStrip = MetricsStrip;

</script>
<script>
/* ─── WS bridge: live mode replaces simulator ─── */
window.__USE_LIVE = new URLSearchParams(location.search).get('demo') !== '1';
window.__connectLive = function(onEvent, onMeta){
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(proto + '//' + location.host + '/observe');
  ws.onmessage = (m) => {
    try {
      const obj = JSON.parse(m.data);
      if (obj._meta) { onMeta && onMeta(obj); return; }
      onEvent(obj);
    } catch(e){ console.error(e); }
  };
  ws.onopen = () => onMeta && onMeta({_meta:'open'});
  ws.onclose = () => onMeta && onMeta({_meta:'close'});
  return {
    close(){ ws.close(); },
    send(o){ ws.send(JSON.stringify(o)); },
  };
};
</script>

<script type="text/babel">
/* ─── app.jsx ─────────────────────────────────────── */
// app.jsx — Root: state machine that consumes the simulator and renders the dashboard.

const { useState, useEffect, useRef, useMemo, useCallback } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "density": "regular",
  "speed": 2,
  "edgePulse": true,
  "showGraphLabels": true,
  "autoExpandErrors": false
}/*EDITMODE-END*/;

const MAX_EVENTS = 600;
const SPARK_INTERVAL_MS = 1000; // 1 bin/sec, 60 bins
const AGENT_SPARK_BINS = 16;
const AGENT_SPARK_INTERVAL_MS = 700;

function summarizeEvent(evt){
  // short last-action summary
  const t = evt.type;
  const p = evt.payload || {};
  switch(t){
    case 'claim.emitted':       return `→ claim · ${p.confidence || ''} · ${(p.content||'').slice(0,72)}…`;
    case 'challenge.emitted':   return `↯ ${p.stance || 'challenge'} → ${p.target || ''}`;
    case 'lateral_idea.emitted': return `✦ idea · ${(p.content||'').slice(0,72)}…`;
    case 'synthesis.attempt':   return `↪ synthesis r${p.round} · ${p.confidence}`;
    case 'alignment.scored':    return `⚖ score=${(p.score||0).toFixed(3)} · ${p.decision}`;
    case 'vector_store.query':  return `kb.query · k=${p.k} · "${(p.query||'').slice(0,40)}…"`;
    case 'vector_store.result': return `kb.result · ${p.docs_returned} docs · top=${p.top_score}`;
    case 'llm.call.start':      return `llm.call → ${p.model}`;
    case 'llm.call.complete':   return `llm.complete · ${p.completion_tokens}t · ${p.latency_ms}ms`;
    case 'llm.call.timeout':    return `llm.timeout · attempt ${p.attempt}`;
    case 'rate_limit.deferred': return `rate_limit · retry ${p.retry_after_ms}ms`;
    case 'round.start':         return `round ${p.round} · start`;
    case 'round.complete':      return `round ${p.round} · score=${(p.alignment_score||0).toFixed(3)}`;
    case 'run.start':           return `run.start · ${p.run_id}`;
    case 'run.complete':        return `run.complete · ${p.status} (${p.rounds}r)`;
    case 'node.enter':          return `enter · round ${p.round}`;
    case 'node.exit':           return `exit · ${p.duration_ms}ms`;
    default:                    return t;
  }
}

function App(){
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // ── core state ────────────────────────────────────────────────────────────
  const [events, setEvents] = useState([]);
  const [liveEdges, setLiveEdges] = useState([]); // recent edge fires for graph
  const [agentStates, setAgentStates] = useState(() => {
    const s = { __round: 1 };
    ['researcher','skeptic','visionary','synthesizer','arbiter','vector_store','orchestrator'].forEach(id => {
      s[id] = { state: 'idle', tasks: 0, errors: 0, uptime: 0, lastSeen: 0,
                lastAction: '', spark: new Array(AGENT_SPARK_BINS).fill(0) };
    });
    return s;
  });
  const [metrics, setMetrics] = useState({
    elapsed: 0, messages: 0, bytesExchanged: 0,
    errors: 0, warns: 0,
    activeAgents: 0, totalAgents: 5, completed: 0, idle: 5,
    totalEvents: 0,
  });
  const [throughput, setThroughput] = useState(new Array(60).fill(0));
  const [latency, setLatency] = useState({ p50: 950, p95: 1320, p99: 1480 });
  const [runStatus, setRunStatus] = useState('starting');
  const [runStartedAt, setRunStartedAt] = useState(null);
  const [paused, setPaused] = useState(false);

  // filters
  const [filterAgents, setFilterAgents] = useState(new Set());
  const [filterSev, setFilterSev] = useState(new Set());
  const [filterType, setFilterType] = useState('');
  const [search, setSearch] = useState('');

  // ── refs for hot counters (avoid stale closures) ─────────────────────────
  const counters = useRef({ throughputBin: 0, latencies: [] });
  const playerRef = useRef(null);

  // ── simulator wiring ──────────────────────────────────────────────────────
  const handleEvent = useCallback((rawEv) => {
    const now = new Date();
    const evt = {
      ...rawEv,
      timestamp: now,
      timestampMs: now.getTime(),
      _isNew: true,
      _seq: rawEv._seq,
    };

    // events log (reverse chronological — newest first)
    setEvents(prev => {
      const next = [evt, ...prev];
      if (next.length > MAX_EVENTS) next.length = MAX_EVENTS;
      // unmark "new" on prior entries after a tick
      return next.map((e, i) => i === 0 ? e : (e._isNew ? { ...e, _isNew: false } : e));
    });

    // throughput counter
    counters.current.throughputBin += 1;
    if (rawEv.type === 'llm.call.complete' && rawEv.payload.latency_ms){
      counters.current.latencies.push(rawEv.payload.latency_ms);
      if (counters.current.latencies.length > 100) counters.current.latencies.shift();
    }

    // agent state mutation
    setAgentStates(prev => {
      const next = { ...prev };
      const id = rawEv.agent;
      const cur = next[id] ? { ...next[id] } : { state: 'idle', tasks: 0, errors: 0, uptime: 0, lastSeen: 0, spark: new Array(AGENT_SPARK_BINS).fill(0) };
      cur.lastSeen = Date.now();
      cur.lastAction = summarizeEvent(rawEv);

      if (rawEv.activate) {
        const a = next[rawEv.activate] ? { ...next[rawEv.activate] } : { state:'idle', tasks:0, errors:0, uptime:0, lastSeen:Date.now(), spark:new Array(AGENT_SPARK_BINS).fill(0) };
        a.state = 'running';
        a.lastSeen = Date.now();
        a.startedAt = Date.now();
        next[rawEv.activate] = a;
      }
      if (rawEv.deactivate) {
        const a = next[rawEv.deactivate] ? { ...next[rawEv.deactivate] } : { state:'idle', tasks:0, errors:0, uptime:0, lastSeen:Date.now(), spark:new Array(AGENT_SPARK_BINS).fill(0) };
        a.state = 'completed';
        a.tasks = (a.tasks || 0) + 1;
        a.lastSeen = Date.now();
        next[rawEv.deactivate] = a;
      }
      if (rawEv.sev === 'ERROR') cur.errors = (cur.errors || 0) + 1;

      // round tracking
      if (rawEv.type === 'round.start') next.__round = rawEv.payload.round;

      // bump activity sparkline for this agent
      const bin = cur.spark[cur.spark.length-1] + 1;
      cur.spark = [...cur.spark.slice(0, -1), bin];

      next[id] = cur;
      return next;
    });

    // edge fire
    if (rawEv.edge){
      const fired = { ...rawEv.edge, _firedAt: Date.now(), _seq: rawEv._seq };
      setLiveEdges(prev => {
        const next = [...prev, fired];
        if (next.length > 24) next.shift();
        return next;
      });
    }

    // metrics
    setMetrics(prev => {
      const isErr = rawEv.sev === 'ERROR' || (rawEv.edge && rawEv.edge.status === 'error');
      const isWarn = rawEv.sev === 'WARN' || (rawEv.edge && rawEv.edge.status === 'warn');
      return {
        ...prev,
        totalEvents: prev.totalEvents + 1,
        messages: rawEv.edge ? prev.messages + 1 : prev.messages,
        bytesExchanged: prev.bytesExchanged + (rawEv.edge?.size || 0),
        errors: isErr ? prev.errors + 1 : prev.errors,
        warns: isWarn ? prev.warns + 1 : prev.warns,
      };
    });

    if (rawEv.type === 'run.start') {
      setRunStatus('running');
      setRunStartedAt(Date.now());
    }
    if (rawEv.type === 'run.complete') setRunStatus('converged');
  }, []);

  // start simulator OR connect to live websocket
  useEffect(() => {
    if (window.__USE_LIVE && window.__connectLive) {
      const conn = window.__connectLive(
        (ev) => handleEvent(ev),
        (meta) => {
          if (meta._meta === 'open') {
            // ask the server to begin a deliberation on the default topic
            conn.send({ action: 'start', topic: window.ThinkTankSim.TOPIC });
          }
        },
      );
      // expose a no-op player so other effects don't crash
      playerRef.current = { setSpeed(){}, pause(){}, resume(){}, stop(){conn.close();}, start(){} };
      return () => conn.close();
    }
    const player = window.ThinkTankSim.createPlayer({
      onEvent: handleEvent,
      speed: t.speed || 2,
    });
    playerRef.current = player;
    player.start();
    return () => player.stop();
  // eslint-disable-next-line
  }, []);

  // speed changes
  useEffect(() => {
    if (playerRef.current) playerRef.current.setSpeed(t.speed);
  }, [t.speed]);

  // pause/resume
  useEffect(() => {
    if (!playerRef.current) return;
    if (paused) playerRef.current.pause();
    else playerRef.current.resume();
  }, [paused]);

  // ── ticking: elapsed / sparklines / agent uptime / idle decay ─────────────
  useEffect(() => {
    const id = setInterval(() => {
      // elapsed
      setMetrics(prev => ({
        ...prev,
        elapsed: runStartedAt ? (Date.now() - runStartedAt) : prev.elapsed,
      }));

      // sparkline tick
      setThroughput(prev => {
        const next = [...prev.slice(1), counters.current.throughputBin];
        counters.current.throughputBin = 0;
        return next;
      });

      // latency p50/p95/p99
      const ls = counters.current.latencies.slice().sort((a,b)=>a-b);
      if (ls.length >= 3) {
        const pct = (p) => ls[Math.floor((ls.length-1) * p)];
        setLatency({ p50: pct(0.5), p95: pct(0.95), p99: pct(0.99) });
      }

      // uptime, idle decay, active count
      setAgentStates(prev => {
        const next = { ...prev };
        let active = 0, completed = 0, idle = 0;
        ['researcher','skeptic','visionary','synthesizer','arbiter'].forEach(aid => {
          const a = { ...(next[aid] || {}) };
          if (a.startedAt) a.uptime = Date.now() - a.startedAt;
          // idle decay: if running and no event in 5s, mark as completed
          if (a.state === 'running' && Date.now() - a.lastSeen > 5000){
            a.state = 'completed';
          }
          if (a.state === 'running') active++;
          else if (a.state === 'completed') completed++;
          else idle++;
          next[aid] = a;
        });
        // also tick vector_store
        if (next.vector_store?.startedAt) {
          next.vector_store = { ...next.vector_store, uptime: Date.now() - next.vector_store.startedAt };
        }
        setMetrics(m => ({ ...m, activeAgents: active, completed, idle }));
        return next;
      });
    }, SPARK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [runStartedAt]);

  // sparkline decay for agents (smaller bins)
  useEffect(() => {
    const id = setInterval(() => {
      setAgentStates(prev => {
        const next = { ...prev };
        Object.keys(next).forEach(k => {
          if (k === '__round') return;
          const a = next[k];
          if (a && a.spark) {
            next[k] = { ...a, spark: [...a.spark.slice(1), 0] };
          }
        });
        return next;
      });
    }, AGENT_SPARK_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  // edge decay (cull old fires from highlighting)
  useEffect(() => {
    const id = setInterval(() => {
      setLiveEdges(prev => prev.filter(e => Date.now() - e._firedAt < 1500));
    }, 400);
    return () => clearInterval(id);
  }, []);

  // ── handlers ─────────────────────────────────────────────────────────────
  const onClear = () => setEvents([]);
  const onTogglePause = () => setPaused(p => !p);

  // ── theme + density root classes ─────────────────────────────────────────
  const rootCls = `app theme-${t.theme} density-${t.density}`;

  // run topic
  const TOPIC = window.ThinkTankSim.TOPIC;
  const RUN_ID = window.ThinkTankSim.RUN_ID;

  return (
    <div className={rootCls}>
      {/* Header ---------------------------------------------------------- */}
      <header className="hdr">
        <div className="hdr-brand">
          <div className="hdr-mark"/>
          <div>
            <div className="hdr-title">Think Tank <span style={{color:'var(--text-3)',fontWeight:400}}>· Observability</span></div>
          </div>
          <span className="hdr-sub">v0.4.2 · langgraph 0.2.31 · local</span>
        </div>
        <div className="hdr-runbar">
          <span className="hdr-pulse">
            <span className="hdr-pulse-dot"/>{runStatus === 'converged' ? 'COMPLETE' : 'LIVE'}
          </span>
          <span className="hdr-runlabel">topic</span>
          <span className="hdr-runtopic">{TOPIC}</span>
          <span className="hdr-runid">run · <b>{RUN_ID}</b></span>
        </div>
        <div className="hdr-actions">
          <button className="hdr-btn" onClick={onTogglePause}>
            <svg width="12" height="12"><use href={paused ? '#ic-play' : '#ic-pause'}/></svg>
            {paused ? 'Resume' : 'Pause'}
            <span className="kbd">␣</span>
          </button>
          <button className="hdr-btn danger">
            <svg width="12" height="12"><use href="#ic-stop"/></svg>
            Abort
          </button>
        </div>
      </header>

      {/* Body ------------------------------------------------------------ */}
      <div className="body">
        <AgentGraph
          agentStates={agentStates}
          liveEdges={liveEdges}
          elapsedMs={metrics.elapsed}
          runStatus={runStatus}
        />
        <div className="row-mid">
          <EventStream
            events={events}
            paused={paused}
            onTogglePause={onTogglePause}
            onClear={onClear}
            filterAgents={filterAgents}
            setFilterAgents={setFilterAgents}
            filterSev={filterSev}
            setFilterSev={setFilterSev}
            filterType={filterType}
            setFilterType={setFilterType}
            search={search}
            setSearch={setSearch}
          />
          <AgentSidebar agentStates={agentStates}/>
        </div>
        <MetricsStrip
          metrics={metrics}
          throughput={throughput}
          latency={latency}
          runStatus={runStatus}
        />
      </div>

      <div className="foot">
        <span>● connected · <b>ws://localhost:7860/observe</b></span>
        <span className="sep"/>
        <span>graph · <b>think_tank.graph.build_think_tank_graph</b></span>
        <span className="sep"/>
        <span>checkpointer · <b>InMemorySaver</b></span>
        <span className="sep"/>
        <span>events buffered · <b>{events.length}</b>/{MAX_EVENTS}</span>
        <span style={{flex:1}}/>
        <span>↑ scroll-lock <b>off</b></span>
        <span className="sep"/>
        <span>render @ <b>{Math.round(1000 / Math.max(1, SPARK_INTERVAL_MS/16))}fps</b></span>
      </div>

      {/* Tweaks ---------------------------------------------------------- */}
      <TweaksPanel>
        <TweakSection label="Display"/>
        <TweakRadio label="Theme" value={t.theme}
          options={['dark','light']}
          onChange={(v)=>setTweak('theme', v)}/>
        <TweakRadio label="Density" value={t.density}
          options={['compact','regular','comfy']}
          onChange={(v)=>setTweak('density', v)}/>

        <TweakSection label="Stream"/>
        <TweakSlider label="Replay speed" value={t.speed} min={0.5} max={6} step={0.25} unit="×"
          onChange={(v)=>setTweak('speed', v)}/>
        <TweakToggle label="Auto-expand errors" value={t.autoExpandErrors}
          onChange={(v)=>setTweak('autoExpandErrors', v)}/>

        <TweakSection label="Graph"/>
        <TweakToggle label="Animate edge pulse" value={t.edgePulse}
          onChange={(v)=>setTweak('edgePulse', v)}/>
        <TweakToggle label="Show resting labels" value={t.showGraphLabels}
          onChange={(v)=>setTweak('showGraphLabels', v)}/>

        <TweakSection label="Run"/>
        <TweakButton label="Restart simulation"
          onClick={() => {
            setEvents([]);
            setLiveEdges([]);
            setMetrics({ elapsed:0, messages:0, bytesExchanged:0, errors:0, warns:0,
                         activeAgents:0, totalAgents:5, completed:0, idle:5, totalEvents:0 });
            setThroughput(new Array(60).fill(0));
            setRunStartedAt(Date.now());
            setRunStatus('running');
            counters.current = { throughputBin: 0, latencies: [] };
            if (playerRef.current) {
              playerRef.current.stop();
              playerRef.current = window.ThinkTankSim.createPlayer({
                onEvent: handleEvent, speed: t.speed,
              });
              playerRef.current.start();
            }
          }}/>
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);

</script></body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Vector-store seed (unchanged from the original Gradio app)
# ─────────────────────────────────────────────────────────────────────────────
_SEED_DOCUMENTS = [
    "Remote work has been shown to increase productivity for knowledge workers "
    "by 13% according to a Stanford study conducted over 9 months with 16,000 "
    "employees.",
    "A 2023 McKinsey report found that 87% of workers offered flexible work "
    "arrangements choose to work remotely at least part of the time.",
    "Communication overhead increases by approximately 30% in fully remote "
    "teams due to reliance on asynchronous channels (Microsoft, n=60,000).",
    "Hybrid work models (2-3 days in-office) appear to balance productivity "
    "gains with team cohesion (HBR meta-analysis of 45 studies).",
    "Remote work exacerbates the 'always-on' culture: 62% of remote workers "
    "report difficulty disconnecting after work hours (Buffer 2023).",
    "Innovation metrics decline in fully remote settings according to a Nature "
    "Human Behaviour study analysing 20 million research papers.",
    "Cost savings from remote work are substantial: ~$11k per remote employee "
    "per year (Global Workplace Analytics 2023).",
    "Onboarding new employees remotely takes 32% longer (Gartner 2022, n=500).",
]


def _get_vector_store():
    from langchain_chroma import Chroma
    from langchain_openai import OpenAIEmbeddings
    from pydantic import SecretStr

    api_key = os.getenv("OPENROUTER_API_KEY")
    return Chroma(
        collection_name="think_tank_kb",
        embedding_function=OpenAIEmbeddings(
            base_url="https://openrouter.ai/api/v1",
            api_key=SecretStr(api_key) if api_key else None,
            model=os.getenv("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
            check_embedding_ctx_length=False,
        ),
        persist_directory=os.getenv("CHROMA_DB_PATH", "./chroma_db"),
    )


def _seed_if_empty(vs) -> None:
    from langchain_core.documents import Document

    if vs.similarity_search("remote work productivity", k=1):
        return
    vs.add_documents(
        [
            Document(page_content=t, metadata={"source": "seed", "index": i})
            for i, t in enumerate(_SEED_DOCUMENTS)
        ]
    )


# ─────────────────────────────────────────────────────────────────────────────
# Event mapping: LangGraph stream → flat dashboard event schema.
#
# The dashboard expects events shaped like:
#   { sev, agent, type, payload,
#     edge?:    { from, to, kind, size, rtt, status },
#     activate?: <agent_id>, deactivate?: <agent_id> }
#
# We walk state deltas yielded by graph.astream(stream_mode="updates") and
# translate the appearance of new claims/challenges/ideas/syntheses into
# concrete events. We synthesize node.enter/node.exit + edge fires from the
# node-name key returned by LangGraph at each step.
# ─────────────────────────────────────────────────────────────────────────────
NODE_TO_AGENT = {
    "researcher": "researcher",
    "skeptic": "skeptic",
    "visionary": "visionary",
    "synthesizer": "synthesizer",
    "arbiter": "arbiter",
    # Common alternates
    "research": "researcher",
    "synthesize": "synthesizer",
    "judge": "arbiter",
}

DOWNSTREAM_EDGE = {
    "researcher": ("researcher", "synthesizer", "claim"),
    "skeptic": ("skeptic", "synthesizer", "challenge"),
    "visionary": ("visionary", "synthesizer", "lateral_idea"),
    "synthesizer": ("synthesizer", "arbiter", "synthesis"),
    "arbiter": ("arbiter", "orchestrator", "control"),
}


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _ev(sev: str, agent: str, type_: str, payload: dict[str, Any], **extra) -> dict:
    return {
        "sev": sev,
        "agent": agent,
        "type": type_,
        "payload": payload,
        "ts": _utc_iso(),
        **extra,
    }


def _payload_size(obj: Any) -> int:
    try:
        return len(json.dumps(obj, default=str))
    except Exception:
        return 0


class _StreamAdapter:
    """Walks the LangGraph state stream and emits structured dashboard events."""

    def __init__(self, run_id: str) -> None:
        self.seen_claims: set[str] = set()
        self.run_id = run_id
        self.seen_challenges: set[str] = set()
        self.seen_ideas: set[str] = set()
        self.seen_syntheses: set[str] = set()
        self.last_round = 0
        self.node_started: dict[str, float] = {}

    @staticmethod
    def _id_of(item: Any, fallback: str) -> str:
        return getattr(item, "id", None) or getattr(item, "uid", None) or fallback

    def open_node(self, node: str) -> list[dict]:
        agent = NODE_TO_AGENT.get(node, node)
        self.node_started[agent] = time.perf_counter()
        return [
            _ev(
                "INFO",
                agent,
                "node.enter",
                {"node": agent, "round": self.last_round},
                activate=agent,
            )
        ]

    def close_node(self, node: str) -> list[dict]:
        agent = NODE_TO_AGENT.get(node, node)
        started = self.node_started.pop(agent, time.perf_counter())
        duration_ms = int((time.perf_counter() - started) * 1000)
        return [
            _ev(
                "INFO",
                agent,
                "node.exit",
                {"node": agent, "round": self.last_round, "duration_ms": duration_ms},
                deactivate=agent,
            )
        ]

    def diff_state(self, node: str, state_after: dict) -> list[dict]:
        out: list[dict] = []
        agent = NODE_TO_AGENT.get(node, node)
        rnd = state_after.get("current_round", self.last_round) or self.last_round

        if rnd != self.last_round and rnd > 0:
            out.append(_ev("INFO", "orchestrator", "round.start", {"round": rnd}))
            self.last_round = rnd

        # Claims
        for c in state_after.get("claims", []) or []:
            cid = self._id_of(c, f"claim_{len(self.seen_claims)}")
            if cid in self.seen_claims:
                continue
            self.seen_claims.add(cid)
            payload = {
                "id": cid,
                "round": getattr(c, "round", rnd),
                "agent_id": getattr(c, "agent_id", agent),
                "confidence": getattr(
                    getattr(c, "confidence", None), "value", str(getattr(c, "confidence", ""))
                ),
                "content": getattr(c, "content", ""),
                "evidence_summary": getattr(c, "evidence_summary", "") or "",
            }
            edge = {
                "from": "researcher",
                "to": "synthesizer",
                "kind": "claim",
                "size": _payload_size(payload),
                "rtt": 5,
                "status": "success",
            }
            out.append(_ev("INFO", "researcher", "claim.emitted", payload, edge=edge))

        # Challenges
        for ch in state_after.get("challenges", []) or []:
            chid = self._id_of(ch, f"chal_{len(self.seen_challenges)}")
            if chid in self.seen_challenges:
                continue
            self.seen_challenges.add(chid)
            stance = getattr(getattr(ch, "stance", None), "value", str(getattr(ch, "stance", "")))
            payload = {
                "id": chid,
                "round": getattr(ch, "round", rnd),
                "agent_id": getattr(ch, "agent_id", "skeptic"),
                "stance": stance.upper(),
                "target": getattr(ch, "target_claim_id", None) or getattr(ch, "target", ""),
                "content": getattr(ch, "content", ""),
                "reasoning": getattr(ch, "reasoning", "") or "",
            }
            status = {"oppose": "error", "refine": "warn"}.get(stance.lower(), "success")
            edge = {
                "from": "skeptic",
                "to": "synthesizer",
                "kind": "challenge",
                "size": _payload_size(payload),
                "rtt": 6,
                "status": status,
            }
            out.append(_ev("INFO", "skeptic", "challenge.emitted", payload, edge=edge))

        # Lateral ideas
        for idea in state_after.get("expansions", []) or []:
            iid = self._id_of(idea, f"idea_{len(self.seen_ideas)}")
            if iid in self.seen_ideas:
                continue
            self.seen_ideas.add(iid)
            payload = {
                "id": iid,
                "round": getattr(idea, "round", rnd),
                "agent_id": getattr(idea, "agent_id", "visionary"),
                "content": getattr(idea, "content", ""),
                "novelty_rationale": getattr(idea, "novelty_rationale", "") or "",
            }
            edge = {
                "from": "visionary",
                "to": "synthesizer",
                "kind": "lateral_idea",
                "size": _payload_size(payload),
                "rtt": 7,
                "status": "success",
            }
            out.append(_ev("INFO", "visionary", "lateral_idea.emitted", payload, edge=edge))

        # Synthesis attempts
        for s in state_after.get("syntheses", []) or []:
            sid = self._id_of(s, f"synth_r{getattr(s, 'round', rnd)}")
            if sid in self.seen_syntheses:
                continue
            self.seen_syntheses.add(sid)
            payload = {
                "id": sid,
                "round": getattr(s, "round", rnd),
                "confidence": getattr(
                    getattr(s, "confidence", None), "value", str(getattr(s, "confidence", ""))
                ),
                "content": getattr(s, "content", ""),
                "contributing_claim_ids": list(getattr(s, "contributing_claim_ids", []) or []),
            }
            edge = {
                "from": "synthesizer",
                "to": "arbiter",
                "kind": "synthesis",
                "size": _payload_size(payload),
                "rtt": 6,
                "status": "success",
            }
            out.append(_ev("INFO", "synthesizer", "synthesis.attempt", payload, edge=edge))

        # Alignment / convergence
        align = state_after.get("alignment_score")
        if align is not None and node == "arbiter":
            out.append(
                _ev(
                    "INFO",
                    "arbiter",
                    "alignment.scored",
                    {
                        "round": rnd,
                        "score": float(align),
                        "threshold": (state_after.get("config") or {}).get(
                            "alignment_threshold", 0.65
                        ),
                        "decision": "CONVERGE" if state_after.get("synthesis") else "CONTINUE",
                    },
                )
            )

        # Final synthesis → run.complete
        final = state_after.get("synthesis")
        if final is not None:
            payload = {
                "run_id": self.run_id,
                "rounds": rnd,
                "alignment_score": getattr(final, "alignment_score", align or 0.0),
                "status": "CONVERGED",
            }
            out.append(
                _ev(
                    "INFO",
                    "arbiter",
                    "run.complete",
                    payload,
                    edge={
                        "from": "arbiter",
                        "to": "orchestrator",
                        "kind": "control",
                        "size": _payload_size(payload),
                        "rtt": 3,
                        "status": "success",
                    },
                )
            )
        return out


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Think Tank · Observability")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.websocket("/observe")
async def observe(ws: WebSocket) -> None:
    """One websocket per client. Client sends {action:'start', topic}; server
    streams events as the LangGraph deliberation progresses."""
    await ws.accept()
    run_id = f"run_{uuid.uuid4().hex[:10]}"

    try:
        msg = await ws.receive_json()
    except WebSocketDisconnect:
        return
    if msg.get("action") != "start":
        await ws.send_json(
            {
                "sev": "ERROR",
                "agent": "system",
                "type": "protocol.error",
                "payload": {"reason": "expected {action:'start', topic}"},
            }
        )
        await ws.close()
        return

    topic = (msg.get("topic") or "").strip() or "Untitled deliberation"

    if not os.getenv("OPENROUTER_API_KEY"):
        await ws.send_json(
            _ev(
                "ERROR",
                "system",
                "config.missing",
                {
                    "reason": "OPENROUTER_API_KEY not set",
                    "hint": "Add it to .env and restart, or open /?demo=1 for a built-in trace.",
                },
            )
        )
        await ws.close()
        return

    # Lazy-import the graph so the module loads even without langgraph installed.
    try:
        from think_tank.graph import build_think_tank_graph
    except Exception as e:
        await ws.send_json(_ev("ERROR", "system", "import.error", {"reason": str(e)}))
        await ws.close()
        return

    # Seed vector store
    try:
        _seed_if_empty(_get_vector_store())
    except Exception as e:
        await ws.send_json(_ev("WARN", "system", "vector_store.seed_failed", {"reason": str(e)}))

    graph = build_think_tank_graph()
    initial_state: dict = {
        "topic": topic,
        "config": {"alignment_threshold": 0.65, "min_rounds": 2, "max_rounds": 6},
        "claims": [],
        "challenges": [],
        "expansions": [],
        "syntheses": [],
        "current_round": 0,
        "alignment_score": 0.0,
        "expansion": None,
        "synthesis": None,
    }

    # Boot events
    await ws.send_json(
        _ev(
            "INFO",
            "system",
            "graph.compile",
            {"nodes": list(NODE_TO_AGENT.keys()), "checkpoint": "in_memory"},
        )
    )
    await ws.send_json(
        _ev(
            "INFO",
            "orchestrator",
            "run.start",
            {"run_id": run_id, "topic": topic, "config": initial_state["config"]},
            edge={
                "from": "orchestrator",
                "to": "researcher",
                "kind": "dispatch",
                "size": _payload_size(initial_state),
                "rtt": 4,
                "status": "success",
            },
        )
    )

    adapter = _StreamAdapter(run_id)
    last_state = initial_state

    stream_error: str | None = None
    try:
        async for chunk in graph.astream(initial_state, stream_mode="updates"):
            # chunk is { node_name: state_delta }
            for node_name, delta in chunk.items():
                # node.enter
                for ev in adapter.open_node(node_name):
                    await ws.send_json(ev)

                # merge delta into our running state to compute diffs
                merged: dict = {**last_state, **(delta or {})}
                for ev in adapter.diff_state(node_name, merged):
                    await ws.send_json(ev)

                # node.exit
                for ev in adapter.close_node(node_name):
                    await ws.send_json(ev)
                last_state = merged
    except WebSocketDisconnect:
        return
    except Exception as e:
        await ws.send_json(
            _ev("ERROR", "system", "graph.exception", {"reason": str(e), "type": type(e).__name__})
        )
        stream_error = str(e)

    await ws.send_json(
        _ev(
            "INFO",
            "system",
            "stream.end",
            {
                "run_id": run_id,
                "status": "ok" if stream_error is None else "error",
                **({"reason": stream_error} if stream_error is not None else {}),
            },
        )
    )
    try:
        await ws.close()
    except Exception:  # nosec B110  # already disconnected, swallow close errors
        pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))  # nosec B104
