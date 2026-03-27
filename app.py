"""
╔══════════════════════════════════════════════════════════════════════════╗
║  CASHFLOW COMMAND CENTER v14.0 — Institutional Edition                  ║
║  Glanceable execution desk + Diamond / Gold Zone / Quant                   ║
║  Hurst · Kelly · Black Scholes engines unchanged in this release          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import html as _html_mod
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import math, warnings, json, time, os, threading
from pathlib import Path
try:
    import urllib.request
    import urllib.parse
except ImportError:
    pass
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────
# CONFIG PERSISTENCE — alerts + watchlist (no personal portfolio in shared deploys)
# ─────────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULT_CONFIG = {"whatsapp_phone": "", "whatsapp_apikey": "", "alert_threshold": 80,
                  "last_alert_date": "", "watchlist": "PLTR,BMNR,AAPL,AMZN,NVDA,AMD,TSLA,SPY,QQQ",
                  "scanner_sort_mode": "Custom watchlist order"}
# Anonymous reference only — used for Kelly / ATR example math (not user portfolio data).
REF_NOTIONAL = 100_000.0
RISK_PCT_EXAMPLE = 3.0

def load_config():
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            merged = {**DEFAULT_CONFIG, **saved}
            for k in ("acct", "pltr_sh", "pltr_cost", "max_risk"):
                merged.pop(k, None)
            return merged
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    """Atomic write — writes to .tmp first, then renames. Zero corruption risk."""
    try:
        temp_path = CONFIG_PATH.with_suffix('.tmp')
        with open(temp_path, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(temp_path, CONFIG_PATH)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────
# RETRY WRAPPER — handles yfinance throttling gracefully
# ─────────────────────────────────────────────────────────────────────────
def retry_fetch(fn, retries=3, delay=2):
    """Call fn() up to `retries` times with exponential backoff."""
    for attempt in range(retries):
        try:
            result = fn()
            if result is not None:
                return result
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    return None

# ─────────────────────────────────────────────────────────────────────────
# ALERT HOOK — CallMeBot WhatsApp (non-blocking background thread)
# ─────────────────────────────────────────────────────────────────────────
def send_whatsapp_alert(phone, apikey, message):
    """Non-blocking WhatsApp alert via CallMeBot — fires on background thread."""
    if not phone or not apikey:
        return False
    def _fire():
        try:
            encoded = urllib.parse.quote(message)
            url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={apikey}"
            urllib.request.urlopen(url, timeout=10)
        except Exception:
            pass
    threading.Thread(target=_fire, daemon=True).start()
    return True

st.set_page_config(page_title="CashFlow Command Center v14", page_icon="💰",
                   layout="wide", initial_sidebar_state="expanded")

# Plotly toolbar: vertical mode bar avoids clashing with the legend
_PLOTLY_UI_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "modeBarOrientation": "v",
    "scrollZoom": False,
}

# ─────────────────────────────────────────────────────────────────────────
# CSS (stored as variable, merged with navbar in a single st.markdown call
# to prevent Streamlit from generating a visible "keyb" widget label)
# ─────────────────────────────────────────────────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
:root{--bg0:#080c14;--bg1:#0f1520;--bg2:#151d2e;--bg3:#1a2540;--bdr:#1e293b;
--t1:#e2e8f0;--t2:#94a3b8;--t3:#64748b;--green:#10b981;--red:#ef4444;
--blue:#3b82f6;--purple:#8b5cf6;--amber:#f59e0b;--cyan:#06b6d4;--cyan-bright:#00e5ff;
--success:#00FFA3;--danger:#FF005C;--gold:#FFD700;
--glass-bg:rgba(15,23,42,.65);--glass-bdr:rgba(255,255,255,.1);--nav-h:52px}
.stApp{background:var(--bg0)!important;font-family:'Inter',sans-serif!important}
.main .block-container{max-width:1400px!important;padding-top:calc(var(--nav-h) + 14px)!important;padding-left:.7rem!important;padding-right:.7rem!important}
/* Shell row: fixed nav leaves no flow; collapse markdown + hide bootstrap iframe chrome */
[data-testid="stMarkdownContainer"]:has(nav.sticky-nav){
  min-height:0!important;padding:0!important;margin:0!important;border:none!important;outline:none!important;
  background:transparent!important;box-shadow:none!important;
}
[data-testid="stMarkdownContainer"]:has(nav.sticky-nav) iframe[aria-hidden="true"],
iframe[aria-hidden="true"][data-cf-toggle-boot="1"]{
  position:fixed!important;left:-9999px!important;top:0!important;width:1px!important;height:1px!important;max-height:1px!important;
  margin:0!important;padding:0!important;border:0!important;overflow:hidden!important;clip-path:inset(50%)!important;
  opacity:0!important;pointer-events:none!important;visibility:hidden!important;
}
iframe{border:0!important}
.main [data-testid="stVerticalBlock"] > div:has(> div[data-testid="stMarkdownContainer"] nav.sticky-nav){
  min-height:0!important;margin-top:0!important;margin-bottom:0!important;
}
section[data-testid="stSidebar"]{background:var(--bg1)!important;border-right:1px solid var(--bdr)!important;z-index:1000006!important}
[data-testid="stSidebarUserContent"]{padding-top:100px!important}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,[data-testid="stSidebar"] h4{color:#00e5ff!important}
[data-testid="stSidebar"] label{color:#ffffff!important;font-weight:600!important}
[data-testid="stSidebar"] .stMarkdown p,[data-testid="stSidebar"] span{color:#e2e8f0!important}
/* Sidebar watchlist: stop cramped 3-col buttons from breaking words mid-label */
[data-testid="stSidebar"] .stButton > button{
  white-space:nowrap!important;text-align:center!important;
  font-size:.82rem!important;padding:.45rem .65rem!important;
}
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="column"]{min-width:0!important}
[data-testid="stSidebar"] textarea{font-family:'JetBrains Mono',monospace!important;font-size:.78rem!important;line-height:1.35!important}
.stMarkdown,.stText,p,span,label{color:var(--t1)!important;font-family:'Inter',sans-serif!important}
h1,h2,h3,h4,h5,h6{font-family:'Inter',sans-serif!important;font-weight:700!important;color:var(--cyan-bright)!important}
div[data-testid="stMetric"]{background:var(--glass-bg)!important;border:1px solid var(--glass-bdr)!important;border-radius:12px!important;padding:10px 12px!important;backdrop-filter:blur(12px)!important;-webkit-backdrop-filter:blur(12px)!important;box-shadow:inset 0 1px 1px rgba(255,255,255,.05),0 10px 26px rgba(2,6,23,.36)!important}
div[data-testid="stMetric"] label{color:var(--t3)!important;font-size:.75rem!important;text-transform:uppercase!important;letter-spacing:.05em!important}
div[data-testid="stMetric"] [data-testid="stMetricValue"]{font-family:'JetBrains Mono',monospace!important;font-weight:600!important}
.stTabs [data-baseweb="tab-list"]{gap:0!important;background:var(--bg1)!important;border-radius:10px!important;padding:4px!important}
.stTabs [data-baseweb="tab"]{border-radius:8px!important;color:var(--t2)!important;font-weight:500!important;padding:8px 16px!important}
.stTabs [aria-selected="true"]{background:var(--bg2)!important;color:var(--cyan)!important}
.stButton>button{background:linear-gradient(135deg,var(--blue),var(--purple))!important;color:#fff!important;border:none!important;border-radius:8px!important;font-weight:600!important;padding:8px 24px!important}
.stSelectbox>div>div,.stNumberInput>div>div>input,.stTextInput>div>div>input{background:var(--bg2)!important;border-color:var(--bdr)!important;color:var(--t1)!important}
.tc{background:var(--glass-bg);border:1px solid var(--glass-bdr);border-radius:12px;padding:12px 14px;margin-bottom:8px;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:inset 0 1px 1px rgba(255,255,255,.05),0 10px 26px rgba(2,6,23,.36)}
.sb{background:linear-gradient(135deg,rgba(16,185,129,.12),rgba(5,150,105,.05));border-left:3px solid var(--green);border-radius:8px;padding:16px;margin:8px 0}
.sr{background:linear-gradient(135deg,rgba(239,68,68,.12),rgba(220,38,38,.05));border-left:3px solid var(--red);border-radius:8px;padding:16px;margin:8px 0}
.sn{background:linear-gradient(135deg,rgba(245,158,11,.12),rgba(217,119,6,.05));border-left:3px solid var(--amber);border-radius:8px;padding:16px;margin:8px 0}
.tip{background:var(--bg1);border:1px solid var(--bdr);border-radius:8px;padding:12px 16px;font-size:.85rem;color:var(--t2);margin:4px 0 12px 0}
.mono{font-family:'JetBrains Mono',monospace!important}
.ni{background:var(--bg2);border:1px solid var(--bdr);border-radius:8px;padding:12px 16px;margin:6px 0;transition:background .15s}
.ni:hover{background:var(--bg3)}
.ac{background:linear-gradient(135deg,rgba(6,182,212,.12),rgba(59,130,246,.08));border:1px solid rgba(6,182,212,.3);border-radius:10px;padding:14px 18px;margin:8px 0}
.qe{background:linear-gradient(135deg,rgba(139,92,246,.15),rgba(59,130,246,.1));border:2px solid rgba(139,92,246,.4);border-radius:14px;padding:20px;margin:12px 0;text-align:center}
.bluf{background:linear-gradient(135deg,rgba(16,185,129,.08),rgba(6,182,212,.08));border:2px solid rgba(16,185,129,.3);border-radius:16px;padding:24px 28px;margin:12px 0}
.tl{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:8px}
.explain{border-left:3px solid var(--cyan);border-radius:0 10px 10px 0;padding:18px 22px;margin:16px 0;line-height:1.7}
.section-hdr{margin:56px 0 28px 0;padding:18px 0;border-bottom:2px solid var(--bdr)}
.section-hdr h2{margin:0!important;font-size:1.5rem!important;color:var(--t1)!important;letter-spacing:-.01em;display:inline;vertical-align:middle}
.section-hdr p{margin:4px 0 0 0!important;color:var(--t3)!important;font-size:.9rem!important}
.cf-tip{
  cursor:help;display:inline-flex;align-items:center;justify-content:center;width:1.15rem;height:1.15rem;margin-left:8px;
  border-radius:50%;background:#0f172a;border:1px solid #334155;color:#e2e8f0;font-size:.62rem;font-weight:800;
  vertical-align:middle;line-height:1;position:relative;top:-2px;overflow:visible;
}
.cf-tip:hover{border-color:#00e5ff;background:#1e293b;color:#fff}
.cf-tip .cf-tiptext{
  visibility:hidden;opacity:0;transition:opacity .14s;
  position:absolute;top:calc(100% + 10px);left:8px;transform:none;
  z-index:2147483647;min-width:320px;width:min(560px,72vw);max-width:72vw;padding:12px 14px;
  background:#020617;border:1px solid rgba(148,163,184,.4);border-left:4px solid #00E5FF;
  color:#f1f5f9;font-size:16px;font-weight:600;line-height:1.62;border-radius:10px;
  box-shadow:0 12px 28px rgba(2,6,23,.78);text-transform:none;letter-spacing:0;
  white-space:normal;word-break:break-word;
}
.cf-tip:hover .cf-tiptext,.cf-tip:focus-visible .cf-tiptext{visibility:visible;opacity:1}
.section-hdr,.section-hdr h2,.section-hdr p,[data-testid="stMarkdownContainer"]{overflow:visible!important}
.rh-card{background:rgba(139,92,246,.06);border:1px solid rgba(139,92,246,.2);border-radius:10px;padding:16px 20px;margin:8px 0;line-height:2}
.rr-card{background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:10px;padding:14px 18px;margin:8px 0}
.edu-card{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:10px 12px;margin:0 0 8px 0}
.edu-card strong{color:var(--cyan)}
.stMarkdown p{font-size:.95rem!important;line-height:1.7!important}
[data-testid="stWidgetLabel"] button,[data-testid="stWidgetLabel"] [role="button"]{
  color:#e2e8f0!important;opacity:1!important;
  background:rgba(148,163,184,.2)!important;border:1px solid rgba(148,163,184,.45)!important;
  border-radius:50%!important;min-width:1.75rem!important;min-height:1.75rem!important;
}
[data-testid="stWidgetLabel"] button:hover,[data-testid="stWidgetLabel"] [role="button"]:hover{
  color:#fff!important;background:rgba(6,182,212,.3)!important;border-color:#22d3ee!important;
}
[data-testid="stWidgetLabel"] svg{fill:currentColor!important;color:#e2e8f0!important}
/* FINAL TOOLTIP VISIBILITY FIX */
div[data-testid="stTooltipHoverTarget"] {
    color: #00E5FF !important; cursor: help !important;
}
/* Force the actual pop-up container */
div[data-testid="stTooltipContent"],
div[data-baseweb="tooltip"] {
    background-color: #020617 !important;
    border: 1px solid rgba(148,163,184,.45) !important;
    border-left: 4px solid #00e5ff !important;
    min-width: 350px !important;
    padding: 15px !important;
    opacity: 1 !important;
    visibility: visible !important;
}
/* Force the text INSIDE the pop-up to be Off-White */
div[data-testid="stTooltipContent"] p,
div[data-baseweb="tooltip"] p {
    color: #f1f5f9 !important;
    font-size: 14px !important;
    line-height: 1.6 !important;
}
.diamond-blue{background:linear-gradient(135deg,rgba(59,130,246,.15),rgba(6,182,212,.10));border:2px solid rgba(59,130,246,.5);border-radius:14px;padding:20px 24px;margin:12px 0}
.diamond-pink{background:linear-gradient(135deg,rgba(236,72,153,.15),rgba(244,114,182,.10));border:2px solid rgba(236,72,153,.5);border-radius:14px;padding:20px 24px;margin:12px 0}
.gold-zone{background:linear-gradient(135deg,rgba(245,158,11,.12),rgba(234,179,8,.08));border:2px solid rgba(245,158,11,.5);border-radius:14px;padding:18px 22px;margin:12px 0}
.confluence-meter{background:var(--bg2);border:1px solid var(--bdr);border-radius:12px;padding:18px 22px;margin:10px 0}
.confluence-meter .bar{height:10px;border-radius:5px;margin:3px 0}
.scanner-row{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:12px 16px;margin:6px 0;transition:background .15s}
.scanner-row:hover{background:var(--bg3)}
.diamond-badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:.75rem;font-weight:700;letter-spacing:.03em}
.badge-blue{background:rgba(59,130,246,.2);color:#60a5fa;border:1px solid rgba(59,130,246,.4)}
.badge-pink{background:rgba(236,72,153,.2);color:#f472b6;border:1px solid rgba(236,72,153,.4)}
.badge-none{background:rgba(100,116,139,.15);color:#94a3b8;border:1px solid rgba(100,116,139,.3)}
.badge-gold{background:rgba(245,158,11,.2);color:#fbbf24;border:1px solid rgba(245,158,11,.4)}
.trade-master{
  background:linear-gradient(145deg,rgba(0,229,255,.11),rgba(2,6,23,.96));
  border:2px solid #00e5ff;border-radius:14px;padding:16px 18px;margin:0;
  box-shadow:0 0 30px rgba(0,229,255,.18),inset 0 1px 1px rgba(255,255,255,.05),0 10px 24px rgba(2,6,23,.55);
  animation:pulse 1.9s ease-in-out infinite;
}
.trade-master .strike-big{
  font-size:clamp(2rem,5vw,3.2rem);font-weight:900;color:#00e5ff;font-family:'JetBrains Mono',monospace;
  line-height:1.12;text-shadow:0 0 28px rgba(0,229,255,.4);letter-spacing:-.02em;
}
.rh-stepper{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:8px;margin-top:10px;align-items:stretch;justify-content:center}
.rh-step{
  background:rgba(0,229,255,.05);border:1px solid rgba(0,229,255,.3);border-radius:10px;
  padding:8px 10px;min-height:88px;position:relative;transition:border-color .2s,box-shadow .2s,background .2s;
}
.rh-step .num{font-family:'JetBrains Mono',monospace;font-weight:700;color:#00E5FF;font-size:.78rem;letter-spacing:.08em}
.rh-step .txt{font-size:.82rem;color:#e2e8f0;line-height:1.35;margin-top:4px}
.rh-step:hover{border-color:#00E5FF;box-shadow:0 0 16px rgba(0,229,255,.38);background:rgba(0,229,255,.09)}
.rh-step:after{
  content:'>';position:absolute;right:-10px;top:50%;transform:translateY(-50%);
  color:rgba(0,229,255,.7);font-size:.95rem;
}
.rh-step:last-child:after{display:none}
@keyframes pulse{
  0%,100%{box-shadow:0 0 10px rgba(0,229,255,.2),0 0 20px rgba(0,229,255,.4),inset 0 1px 1px rgba(255,255,255,.05),0 10px 24px rgba(2,6,23,.55)}
  50%{box-shadow:0 0 25px rgba(0,229,255,.5),0 0 20px rgba(0,229,255,.4),inset 0 1px 1px rgba(255,255,255,.08),0 14px 30px rgba(2,6,23,.7)}
}
.execution-shell{display:grid;grid-template-columns:1.25fr 1fr;gap:12px;align-items:stretch;margin:8px 0 10px 0;min-width:0}
.execution-col{min-width:0;overflow:hidden}
.bluf{margin:0!important;height:100%}
.trade-master{height:100%}
@media(max-width:1100px){
  .execution-shell{grid-template-columns:1fr}
}
@media(max-width:900px){
  .rh-stepper{grid-template-columns:1fr;gap:6px}
  .rh-step{min-height:unset}
  .rh-step:after{display:none}
}
.diamond-win-badge{
  display:inline-block;padding:8px 18px;border-radius:999px;background:rgba(16,185,129,.22);
  border:1px solid #34d399;color:#a7f3d0;font-weight:800;font-size:1.05rem;margin:10px 0;
  font-family:'JetBrains Mono',monospace;
}
#MainMenu{display:none!important}
footer{display:none!important}
[data-testid="stToolbar"]{display:none!important}
[data-testid="stDecoration"]{display:none!important}
[data-testid="stStatusWidget"]{display:none!important}
header{display:none!important}
[data-testid="stHeader"]{display:none!important}
[data-testid="stAppHeader"]{display:none!important}
[data-testid^="stHeader"]{display:none!important}
@keyframes sobg{
  0%,100%{box-shadow:0 0 20px rgba(0,229,255,.6)}
  50%{box-shadow:0 0 35px rgba(0,229,255,1),0 0 70px rgba(0,229,255,.35)}
}
.sticky-nav{
  position:fixed;top:0;left:0;width:100%;height:var(--nav-h);
  z-index:99999;
  pointer-events:auto!important;
  background:rgba(8,12,20,.8)!important;
  backdrop-filter:blur(15px);-webkit-backdrop-filter:blur(15px);
  border-bottom:1px solid #1e293b;
  display:flex;align-items:center;justify-content:center;gap:6px;
  padding:0 12px 0 72px;
  box-shadow:0 2px 24px rgba(0,0,0,.4);
}
.sticky-nav-track{
  flex:1;min-width:0;display:flex;align-items:center;justify-content:center;gap:4px;
  overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin;
  padding:0 4px;mask-image:linear-gradient(90deg,transparent 0,#000 8px,#000 calc(100% - 8px),transparent 100%);
}
.cf-vip-fab{
  position:fixed!important;top:80px!important;left:20px!important;z-index:1000008!important;
  width:56px!important;height:56px!important;margin:0!important;padding:0!important;border-radius:50%!important;
  border:2px solid rgba(255,255,255,.4)!important;
  background:#00e5ff!important;color:#080c14!important;font-size:22px!important;font-weight:800!important;line-height:1!important;
  cursor:pointer!important;display:flex!important;align-items:center!important;justify-content:center!important;
  box-shadow:0 0 22px rgba(0,229,255,.65)!important;animation:sobg 2s ease-in-out infinite;
  transition:transform .15s,background .15s,box-shadow .15s!important;
  font-family:'Inter',system-ui,sans-serif!important;
  -webkit-appearance:none!important;appearance:none!important;
}
.cf-vip-fab:hover{
  background:#00b8d4!important;transform:scale(1.08)!important;animation:none!important;
  box-shadow:0 0 36px rgba(0,229,255,.9)!important;
}
.sticky-nav-track a{
  pointer-events:auto!important;z-index:100000!important;
  color:var(--t2);text-decoration:none;
  font-family:'Inter',sans-serif;font-size:.8rem;font-weight:600;
  letter-spacing:.02em;text-transform:uppercase;
  padding:7px 12px;border-radius:6px;
  transition:color .15s,background .15s;white-space:nowrap;flex-shrink:0;
}
.sticky-nav-track a:hover{color:var(--cyan);background:rgba(6,182,212,.1)}
.sticky-nav-track a:active,.sticky-nav-track a:focus{color:#fff;background:rgba(6,182,212,.2)}
@media(max-width:768px){
  .bluf{padding:16px 14px!important}
  .bluf .mono{font-size:2rem!important}
  div[data-testid="stMetric"]{padding:10px 12px!important}
  .tc{padding:14px!important}
  .mobile-hide{display:none!important}
  .sticky-nav{gap:4px;padding:0 6px 0 58px}
  .cf-vip-fab{width:48px!important;height:48px!important;top:76px!important;left:14px!important;font-size:20px!important}
  .sticky-nav-track{justify-content:flex-start;mask-image:none}
  .sticky-nav-track a{font-size:.68rem;padding:6px 8px}
  .cf-tip .cf-tiptext{
    left:50%;transform:translateX(-50%);
    min-width:unset;width:min(92vw,440px);max-width:92vw;
    font-size:15px;line-height:1.56;
  }
}
/* High-density Bloomberg-like spacing */
.main .block-container [data-testid="stVerticalBlock"]{gap:.45rem!important}
.main .block-container [data-testid="stHorizontalBlock"]{gap:.5rem!important}
[data-testid="stVerticalBlock"] > div{margin-top:0!important;margin-bottom:0!important}
div[data-testid="stMetricValue"], .mono, .glance-value, .ticker, .price-value{
  font-family:'JetBrains Mono',monospace!important;
  font-variant-numeric:tabular-nums lining-nums;
}
.glance-value{font-variant-numeric:tabular-nums!important}
.glass-card,.ni,.ac,.scanner-row,.edu-card,.confluence-meter,.rr-card,.rh-card{
  background:var(--glass-bg)!important;border:1px solid var(--glass-bdr)!important;
  backdrop-filter:blur(12px)!important;-webkit-backdrop-filter:blur(12px)!important;
  box-shadow:inset 0 0 0 1px rgba(0,229,255,.22),0 10px 26px rgba(2,6,23,.36)!important;
}
.glance-shell{display:flex;gap:10px;flex-wrap:nowrap;margin:6px 0 10px 0}
.glance-card{padding:10px 12px 10px 12px;border-radius:12px;min-height:unset}
.glance-card-whole{min-width:0}
.glance-row-flex{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}
.glance-text-col{min-width:0;flex:1 1 auto}
.glance-spark-col{flex:0 0 auto;display:flex;align-items:center;justify-content:flex-end}
.glance-spark-svg{display:block;vertical-align:middle}
.glance-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
.glance-mini{height:62px}
.glance-label{font-size:.72rem;color:#a8b6ca;text-transform:uppercase;letter-spacing:.09em;font-weight:700}
.glance-caption{font-size:.78rem;color:#b7c3d4;margin-top:6px;line-height:1.4}
.glance-inner{display:grid;grid-template-columns:1.2fr .9fr;gap:8px;align-items:center}
.trade-master{overflow:hidden;min-width:0}
.trade-master p{overflow-wrap:anywhere;word-break:break-word;hyphens:auto}
@media(max-width:1100px){.glance-shell{flex-wrap:wrap}}
[data-testid="stDataFrame"] tbody tr:hover,
[data-testid="stTable"] tbody tr:hover{
  background:rgba(0,229,255,.12)!important;
  transition:background .2s ease;
}
.earnings-intel{padding:14px 16px;border-radius:12px}
.earnings-intel-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.earn-col{padding:10px 12px;border-radius:10px;background:rgba(2,6,23,.6);border:1px solid rgba(148,163,184,.24)}
.earn-col h4{margin:0 0 8px 0!important;font-size:.84rem!important;letter-spacing:.08em;text-transform:uppercase}
.earn-col ul{margin:0;padding-left:1rem}
.earn-col li{margin:.34rem 0;color:#dbe5f0;font-size:.85rem;line-height:1.35}
.earn-good h4{color:#00FFA3!important}
.earn-bad h4{color:#FF005C!important}
.earn-meta{margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,.08);display:flex;gap:12px;flex-wrap:wrap}
.earn-pill{padding:6px 10px;border-radius:999px;border:1px solid rgba(0,229,255,.35);background:rgba(2,6,23,.66);color:#cbd5e1;font-size:.82rem}
@media(max-width:900px){.earnings-intel-grid{grid-template-columns:1fr}}
/* ── Sidebar: segmented control = sliding pill (scanner / focus / horizon) ── */
[data-testid="stSidebar"] [data-baseweb="segmented-control"]{
  width:100%!important;max-width:100%!important;
  background:linear-gradient(180deg,rgba(15,23,42,.96),rgba(8,12,20,.99))!important;
  border:1px solid rgba(0,229,255,.28)!important;border-radius:12px!important;padding:5px!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 8px 28px rgba(2,6,23,.55)!important;
  min-height:44px!important;
}
[data-testid="stSidebar"] [data-baseweb="segmented-control"] [role="button"]{
  border-radius:9px!important;padding:8px 10px!important;min-height:36px!important;
  font-weight:600!important;font-size:.76rem!important;letter-spacing:.02em!important;
  border:none!important;transition:background .18s ease,color .18s ease,box-shadow .18s ease!important;
  flex:1 1 0!important;justify-content:center!important;
}
[data-testid="stSidebar"] [data-baseweb="segmented-control"] [role="button"][aria-selected="true"]{
  background:linear-gradient(135deg,rgba(0,229,255,.38),rgba(6,182,212,.2))!important;
  color:#f8fafc!important;
  box-shadow:0 0 0 1px rgba(0,229,255,.5),0 4px 20px rgba(0,229,255,.25)!important;
}
[data-testid="stSidebar"] [data-baseweb="segmented-control"] [role="button"][aria-selected="false"]{
  color:#94a3b8!important;background:transparent!important;
}
[data-testid="stSidebar"] [data-baseweb="segmented-control"] [role="button"][aria-selected="false"]:hover{
  color:#e2e8f0!important;background:rgba(148,163,184,.08)!important;
}
/* ── Sidebar: sliders (Quant Edge threshold) ── */
[data-testid="stSidebar"] [data-baseweb="slider"] [data-baseweb="thumb"]{
  background:linear-gradient(180deg,#22d3ee,#0891b2)!important;
  border:2px solid rgba(255,255,255,.85)!important;
  box-shadow:0 0 0 2px rgba(0,229,255,.35),0 4px 14px rgba(0,229,255,.4)!important;
  height:22px!important;width:22px!important;
}
[data-testid="stSidebar"] [data-baseweb="slider"] [data-baseweb="track"]{
  background:rgba(30,41,59,.9)!important;border-radius:999px!important;height:8px!important;
}
[data-testid="stSidebar"] [data-baseweb="slider"] [data-baseweb="track"] [data-index="0"]{
  background:linear-gradient(90deg,rgba(0,229,255,.15),rgba(0,229,255,.55))!important;
  border-radius:999px!important;
}
/* ── Sidebar: toggle switches (chart overlays) ── */
[data-testid="stSidebar"] [data-testid="stToggle"] label{
  font-size:.84rem!important;font-weight:500!important;color:#e2e8f0!important;
}
[data-testid="stSidebar"] [data-baseweb="checkbox"] [data-baseweb="checkmark"]{
  border-radius:999px!important;
}
[data-testid="stSidebar"] [data-testid="stToggle"] [data-baseweb="switch"]{
  background:rgba(30,41,59,.95)!important;border:1px solid rgba(148,163,184,.35)!important;
}
[data-testid="stSidebar"] [data-testid="stToggle"] [data-baseweb="switch"][data-state="checked"]{
  background:linear-gradient(135deg,#0891b2,#06b6d4)!important;border-color:rgba(0,229,255,.5)!important;
  box-shadow:0 0 16px rgba(0,229,255,.35)!important;
}
[data-testid="stSidebar"] .cf-toggle-grid{
  display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;align-items:center;margin-top:4px;
}
[data-testid="stSidebar"] .cf-toggle-grid [data-testid="stToggle"]{margin:0!important;padding:4px 0!important;}
[data-testid="stSidebar"] .cf-widget-hint{
  font-size:.68rem!important;color:#64748b!important;margin:-4px 0 8px 0!important;line-height:1.35!important;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div:first-child{
  border-radius:10px!important;border-color:rgba(0,229,255,.32)!important;
  background:rgba(15,23,42,.85)!important;min-height:42px!important;
}
[data-testid="stSidebar"] [data-baseweb="textarea"]{
  border-radius:10px!important;border-color:rgba(0,229,255,.22)!important;
}
[data-testid="stExpander"]{
  background:rgba(15,23,42,.65)!important;border:1px solid rgba(255,255,255,.1)!important;border-radius:12px!important;
  backdrop-filter:blur(12px)!important;-webkit-backdrop-filter:blur(12px)!important;
  box-shadow:inset 0 0 0 1px rgba(0,229,255,.22),0 10px 26px rgba(2,6,23,.36)!important;
}
[data-testid="stExpander"] details,[data-testid="stExpander"] summary{border:none!important}
[data-testid="stExpander"] summary{background:transparent!important}
[data-testid="stExpander"] *{border-color:transparent!important}
.scanner-row{overflow:hidden}
.scanner-grid{display:flex;justify-content:space-between;align-items:center;flex-wrap:nowrap;gap:10px;overflow-x:auto}
.scanner-grid > div{white-space:nowrap}
.scan-summary{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:360px}
</style>"""

# ─────────────────────────────────────────────────────────────────────────
# SIDEBAR TOGGLE — injected via iframe srcdoc inside st.markdown
# ─────────────────────────────────────────────────────────────────────────
_TOGGLE_JS = r"""(function(){
function resolveDoc(){
  var list=[];
  try{list.push(window.parent);}catch(e1){}
  try{list.push(window.top);}catch(e2){}
  list.push(window);
  for(var i=0;i<list.length;i++){
    try{
      var d=list[i].document;
      if(!d)continue;
      var sb=d.querySelector('section[data-testid="stSidebar"]')||d.querySelector('[data-testid="stSidebar"]');
      var nav=d.querySelector('nav.sticky-nav');
      if(sb&&nav)return d;
    }catch(e3){}
  }
  for(var j=0;j<list.length;j++){
    try{
      var d2=list[j].document;
      if(d2&&(d2.querySelector('section[data-testid="stSidebar"]')||d2.querySelector('[data-testid="stSidebar"]')))return d2;
    }catch(e4){}
  }
  try{return window.parent.document;}catch(e5){return document;}
}
var pd=resolveDoc();
var pw=pd.defaultView||window;
if(pw.__cfSidebarToggleInit)return;
pw.__cfSidebarToggleInit=true;
var legacy=pd.getElementById('sob-host');
if(legacy)try{legacy.remove()}catch(e0){}
var oldFab=pd.getElementById('sob');
if(oldFab&&!oldFab.hasAttribute('data-cf-hamburger'))try{oldFab.remove()}catch(e1){}
var sOpen=true;
function sbEl(){return pd.querySelector('section[data-testid="stSidebar"]')||pd.querySelector('[data-testid="stSidebar"]')}
function iso(){return sOpen}
function applyClosed(sb){
  if(!sb)return;
  sb.setAttribute('aria-expanded','false');
  sb.style.setProperty('display','none','important');
  sb.style.setProperty('visibility','hidden','important');
  sb.style.setProperty('opacity','0','important');
  sb.style.setProperty('min-width','0','important');
  sb.style.setProperty('max-width','0','important');
  sb.style.setProperty('width','0','important');
  sb.style.setProperty('overflow','hidden','important');
  sb.style.setProperty('transform','translateX(-100%)','important');
  sb.style.setProperty('pointer-events','none','important');
}
function applyOpen(sb){
  if(!sb)return;
  sb.setAttribute('aria-expanded','true');
  sb.style.setProperty('display','flex','important');
  sb.style.setProperty('visibility','visible','important');
  sb.style.setProperty('opacity','1','important');
  sb.style.setProperty('width','21rem','important');
  sb.style.setProperty('min-width','21rem','important');
  sb.style.setProperty('max-width','','important');
  sb.style.setProperty('transform','none','important');
  sb.style.setProperty('position','relative','important');
  sb.style.removeProperty('overflow');
  sb.style.removeProperty('pointer-events');
}
function opn(){var sb=sbEl();if(sb){sOpen=true;applyOpen(sb);}}
function cls(){
  var sb=sbEl();
  if(sb){
    sOpen=false;
    applyClosed(sb);
    queueMicrotask(function(){if(!sOpen)applyClosed(sbEl());});
    setTimeout(function(){if(!sOpen)applyClosed(sbEl());},0);
    setTimeout(function(){if(!sOpen)applyClosed(sbEl());},50);
  }
}
function toggleFromUi(ev){
  if(ev){ev.preventDefault();ev.stopPropagation();}
  if(iso())cls();else opn();
}
function onDocClick(ev){
  var el=ev.target;
  if(el&&el.nodeType===3)el=el.parentElement;
  if(!el||!el.closest)return;
  if(!el.closest('[data-cf-hamburger="1"]'))return;
  toggleFromUi(ev);
}
pd.addEventListener('click',onDocClick,false);
function ensureToggle(){
  var fab=pd.getElementById('sob');
  if(!fab){
    fab=pd.createElement('button');
    fab.type='button';fab.id='sob';fab.className='cf-vip-fab';
    fab.setAttribute('data-cf-hamburger','1');fab.setAttribute('aria-label','Open or close settings');
    fab.textContent='\u2630';pd.body.appendChild(fab);
  }else if(!fab.getAttribute('data-cf-hamburger'))fab.setAttribute('data-cf-hamburger','1');
}
function syncToggleUi(){
  ensureToggle();
  if(!sOpen)applyClosed(sbEl());
  var t=pd.getElementById('sob')||pd.querySelector('[data-cf-hamburger="1"]');
  if(!t)return;
  t.textContent=iso()?'\u2715':'\u2630';
  t.title=iso()?'Close settings':'Open settings';
  t.setAttribute('aria-expanded',iso()?'true':'false');
}
function armSidebarMo(){
  var sb=sbEl();
  if(!sb||sb.__cfMo)return;
  sb.__cfMo=1;
  new MutationObserver(function(){
    if(!sOpen){
      var x=sbEl();
      if(x)applyClosed(x);
    }
  }).observe(sb,{attributes:true,attributeFilter:['style','class']});
}
function sobFam(el){while(el){if(el.id==='sob-host')return true;if(el.getAttribute&&el.getAttribute('data-cf-hamburger')==='1')return true;el=el.parentElement}return false}
function nukeKeyb(){var all=pd.querySelectorAll('header,[data-testid*="eader"],[data-testid*="Header"]');for(var i=0;i<all.length;i++){all[i].style.setProperty('display','none','important');}var tw=pd.createTreeWalker(pd.body,NodeFilter.SHOW_TEXT,null);while(tw.nextNode()){var n=tw.currentNode;if(n.textContent&&n.textContent.indexOf('keyb')>=0&&n.parentElement&&!sobFam(n.parentElement)){var p=n.parentElement;p.style.setProperty('display','none','important');p.style.setProperty('visibility','hidden','important')}}}
ensureToggle();
armSidebarMo();
setInterval(function(){ensureToggle();armSidebarMo();syncToggleUi();},400);
nukeKeyb();setInterval(nukeKeyb,1500);
})();"""
_TOGGLE_SRCDOC = _html_mod.escape("<script>" + _TOGGLE_JS + "</script>", quote=True)

st.markdown(
    _CSS + f"""
<button type="button" class="cf-vip-fab" id="sob" data-cf-hamburger="1" aria-label="Open or close settings" title="Settings">&#9776;</button>
<nav class="sticky-nav">
<div class="sticky-nav-track">
<a href="#execution">Execution</a>
<a href="#charts">Charts</a>
<a href="#setup">Setup</a>
<a href="#quant-dashboard">Quant Dashboard</a>
<a href="#strategies">Strategies</a>
<a href="#risk">Risk</a>
<a href="#scanner">Scanner</a>
<a href="#news">News</a>
<a href="#guide">Guide</a>
</div>
</nav>
<iframe data-cf-toggle-boot="1" srcdoc="{_TOGGLE_SRCDOC}" title="" tabindex="-1" aria-hidden="true"></iframe>
""",
    unsafe_allow_html=True,
)

# ═════════════════════════════════════════════════════════════════════════
#  DATA LAYER
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_stock(ticker, period="1y", interval="1d"):
    def _fetch():
        df = yf.Ticker(ticker).history(period=period, interval=interval)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    return retry_fetch(_fetch)

@st.cache_data(ttl=300)
def fetch_intraday_series(symbol, period="5d", interval="1h"):
    """Cached intraday close series for compact UI sparklines."""
    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return pd.Series(dtype=float)
        s = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        return s
    except Exception:
        return pd.Series(dtype=float)

@st.cache_data(ttl=300)
def fetch_info(ticker):
    try:
        return yf.Ticker(ticker).info
    except Exception:
        return {}

@st.cache_data(ttl=300)
def fetch_options(ticker, exp=None):
    """Fetch options chain. Always returns ((calls_df, puts_df), exps) for stable unpacking."""
    empty = (pd.DataFrame(), pd.DataFrame())
    try:
        t = yf.Ticker(str(ticker).upper())
        raw_exps = getattr(t, "options", None)
        if raw_exps is None:
            return empty, []
        exps = [str(x) for x in list(raw_exps)]
        if not exps:
            return empty, []
        pick = exp if exp in exps else exps[0]
        chain = t.option_chain(pick)
        c_raw, p_raw = chain.calls, chain.puts
        calls_df = c_raw.copy() if c_raw is not None and not c_raw.empty else pd.DataFrame()
        puts_df = p_raw.copy() if p_raw is not None and not p_raw.empty else pd.DataFrame()
        return (calls_df, puts_df), exps
    except Exception:
        return empty, []

@st.cache_data(ttl=600)
def fetch_news(ticker):
    try:
        raw = yf.Ticker(ticker).news or []
        items = []
        for n in raw[:8]:
            title = n.get("title") or n.get("content", {}).get("title", "")
            link = n.get("link") or n.get("content", {}).get("canonicalUrl", {}).get("url", "")
            pub = n.get("publisher") or n.get("content", {}).get("provider", {}).get("displayName", "")
            pt = ""
            try:
                ts = n.get("providerPublishTime") or n.get("content", {}).get("pubDate", "")
                if isinstance(ts, (int, float)):
                    pt = datetime.fromtimestamp(ts).strftime("%b %d, %H:%M")
                elif isinstance(ts, str) and ts:
                    pt = ts[:16]
            except Exception:
                pass
            if title:
                items.append({"title": title, "link": link, "pub": pub, "time": pt})
        return items
    except Exception:
        return []

@st.cache_data(ttl=3600)
def fetch_earnings_date(ticker):
    """Fetch next earnings date from yfinance corporate calendar."""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, (list, tuple)) and ed:
                return ed[0]
            return ed if ed else None
        if isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.columns:
                return cal["Earnings Date"].iloc[0]
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"]
                return val.iloc[0] if hasattr(val, "iloc") else val
        return None
    except Exception:
        return None

@st.cache_data(ttl=300)
def fetch_macro():
    data = {}
    for label, sym in {"VIX": "^VIX", "10Y Yield": "^TNX", "DXY (UUP)": "UUP", "SPY": "SPY", "QQQ": "QQQ"}.items():
        try:
            df = yf.Ticker(sym).history(period="5d")
            if not df.empty:
                last = df["Close"].iloc[-1]
                prev = df["Close"].iloc[-2] if len(df) >= 2 else last
                data[label] = {"price": last, "chg": (last / prev - 1) * 100}
        except Exception:
            pass
    if "10Y Yield" not in data:
        data["10Y Yield"] = {"price": 4.5, "chg": 0.0}
    if "VIX" not in data:
        data["VIX"] = {"price": 20.0, "chg": 0.0}
    return data


# ═════════════════════════════════════════════════════════════════════════
#  TECHNICAL ANALYSIS ENGINE
# ═════════════════════════════════════════════════════════════════════════

class TA:
    @staticmethod
    def ema(s, p): return s.ewm(span=p, adjust=False).mean()
    @staticmethod
    def sma(s, p): return s.rolling(window=p).mean()

    @staticmethod
    def rsi(s, p=14):
        d = s.diff()
        g = d.where(d > 0, 0).rolling(p).mean()
        l = (-d.where(d < 0, 0)).rolling(p).mean()
        return 100 - 100 / (1 + g / l)

    @staticmethod
    def rsi2(s): return TA.rsi(s, 2)

    @staticmethod
    def macd(s, fast=12, slow=26, sig=9):
        ef = s.ewm(span=fast, adjust=False).mean()
        es = s.ewm(span=slow, adjust=False).mean()
        ml = ef - es; sl = ml.ewm(span=sig, adjust=False).mean()
        return ml, sl, ml - sl

    @staticmethod
    def bollinger(s, p=20, sd=2):
        m = s.rolling(p).mean(); st = s.rolling(p).std()
        return m + st * sd, m, m - st * sd

    @staticmethod
    def atr(df, p=14):
        hl = df["High"] - df["Low"]
        hc = abs(df["High"] - df["Close"].shift())
        lc = abs(df["Low"] - df["Close"].shift())
        return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(p).mean()

    @staticmethod
    def stoch(df, k=14, d=3):
        lo = df["Low"].rolling(k).min(); hi = df["High"].rolling(k).max()
        kv = 100 * (df["Close"] - lo) / (hi - lo)
        return kv, kv.rolling(d).mean()

    @staticmethod
    def vwap(df):
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        return (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()

    @staticmethod
    def ichimoku(df):
        t = (df["High"].rolling(9).max() + df["Low"].rolling(9).min()) / 2
        k = (df["High"].rolling(26).max() + df["Low"].rolling(26).min()) / 2
        sa = ((t + k) / 2).shift(26)
        sb = ((df["High"].rolling(52).max() + df["Low"].rolling(52).min()) / 2).shift(26)
        return t, k, sa, sb, df["Close"].shift(-26)

    @staticmethod
    def supertrend(df, period=10, mult=3.0):
        """Supertrend — FIXED: uses numpy arrays to avoid pandas chained indexing warnings."""
        atr_v = TA.atr(df, period).values
        hl2 = ((df["High"] + df["Low"]) / 2).values
        close = df["Close"].values
        n = len(df)
        up = hl2 + mult * atr_v
        dn = hl2 - mult * atr_v
        direction = np.empty(n)
        st_line = np.empty(n)
        direction[0] = 1
        st_line[0] = dn[0] if not np.isnan(dn[0]) else close[0]
        for i in range(1, n):
            if np.isnan(up[i]) or np.isnan(dn[i]):
                direction[i] = direction[i-1]
                st_line[i] = st_line[i-1]
                continue
            if close[i] > up[i-1]:
                direction[i] = 1
            elif close[i] < dn[i-1]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]
            if direction[i] == 1:
                st_line[i] = max(dn[i], st_line[i-1]) if direction[i-1] == 1 else dn[i]
            else:
                st_line[i] = min(up[i], st_line[i-1]) if direction[i-1] == -1 else up[i]
        return pd.Series(st_line, index=df.index), pd.Series(direction, index=df.index)

    @staticmethod
    def adx(df, p=14):
        atr_v = TA.atr(df, p)
        dm_p = df["High"].diff(); dm_n = -df["Low"].diff()
        dm_p = dm_p.where((dm_p > dm_n) & (dm_p > 0), 0)
        dm_n = dm_n.where((dm_n > dm_p) & (dm_n > 0), 0)
        di_p = 100 * dm_p.rolling(p).mean() / atr_v
        di_n = 100 * dm_n.rolling(p).mean() / atr_v
        dx = 100 * abs(di_p - di_n) / (di_p + di_n)
        return dx.rolling(p).mean(), di_p, di_n

    @staticmethod
    def cci(df, p=20):
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        sma_tp = tp.rolling(p).mean()
        mad = tp.rolling(p).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma_tp) / (0.015 * mad)

    @staticmethod
    def obv(df):
        return (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()

    @staticmethod
    def volume_profile(df, bins=20):
        pr = np.linspace(df["Low"].min(), df["High"].max(), bins + 1)
        rows = []
        for i in range(len(pr) - 1):
            mask = (df["Close"] >= pr[i]) & (df["Close"] < pr[i+1])
            rows.append({"mid": (pr[i]+pr[i+1])/2, "volume": df.loc[mask, "Volume"].sum()})
        return pd.DataFrame(rows)

    @staticmethod
    def detect_divergences(price_series, indicator_series, lookback=30):
        divs = []
        p = price_series.iloc[-lookback:]
        ind = indicator_series.iloc[-lookback:]
        for i in range(5, len(p) - 1):
            if p.iloc[i] < p.iloc[i-5:i].min() and ind.iloc[i] > ind.iloc[i-5:i].min():
                divs.append({"type": "bullish", "idx": p.index[i], "price": p.iloc[i]})
            if p.iloc[i] > p.iloc[i-5:i].max() and ind.iloc[i] < ind.iloc[i-5:i].max():
                divs.append({"type": "bearish", "idx": p.index[i], "price": p.iloc[i]})
        return divs[-5:]

    @staticmethod
    def fib_retracement(high, low):
        d = high - low
        return {f"{r:.1%}": high - d * r for r in [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]}

    @staticmethod
    def gann_sq9(price):
        sqrt_p = math.sqrt(price); levels = {}
        for i in range(-4, 5):
            if i == 0: continue
            levels[f"Card {'+'if i>0 else ''}{i*180} deg"] = round((sqrt_p + i * 0.5) ** 2, 2)
            levels[f"Ord {'+'if i>0 else ''}{i*90} deg"] = round((sqrt_p + i * 0.25) ** 2, 2)
        return dict(sorted(levels.items(), key=lambda x: x[1]))

    @staticmethod
    def gann_angles(df, lookback=60):
        recent = df.iloc[-lookback:]
        si = recent["Low"].idxmin(); sp = recent.loc[si, "Low"]
        sb = list(recent.index).index(si)
        av = TA.atr(df).iloc[-1]
        if pd.isna(av) or av <= 0: av = sp * 0.02
        bs = len(recent) - 1 - sb
        return {n: round(sp + av * r * bs, 2) for n, r in {"1x1":1,"2x1":2,"1x2":.5,"3x1":3,"1x3":1/3}.items()}, sp

    @staticmethod
    def gann_time_cycles(df):
        recent = df.iloc[-120:]
        si = recent["Low"].idxmin(); sp = list(df.index).index(si)
        results = []
        for c in [30, 60, 90, 120, 180, 360]:
            tp = sp + c
            if tp < len(df):
                results.append({"cycle": c, "date": df.index[tp], "status": "PAST"})
            else:
                results.append({"cycle": c, "date": df.index[-1] + timedelta(days=tp - len(df) + 1), "status": "UPCOMING"})
        return results

    @staticmethod
    def find_sr(df, window=20):
        highs = df["High"].rolling(window, center=True).max()
        lows = df["Low"].rolling(window, center=True).min()
        res_l, sup_l = [], []
        for i in range(window, len(df) - window):
            if df["High"].iloc[i] == highs.iloc[i]: res_l.append(df["High"].iloc[i])
            if df["Low"].iloc[i] == lows.iloc[i]: sup_l.append(df["Low"].iloc[i])
        def cluster(lv, thr=0.02):
            if not lv: return []
            lv = sorted(set(lv)); cs = [[lv[0]]]
            for v in lv[1:]:
                if (v - cs[-1][-1]) / cs[-1][-1] < thr: cs[-1].append(v)
                else: cs.append([v])
            return [np.mean(c) for c in cs]
        return cluster(sup_l), cluster(res_l)

    @staticmethod
    def fvg(df):
        gaps = []
        for i in range(2, len(df)):
            if df["Low"].iloc[i] > df["High"].iloc[i-2]:
                gaps.append({"type":"bullish","top":df["Low"].iloc[i],"bottom":df["High"].iloc[i-2],"date":df.index[i]})
            elif df["High"].iloc[i] < df["Low"].iloc[i-2]:
                gaps.append({"type":"bearish","top":df["Low"].iloc[i-2],"bottom":df["High"].iloc[i],"date":df.index[i]})
        return gaps[-10:]

    @staticmethod
    def market_structure(df, lb=5):
        sh, sl = [], []
        for i in range(lb, len(df) - lb):
            seg = df.iloc[i-lb:i+lb+1]
            if df["High"].iloc[i] == seg["High"].max(): sh.append((df.index[i], df["High"].iloc[i]))
            if df["Low"].iloc[i] == seg["Low"].min(): sl.append((df.index[i], df["Low"].iloc[i]))
        if len(sh) >= 2 and len(sl) >= 2:
            if sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1]: return "BULLISH", sh, sl
            if sh[-1][1] < sh[-2][1] and sl[-1][1] < sl[-2][1]: return "BEARISH", sh, sl
        return "RANGING", sh, sl

    @staticmethod
    def hurst(series):
        """Hurst exponent via variance ratio (aggregated variance method).
        Uses log returns. Var(q-period returns) scales as q^(2H).
        H > 0.55 = trending, H < 0.45 = mean-reverting, ~0.5 = random walk."""
        ts = series.dropna().values
        if len(ts) < 100:
            return 0.5
        rets = np.diff(np.log(ts))
        rets = rets[np.isfinite(rets)]
        if len(rets) < 80:
            return 0.5
        lags = [2, 4, 8, 16, 32, 64]
        lags = [q for q in lags if q < len(rets) // 4]
        if len(lags) < 3:
            return 0.5
        log_lags, log_vars = [], []
        for q in lags:
            agg = np.array([rets[i:i + q].sum() for i in range(0, len(rets) - q + 1, q)])
            if len(agg) < 5:
                continue
            v = np.var(agg, ddof=1)
            if v > 0:
                log_lags.append(np.log(q))
                log_vars.append(np.log(v))
        if len(log_lags) < 3:
            return 0.5
        slope = np.polyfit(log_lags, log_vars, 1)[0]
        H = slope / 2.0
        return round(float(np.clip(H, 0, 1)), 3)


# ═════════════════════════════════════════════════════════════════════════
#  BLACK-SCHOLES ENGINE — Greeks & fair value pricing
# ═════════════════════════════════════════════════════════════════════════

from math import log, sqrt, exp
try:
    from scipy.stats import norm as _norm
    _cdf = _norm.cdf; _pdf = _norm.pdf
except ImportError:
    # Fallback if scipy not installed — rational approximation of CDF
    def _cdf(x):
        a1,a2,a3,a4,a5 = 0.254829592,-0.284496736,1.421413741,-1.453152027,1.061405429
        sign = 1 if x >= 0 else -1; x = abs(x)/sqrt(2)
        t = 1.0/(1.0+0.3275911*x)
        y = 1.0-(((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*exp(-x*x)
        return 0.5*(1.0+sign*y)
    def _pdf(x):
        return exp(-0.5*x*x)/sqrt(2*3.14159265359)

def bs_price(S, K, T, r, sigma, option_type="call"):
    """Black-Scholes option price. S=spot, K=strike, T=years, r=risk-free rate, sigma=IV."""
    sigma = max(sigma, 0.001)
    if T <= 0:
        return max(0, S - K) if option_type == "call" else max(0, K - S)
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    if option_type == "call":
        return S*_cdf(d1) - K*exp(-r*T)*_cdf(d2)
    return K*exp(-r*T)*_cdf(-d2) - S*_cdf(-d1)

def bs_greeks(S, K, T, r, sigma, option_type="call"):
    """Calculate Delta, Gamma, Theta (per day), Vega (per 1% IV move)."""
    sigma = max(sigma, 0.001)
    if T <= 0:
        return {"delta": 1.0 if option_type == "call" else -1.0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    gamma = _pdf(d1) / (S * sigma * sqrt(T))
    vega = S * _pdf(d1) * sqrt(T) / 100  # per 1% move
    if option_type == "call":
        delta = _cdf(d1)
        theta = (-S*_pdf(d1)*sigma/(2*sqrt(T)) - r*K*exp(-r*T)*_cdf(d2)) / 365
    else:
        delta = _cdf(d1) - 1
        theta = (-S*_pdf(d1)*sigma/(2*sqrt(T)) + r*K*exp(-r*T)*_cdf(-d2)) / 365
    return {"delta": round(delta, 3), "gamma": round(gamma, 4), "theta": round(theta, 3), "vega": round(vega, 3)}


# ═════════════════════════════════════════════════════════════════════════
#  EXPECTED VALUE (EV) CALCULATOR
# ═════════════════════════════════════════════════════════════════════════

def calc_ev(premium, max_loss, pop_pct):
    """Calculate Expected Value: EV = (POP * premium) - ((1-POP) * max_loss).
    Returns EV per contract. Positive = edge, negative = avoid."""
    pop = pop_pct / 100
    ev = (pop * premium) - ((1 - pop) * max_loss)
    return round(ev, 2)


def kelly_criterion(win_prob_pct, win_amount, loss_amount):
    """Kelly Criterion: optimal bankroll fraction.
    f* = W - (1-W)/R where W = win probability, R = win/loss payout ratio.
    Returns (full_kelly_pct, half_kelly_pct) as percentages."""
    if loss_amount <= 0 or win_amount <= 0 or win_prob_pct <= 0 or win_prob_pct >= 100:
        return 0.0, 0.0
    W = win_prob_pct / 100
    R = win_amount / loss_amount
    full = W - (1 - W) / R
    half = full / 2
    return round(max(0.0, full) * 100, 1), round(max(0.0, half) * 100, 1)


# ═════════════════════════════════════════════════════════════════════════
#  VOLATILITY SKEW — detects institutional hedging
# ═════════════════════════════════════════════════════════════════════════

def calc_vol_skew(price, calls_df, puts_df, otm_pct=0.10):
    """Compare IV of 10% OTM put vs 10% OTM call. Positive = put skew (bearish hedging)."""
    if calls_df is None or puts_df is None or calls_df.empty or puts_df.empty:
        return None, None, None
    target_put_strike = price * (1 - otm_pct)
    target_call_strike = price * (1 + otm_pct)
    # Find nearest strikes
    put_row = puts_df.iloc[(puts_df["strike"] - target_put_strike).abs().argsort()[:1]]
    call_row = calls_df.iloc[(calls_df["strike"] - target_call_strike).abs().argsort()[:1]]
    put_iv = put_row["impliedVolatility"].values[0] * 100 if not put_row.empty and put_row["impliedVolatility"].values[0] else None
    call_iv = call_row["impliedVolatility"].values[0] * 100 if not call_row.empty and call_row["impliedVolatility"].values[0] else None
    if put_iv and call_iv:
        skew = put_iv - call_iv
        return round(skew, 1), round(put_iv, 1), round(call_iv, 1)
    return None, put_iv, call_iv


# ═════════════════════════════════════════════════════════════════════════
#  QUANT EDGE SCORE — DE-CORRELATED (no double-counting momentum)
# ═════════════════════════════════════════════════════════════════════════

def quant_edge_score(df, vix_val=None):
    """Composite 0-100 using 5 NON-CORRELATED dimensions:
    1. Trend (EMA stack) — price structure
    2. Momentum (RSI only — single oscillator, not RSI+MACD+CCI which are collinear)
    3. Volume (OBV) — independent of price momentum
    4. Volatility (ATR regime + VIX) — separate dimension
    5. Structure (market structure BOS/CHOCH) — pattern recognition
    Each weighted equally at 20% to avoid false confidence from redundant signals.
    """
    sc = {}; close = df["Close"].iloc[-1]
    # 1. TREND (30% weight — most important for CC sellers)
    if len(df) >= 200:
        e20, e50, e200 = [TA.ema(df["Close"], p).iloc[-1] for p in (20, 50, 200)]
        sc["trend"] = 95 if close > e20 > e50 > e200 else (75 if close > e50 > e200 else (55 if close > e200 else 25))
    else: sc["trend"] = 60
    # 2. MOMENTUM (single indicator: RSI — avoids collinearity with MACD/CCI)
    rv = TA.rsi(df["Close"]).iloc[-1]
    sc["momentum"] = 85 if 40 <= rv <= 60 else (65 if 30 <= rv <= 70 else 25)
    # 3. VOLUME (OBV — measures accumulation/distribution, orthogonal to price momentum)
    obv_s = TA.obv(df)
    sc["volume"] = (85 if obv_s.iloc[-1] > obv_s.iloc[-20] else 35) if len(obv_s) >= 20 else 50
    # 4. VOLATILITY (ATR regime + VIX — for premium sellers, higher = better)
    if len(df) >= 20:
        cur_atr = TA.atr(df).iloc[-1]
        avg_atr = TA.atr(df).iloc[-60:].mean() if len(df) >= 60 else cur_atr
        atr_ratio = cur_atr / avg_atr if avg_atr > 0 else 1
        vol_score = min(100, max(20, 50 + (atr_ratio - 1) * 30))
        if vix_val and vix_val > 0:
            vix_score = min(100, max(20, 30 + (vix_val - 12) * 3))
            vol_score = (vol_score + vix_score) / 2
        sc["volatility"] = vol_score
    else:
        sc["volatility"] = 50
    # 5. STRUCTURE (BOS/CHOCH — pattern-based, not derived from moving averages)
    struct, _, _ = TA.market_structure(df)
    sc["structure"] = 90 if struct == "BULLISH" else (50 if struct == "RANGING" else 20)

    composite = round(np.mean(list(sc.values())), 1)
    return composite, sc


def weekly_trend_label(df_wk):
    """Weekly bias using MACD(12,26,9) and EMA(20) on weekly closes."""
    if df_wk is None or len(df_wk) < 26:
        return "UNKNOWN", "#64748b"
    ml, sl, _ = TA.macd(df_wk["Close"], 12, 26, 9)
    e20 = TA.ema(df_wk["Close"], 20).iloc[-1]
    above_ema = df_wk["Close"].iloc[-1] > e20
    macd_bull = ml.iloc[-1] > sl.iloc[-1]
    if above_ema and macd_bull:
        return "BULLISH", "#10b981"
    if not above_ema and not macd_bull:
        return "BEARISH", "#ef4444"
    return "MIXED", "#f59e0b"


# ═════════════════════════════════════════════════════════════════════════
#  GOLD ZONE — dynamic confluence support/resistance
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def calc_gold_zone(df, df_wk=None):
    """Gold Zone: weighted average of Volume-Profile POC, 61.8% Fibonacci,
    nearest Gann Sq9 level, and higher-TF order-block approximation.
    Returns (gold_zone_price, component_dict)."""
    price = df["Close"].iloc[-1]
    components = {}

    vp = TA.volume_profile(df)
    if not vp.empty:
        poc = vp.loc[vp["volume"].idxmax(), "mid"]
        components["POC"] = poc

    if len(df) >= 50:
        rec = df.iloc[-60:]
        hi, lo = rec["High"].max(), rec["Low"].min()
        components["Fib 61.8%"] = hi - (hi - lo) * 0.618

    gann = TA.gann_sq9(price)
    if gann:
        below = {k: v for k, v in gann.items() if v <= price}
        above = {k: v for k, v in gann.items() if v > price}
        nearest = min(gann.values(), key=lambda x: abs(x - price))
        components["Gann Sq9"] = nearest

    if df_wk is not None and len(df_wk) >= 20:
        sups, ress = TA.find_sr(df_wk, window=10)
        all_sr = sups + ress
        if all_sr:
            components["Weekly S/R"] = min(all_sr, key=lambda x: abs(x - price))

    if components:
        gold_zone = round(np.mean(list(components.values())), 2)
        return gold_zone, components
    return round(price, 2), {}


# ═════════════════════════════════════════════════════════════════════════
#  CONFLUENCE POINTS — 0-to-9 scoring (Startup.io-inspired, enhanced)
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def calc_confluence_points(df, df_wk=None, vix_val=None):
    """Compute 0-9 bullish confluence score with per-component breakdown.
    Returns (score, max_score, breakdown_dict, bearish_score)."""
    score = 0
    breakdown = {}
    price = df["Close"].iloc[-1]

    st_l, st_d = TA.supertrend(df)
    bull = st_d.iloc[-1] == 1
    pts = 2 if bull else 0
    score += pts
    breakdown["Supertrend"] = {"pts": pts, "max": 2, "detail": "Bullish" if bull else "Bearish"}

    _, _, sa, sb, _ = TA.ichimoku(df)
    above_cloud = (not pd.isna(sa.iloc[-1]) and not pd.isna(sb.iloc[-1])
                   and price > max(sa.iloc[-1], sb.iloc[-1]))
    pts = 2 if above_cloud else 0
    score += pts
    breakdown["Ichimoku"] = {"pts": pts, "max": 2, "detail": "Above Cloud" if above_cloud else "In/Below Cloud"}

    adx_v, dip, din = TA.adx(df)
    adx_val = adx_v.iloc[-1] if not pd.isna(adx_v.iloc[-1]) else 0
    dip_val = dip.iloc[-1] if not pd.isna(dip.iloc[-1]) else 0
    din_val = din.iloc[-1] if not pd.isna(din.iloc[-1]) else 0
    adx_bull = adx_val > 25 and dip_val > din_val
    pts = 1 if adx_bull else 0
    score += pts
    breakdown["ADX+DI"] = {"pts": pts, "max": 1, "detail": f"ADX {adx_val:.0f}, +DI>-DI" if adx_bull else f"ADX {adx_val:.0f}"}

    obv_s = TA.obv(df)
    obv_up = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else False
    pts = 1 if obv_up else 0
    score += pts
    breakdown["OBV"] = {"pts": pts, "max": 1, "detail": "Accumulation" if obv_up else "Distribution"}

    rsi_s = TA.rsi(df["Close"])
    divs = TA.detect_divergences(df["Close"], rsi_s)
    bull_div = any(d["type"] == "bullish" for d in divs[-3:])
    pts = 1 if bull_div else 0
    score += pts
    breakdown["Divergence"] = {"pts": pts, "max": 1, "detail": "Bullish Div Found" if bull_div else "None"}

    gold_zone, _ = calc_gold_zone(df, df_wk)
    above_gz = price > gold_zone
    pts = 1 if above_gz else 0
    score += pts
    breakdown["Gold Zone"] = {"pts": pts, "max": 1, "detail": f"{'Above' if above_gz else 'Below'} ${gold_zone:.2f}"}

    struct, _, _ = TA.market_structure(df)
    pts = 1 if struct == "BULLISH" else 0
    score += pts
    breakdown["Structure"] = {"pts": pts, "max": 1, "detail": struct}

    bearish = 9 - score
    return score, 9, breakdown, bearish


# ═════════════════════════════════════════════════════════════════════════
#  DIAMOND SIGNAL DETECTION — Blue (buy) & Pink (exit/take-profit)
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def detect_diamonds(df, df_wk=None, lookback=None):
    """Blue Diamond: daily confluence jumps to 7+ and weekly bias is BULLISH or MIXED.
    Pink Diamond: daily collapse or overbought fade and weekly bias is BEARISH or MIXED."""
    diamonds = []
    n = len(df)
    if n < 55:
        return diamonds

    st_l, st_d = TA.supertrend(df)
    _, _, sa, sb, _ = TA.ichimoku(df)
    adx_v, dip, din = TA.adx(df)
    obv_s = TA.obv(df)
    rsi_s = TA.rsi(df["Close"])
    struct, _, _ = TA.market_structure(df)
    gold_zone, _ = calc_gold_zone(df, df_wk)

    wk_bias = "UNKNOWN"
    if df_wk is not None and len(df_wk) >= 26:
        wk_bias, _ = weekly_trend_label(df_wk)

    start = max(52, 26)
    prev_score = 0

    for i in range(start, n):
        sc = 0
        pi = df["Close"].iloc[i]

        if st_d.iloc[i] == 1:
            sc += 2
        if (not pd.isna(sa.iloc[i]) and not pd.isna(sb.iloc[i])
                and pi > max(sa.iloc[i], sb.iloc[i])):
            sc += 2
        if (not pd.isna(adx_v.iloc[i]) and adx_v.iloc[i] > 25
                and not pd.isna(dip.iloc[i]) and not pd.isna(din.iloc[i])
                and dip.iloc[i] > din.iloc[i]):
            sc += 1
        if i >= 20 and obv_s.iloc[i] > obv_s.iloc[i - 20]:
            sc += 1
        if pi > gold_zone:
            sc += 1
        if struct == "BULLISH":
            sc += 1

        rsi_i = rsi_s.iloc[i] if not pd.isna(rsi_s.iloc[i]) else 50

        # Blue Diamond: daily surge + weekly agrees (bullish or mixed only)
        if sc >= 7 and prev_score < 7 and wk_bias in ("BULLISH", "MIXED"):
            diamonds.append({"date": df.index[i], "price": pi, "type": "blue",
                             "score": sc, "rsi": rsi_i, "weekly": wk_bias})

        # Pink Diamond: daily collapse + weekly agrees (bearish or mixed only)
        if ((sc <= 3 and prev_score >= 5) or (rsi_i > 75 and sc <= 4 and prev_score > 4)) and wk_bias in ("BEARISH", "MIXED"):
            diamonds.append({"date": df.index[i], "price": pi, "type": "pink",
                             "score": sc, "rsi": rsi_i, "weekly": wk_bias})

        prev_score = sc

    return diamonds


def diamond_win_rate(df, diamonds, forward_bars=10):
    """Backtest diamond signals: for Blue, check if price rose; for Pink, check
    if price fell.  Returns (win_rate_pct, avg_return_pct, sample_count)."""
    if not diamonds:
        return 0.0, 0.0, 0

    wins, total = 0, 0
    returns = []

    for d in diamonds:
        try:
            idx = df.index.get_loc(d["date"])
        except KeyError:
            continue
        if idx + forward_bars >= len(df):
            continue

        entry = d["price"]
        exit_p = df["Close"].iloc[idx + forward_bars]

        if d["type"] == "blue":
            ret = (exit_p - entry) / entry * 100
            if exit_p > entry:
                wins += 1
        else:
            ret = (entry - exit_p) / entry * 100
            if exit_p < entry:
                wins += 1

        returns.append(ret)
        total += 1

    if total == 0:
        return 0.0, 0.0, 0
    return round(wins / total * 100, 1), round(float(np.mean(returns)), 2), total


def latest_diamond_status(diamonds):
    """Return the most recent diamond or None."""
    if not diamonds:
        return None
    return diamonds[-1]


# ═════════════════════════════════════════════════════════════════════════
#  MARKET SCANNER — batch-scan a watchlist
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def scan_single_ticker(tkr):
    """Fetch data and compute all scores for a single ticker (for the scanner)."""
    try:
        df = fetch_stock(tkr, "1y", "1d")
        if df is None or len(df) < 60:
            return None
        df_wk = fetch_stock(tkr, "2y", "1wk")
        price = df["Close"].iloc[-1]
        prev = df["Close"].iloc[-2] if len(df) >= 2 else price
        chg_pct = (price / prev - 1) * 100

        qs, _ = quant_edge_score(df)
        cp_score, cp_max, cp_bd, _ = calc_confluence_points(df, df_wk)
        diamonds = detect_diamonds(df, df_wk)
        latest_d = latest_diamond_status(diamonds)
        gold_zone, _ = calc_gold_zone(df, df_wk)
        dist_gz = (price / gold_zone - 1) * 100 if gold_zone else 0

        struct, _, _ = TA.market_structure(df)
        wk_lbl, _ = weekly_trend_label(df_wk) if df_wk is not None and len(df_wk) >= 26 else ("N/A", "#64748b")

        d_status = "None"
        d_class = "badge-none"
        if latest_d:
            age = (df.index[-1] - latest_d["date"]).days
            if age <= 5:
                d_status = "🔷 BLUE" if latest_d["type"] == "blue" else "💎 PINK"
                d_class = "badge-blue" if latest_d["type"] == "blue" else "badge-pink"

        if cp_score >= 7:
            summary = "Strong bullish setup. High confluence buy zone."
        elif cp_score >= 5:
            summary = "Moderate bullish lean. Watch for confirmation."
        elif cp_score >= 3:
            summary = "Mixed signals. Neutral stance recommended."
        else:
            summary = "Bearish pressure. Defensive posture advised."

        return {"ticker": tkr, "price": price, "chg_pct": chg_pct, "qs": qs,
                "cp_score": cp_score, "cp_max": cp_max, "d_status": d_status,
                "d_class": d_class, "gold_zone": gold_zone, "dist_gz": dist_gz,
                "struct": struct, "wk_trend": wk_lbl, "summary": summary}
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════
#  OPTIONS ENGINE
# ═════════════════════════════════════════════════════════════════════════

class Opt:
    DELTA_TARGET = 0.16
    DELTA_LOW, DELTA_HIGH = 0.15, 0.20
    MIN_OI, MIN_VOL = 100, 10

    @staticmethod
    def _sc(otm, py, ann, vol, delta=None):
        base = py * .25 + min(otm, 15) * .15 + min(ann, 50) * .15 + (1 if vol and vol > 100 else 0) * .05
        if delta is not None:
            d = abs(delta)
            if Opt.DELTA_LOW <= d <= Opt.DELTA_HIGH:
                base += (1.0 - abs(d - Opt.DELTA_TARGET) / 0.05) * 5
            elif d < 0.10 or d > 0.30:
                base *= 0.5
        return base

    @staticmethod
    def covered_calls(price, calls_df, dte=30, rfr=0.045):
        if calls_df is None or calls_df.empty: return []
        rows = []; T_y = max(dte, 1) / 365
        for _, r in calls_df.iterrows():
            s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
            iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
            mid = (b + a) / 2 if b > 0 and a > 0 else 0
            if s <= price or mid <= .01: continue
            if oi < Opt.MIN_OI or vol < Opt.MIN_VOL: continue
            otm = (s - price) / price * 100; py = mid / price * 100; ann = py * 365 / max(dte, 1)
            iv_dec = iv if iv > 0 else 0.5
            greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "call")
            delta = greeks["delta"]
            rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                         "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                         "prem_100": mid * 100, "breakeven": price - mid,
                         "delta": round(delta, 3), "optimal": False,
                         "score": Opt._sc(otm, py, ann, vol, delta)})
        rows.sort(key=lambda x: x["score"], reverse=True)
        if rows:
            best = min(range(len(rows)), key=lambda i: abs(rows[i]["delta"] - Opt.DELTA_TARGET))
            rows[best]["optimal"] = True
        return rows[:8]

    @staticmethod
    def cash_secured_puts(price, puts_df, dte=30, rfr=0.045):
        if puts_df is None or puts_df.empty: return []
        rows = []; T_y = max(dte, 1) / 365
        for _, r in puts_df.iterrows():
            s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
            iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
            mid = (b + a) / 2 if b > 0 and a > 0 else 0
            if s >= price or mid <= .01: continue
            if oi < Opt.MIN_OI or vol < Opt.MIN_VOL: continue
            otm = (price - s) / price * 100; py = mid / s * 100; ann = py * 365 / max(dte, 1)
            iv_dec = iv if iv > 0 else 0.5
            greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "put")
            delta = greeks["delta"]
            rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                         "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                         "prem_100": mid * 100, "eff_buy": s - mid, "cash_req": s * 100,
                         "delta": round(delta, 3), "optimal": False,
                         "score": Opt._sc(otm, py, ann, vol, delta)})
        rows.sort(key=lambda x: x["score"], reverse=True)
        if rows:
            best = min(range(len(rows)), key=lambda i: abs(abs(rows[i]["delta"]) - Opt.DELTA_TARGET))
            rows[best]["optimal"] = True
        return rows[:8]

    @staticmethod
    def credit_spreads(price, opts_df, stype="put_credit"):
        if opts_df is None or opts_df.empty: return []
        rows = []; strikes = sorted(opts_df["strike"].unique())
        for i in range(len(strikes)):
            for j in range(i + 1, min(i + 6, len(strikes))):
                ss = strikes[i] if stype == "call_credit" else strikes[j]
                ls = strikes[j] if stype == "call_credit" else strikes[i]
                sr, lr = opts_df[opts_df["strike"] == ss], opts_df[opts_df["strike"] == ls]
                if sr.empty or lr.empty: continue
                s_oi = (sr["openInterest"].values[0] or 0) if "openInterest" in sr.columns else 0
                s_vol = (sr["volume"].values[0] or 0) if "volume" in sr.columns else 0
                l_oi = (lr["openInterest"].values[0] or 0) if "openInterest" in lr.columns else 0
                l_vol = (lr["volume"].values[0] or 0) if "volume" in lr.columns else 0
                if s_oi < Opt.MIN_OI or s_vol < Opt.MIN_VOL: continue
                if l_oi < Opt.MIN_OI or l_vol < Opt.MIN_VOL: continue
                sm = (sr["bid"].values[0] + sr["ask"].values[0]) / 2
                lm = (lr["bid"].values[0] + lr["ask"].values[0]) / 2
                cr = sm - lm; w = abs(ss - ls)
                if cr <= 0 or w <= cr: continue
                ml = (w - cr) * 100
                otm = ((price - ss) / price * 100) if stype == "put_credit" else ((ss - price) / price * 100)
                if otm < 0: continue
                pop = max(30, min(95, (1 - cr / w) * 100))
                rows.append({"short": ss, "long": ls, "credit": cr, "credit_100": cr * 100,
                             "max_loss": ml, "width": w, "rr": cr / (w - cr), "pop": pop, "otm_pct": otm,
                             "be": ss - cr if stype == "put_credit" else ss + cr})
        rows.sort(key=lambda x: x["rr"] * x["pop"], reverse=True)
        return rows[:8]


# ═════════════════════════════════════════════════════════════════════════
#  SENTIMENT, BACKTEST, ALERTS
# ═════════════════════════════════════════════════════════════════════════

class Sentiment:
    @staticmethod
    def fear_greed(df, vix_val=None):
        sc = [min(100, max(0, TA.rsi(df["Close"]).iloc[-1]))]
        sma200 = df["Close"].rolling(200).mean().iloc[-1] if len(df) >= 200 else df["Close"].mean()
        sc.append(min(100, max(0, 50 + (df["Close"].iloc[-1]/sma200-1)*500)))
        if len(df) >= 20:
            sc.append(min(100, max(0, 50 + (df["Close"].iloc[-1]/df["Close"].iloc[-20]-1)*300)))
            cv = df["Close"].pct_change().iloc[-20:].std()*np.sqrt(252)*100
            hv = df["Close"].pct_change().std()*np.sqrt(252)*100
            sc.append(max(0, min(100, 100-cv/max(hv,1)*50)))
        if vix_val and vix_val > 0: sc.append(max(0, min(100, 100-(vix_val-12)*3)))
        return np.mean(sc)

    @staticmethod
    def interpret(s):
        if s >= 80: return "Extreme Greed","🔴","Everyone is euphoric. Sell calls aggressively and collect the hype premium."
        if s >= 60: return "Greed","🟠","Market is confident. Sell covered calls at higher strikes to ride the wave."
        if s >= 40: return "Neutral","🟡","Market is calm. Standard premium selling works great here."
        if s >= 20: return "Fear","🟢","Fear is elevated. Premiums are fat. Sell aggressively and collect extra cash."
        return "Extreme Fear","💚","Maximum panic. Premiums are huge. Sell puts at deep discounts and get paid."

class Backtest:
    @staticmethod
    def cc_sim(df, otm_pct=.05, hold=30, iv_m=1.0):
        results = []; rvol = df["Close"].pct_change().rolling(20).std()*np.sqrt(252)
        i = 20
        while i < len(df) - hold:
            entry = df["Close"].iloc[i]; strike = entry*(1+otm_pct)
            iv = rvol.iloc[i]
            if pd.isna(iv) or iv <= 0: iv = 0.5
            iv *= iv_m; tf = math.sqrt(hold/365)
            d1a = otm_pct/(iv*tf) if iv*tf > 0 else 1
            prem = entry*iv*tf*max(.05,.4-.3*min(d1a,2)); prem = max(prem, entry*.003)
            exit_p = df["Close"].iloc[i+hold]
            if exit_p >= strike: profit = (strike-entry)+prem; out = "Called Away"
            else: profit = prem+(exit_p-entry); out = "Expired OTM"
            results.append({"entry_date":df.index[i],"exit_date":df.index[i+hold],
                "entry":entry,"strike":strike,"exit":exit_p,"iv_est":iv*100,
                "premium":prem,"profit":profit,"ret_pct":profit/entry*100,"outcome":out})
            i += hold
        return pd.DataFrame(results)

class Alerts:
    @staticmethod
    def scan(df, ticker, vix_val=None):
        alerts = []; close = df["Close"].iloc[-1]; rv = TA.rsi(df["Close"]).iloc[-1]
        if rv < 30: alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} RSI is {rv:.1f}. Stock is oversold. Great time to sell puts and collect cash."})
        elif rv > 70: alerts.append({"t":"bearish","p":"MEDIUM","m":f"{ticker} RSI is {rv:.1f}. Stock is overbought. Sell covered calls now."})
        ml, sl, _ = TA.macd(df["Close"])
        if len(ml) >= 2:
            if ml.iloc[-1] > sl.iloc[-1] and ml.iloc[-2] <= sl.iloc[-2]:
                alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} MACD just crossed bullish. Buyers are taking over."})
            elif ml.iloc[-1] < sl.iloc[-1] and ml.iloc[-2] >= sl.iloc[-2]:
                alerts.append({"t":"bearish","p":"MEDIUM","m":f"{ticker} MACD just crossed bearish. Sellers are gaining control."})
        u, _, lo = TA.bollinger(df["Close"])
        if len(u)>1:
            bw = (u.iloc[-1]-lo.iloc[-1])/((u.iloc[-1]+lo.iloc[-1])/2)*100
            if bw < 5: alerts.append({"t":"neutral","p":"HIGH","m":f"{ticker} Bollinger squeeze detected. A big move is coming soon."})
        if vix_val and vix_val > 30: alerts.append({"t":"bullish","p":"HIGH","m":f"VIX is {vix_val:.1f}. Extreme fear. Premiums are huge right now."})
        elif vix_val and vix_val > 25: alerts.append({"t":"bullish","p":"MEDIUM","m":f"VIX is {vix_val:.1f}. Fear is elevated. Good time to sell options."})
        st_l, st_d = TA.supertrend(df)
        if len(st_d) >= 2:
            if st_d.iloc[-1]==1 and st_d.iloc[-2]==-1: alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} Supertrend just flipped BULLISH. The price floor is rising."})
            elif st_d.iloc[-1]==-1 and st_d.iloc[-2]==1: alerts.append({"t":"bearish","p":"HIGH","m":f"{ticker} Supertrend just flipped BEARISH. The price ceiling is falling."})
        rsi_s = TA.rsi(df["Close"]); divs = TA.detect_divergences(df["Close"], rsi_s)
        for d in divs[-2:]:
            alerts.append({"t":d["type"],"p":"MEDIUM","m":f"{ticker} RSI {d['type']} divergence near ${d['price']:.2f}. Early warning of a reversal."})
        return alerts


# ═════════════════════════════════════════════════════════════════════════
#  CHART BUILDER
# ═════════════════════════════════════════════════════════════════════════

def build_chart(df, ticker, show_ind=True, show_fib=True, show_gann=True, show_sr=True,
                show_ichi=False, show_super=False, diamonds=None, gold_zone=None):
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[.55,.15,.15,.15])
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color="#10b981", decreasing_line_color="#ef4444",
        increasing_fillcolor="#10b981", decreasing_fillcolor="#ef4444", name="Price"), row=1, col=1)
    if show_ind:
        for p, c in [(20,"#3b82f6"),(50,"#f59e0b"),(200,"#8b5cf6")]:
            if len(df) >= p:
                fig.add_trace(go.Scatter(x=df.index, y=TA.ema(df["Close"],p), mode="lines",
                    line=dict(color=c,width=1), name=f"EMA{p}", opacity=.7), row=1, col=1)
        u, m, lo = TA.bollinger(df["Close"])
        fig.add_trace(go.Scatter(x=df.index,y=u,line=dict(color="rgba(100,116,139,.3)",width=1),name="BB+",showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index,y=lo,line=dict(color="rgba(100,116,139,.3)",width=1),fill="tonexty",fillcolor="rgba(100,116,139,.05)",name="BB-",showlegend=False), row=1, col=1)
    if show_ichi:
        t, k, sa, sb, _ = TA.ichimoku(df)
        fig.add_trace(go.Scatter(x=df.index,y=t,line=dict(color="#06b6d4",width=1),name="Tenkan",opacity=.6), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index,y=k,line=dict(color="#ef4444",width=1),name="Kijun",opacity=.6), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index,y=sa,line=dict(color="rgba(16,185,129,.3)",width=0),name="SenkouA",showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index,y=sb,line=dict(color="rgba(239,68,68,.3)",width=0),fill="tonexty",fillcolor="rgba(16,185,129,.08)",name="Cloud"), row=1, col=1)
    if show_super:
        st_l, st_d = TA.supertrend(df)
        fig.add_trace(go.Scatter(x=df.index,y=st_l,mode="lines",line=dict(color="#06b6d4",width=2),name="Supertrend"), row=1, col=1)
    if show_fib and len(df) >= 50:
        rec = df.iloc[-60:]; fl = TA.fib_retracement(rec["High"].max(), rec["Low"].min())
        cols = ["#64748b","#06b6d4","#3b82f6","#8b5cf6","#f59e0b","#ef4444","#64748b"]
        for (lab,lev),clr in zip(fl.items(), cols):
            fig.add_hline(y=lev,line_dash="dot",line_color=clr,annotation_text=f"Fib {lab}: ${lev:.2f}",annotation_position="right",opacity=.5,row=1,col=1)
    if show_gann:
        cur = df["Close"].iloc[-1]; gl = TA.gann_sq9(cur)
        near = sorted(gl.items(), key=lambda x: abs(x[1]-cur))[:6]
        for lab, lev in near:
            fig.add_hline(y=lev,line_dash="dash",line_color="rgba(245,158,11,.35)",annotation_text=f"G:{lab} ${lev:.0f}",annotation_position="left",opacity=.4,row=1,col=1)
    if show_sr:
        sups, ress = TA.find_sr(df)
        for s in sups[-3:]: fig.add_hline(y=s,line_dash="solid",line_color="rgba(16,185,129,.4)",annotation_text=f"S ${s:.2f}",opacity=.5,row=1,col=1)
        for r in ress[-3:]: fig.add_hline(y=r,line_dash="solid",line_color="rgba(239,68,68,.4)",annotation_text=f"R ${r:.2f}",opacity=.5,row=1,col=1)
    # ── GOLD ZONE (thick golden horizontal line) ──
    if gold_zone is not None:
        fig.add_hline(y=gold_zone, line_dash="solid", line_color="#eab308",
                      line_width=3, opacity=0.85,
                      annotation_text=f"⬥ Gold Zone ${gold_zone:.2f}",
                      annotation_position="right",
                      annotation_font=dict(color="#fbbf24", size=12, family="JetBrains Mono"),
                      row=1, col=1)

    # ── DIAMOND SIGNALS (Blue = bullish entry, Pink = bearish exit) ──
    if diamonds:
        blue_d = [d for d in diamonds if d["type"] == "blue"]
        pink_d = [d for d in diamonds if d["type"] == "pink"]
        if blue_d:
            fig.add_trace(go.Scatter(
                x=[d["date"] for d in blue_d],
                y=[d["price"] * 0.97 for d in blue_d],
                mode="markers+text",
                marker=dict(symbol="diamond", size=16, color="#3b82f6",
                            line=dict(color="#60a5fa", width=2)),
                text=["🔷" for _ in blue_d],
                textposition="bottom center",
                textfont=dict(size=14),
                name="Blue Diamond",
                hovertemplate="<b>BLUE DIAMOND</b><br>Date: %{x}<br>Price: $%{customdata:.2f}<br>Strong Buy Signal<extra></extra>",
                customdata=[d["price"] for d in blue_d]
            ), row=1, col=1)
        if pink_d:
            fig.add_trace(go.Scatter(
                x=[d["date"] for d in pink_d],
                y=[d["price"] * 1.03 for d in pink_d],
                mode="markers+text",
                marker=dict(symbol="diamond", size=16, color="#ec4899",
                            line=dict(color="#f472b6", width=2)),
                text=["💎" for _ in pink_d],
                textposition="top center",
                textfont=dict(size=14),
                name="Pink Diamond",
                hovertemplate="<b>PINK DIAMOND</b><br>Date: %{x}<br>Price: $%{customdata:.2f}<br>Take Profit / Exit<extra></extra>",
                customdata=[d["price"] for d in pink_d]
            ), row=1, col=1)

    vc = ["#10b981" if c>=o else "#ef4444" for c,o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index,y=df["Volume"],marker_color=vc,name="Vol",opacity=.6), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index,y=TA.rsi(df["Close"]),line=dict(color="#8b5cf6",width=1.5),name="RSI"), row=3, col=1)
    fig.add_hline(y=70,line_dash="dash",line_color="rgba(239,68,68,.5)",row=3,col=1)
    fig.add_hline(y=30,line_dash="dash",line_color="rgba(16,185,129,.5)",row=3,col=1)
    ml, sl, hist = TA.macd(df["Close"])
    fig.add_trace(go.Scatter(x=df.index,y=ml,line=dict(color="#3b82f6",width=1.5),name="MACD"), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index,y=sl,line=dict(color="#f59e0b",width=1),name="Signal"), row=4, col=1)
    hc = ["#10b981" if v>=0 else "#ef4444" for v in hist]
    fig.add_trace(go.Bar(x=df.index,y=hist,marker_color=hc,name="Hist",opacity=.6), row=4, col=1)
    fig.update_layout(template="plotly_dark",paper_bgcolor="#080c14",plot_bgcolor="#080c14",
        font=dict(family="JetBrains Mono, monospace",size=11,color="#94a3b8"),
        height=800,margin=dict(l=60,r=56,t=52,b=20),xaxis_rangeslider_visible=False,
        showlegend=True,legend=dict(orientation="h",yanchor="bottom",y=1.08,xanchor="left",x=0,font=dict(size=10),bgcolor="rgba(0,0,0,0)"))
    for i in range(1,5):
        fig.update_xaxes(gridcolor="#1e293b",zeroline=False,row=i,col=1)
        fig.update_yaxes(gridcolor="#1e293b",zeroline=False,row=i,col=1)
    return fig


# ═════════════════════════════════════════════════════════════════════════
#  UI HELPERS — reusable explanation cards and section dividers
# ═════════════════════════════════════════════════════════════════════════

def _factor_checklist_labels():
    return {
        "Supertrend": "Supertrend supports buyers",
        "Ichimoku": "Price above the cloud",
        "ADX+DI": "Strong trend with buyers in front",
        "OBV": "Big money accumulation",
        "Divergence": "Bullish divergence hint",
        "Gold Zone": "Above Gold Zone",
        "Structure": "Higher highs and higher lows",
    }


def _explain(title, body, mood="neutral"):
    """Render an explanation card with color-coded border."""
    colors = {"bull": ("#10b981", "rgba(16,185,129,.08)"),
              "bear": ("#ef4444", "rgba(239,68,68,.08)"),
              "neutral": ("#06b6d4", "rgba(6,182,212,.08)")}
    c, bg = colors.get(mood, colors["neutral"])
    st.markdown(
        f"<div class='explain' style='background:{bg};border-left-color:{c}'>"
        f"<div style='font-size:.8rem;font-weight:700;color:{c};text-transform:uppercase;"
        f"letter-spacing:.05em;margin-bottom:8px'>{title}</div>"
        f"<div style='color:#e2e8f0;font-size:.95rem;line-height:1.7'>{body}</div></div>",
        unsafe_allow_html=True)

def _section(title, subtitle="", tip_plain=""):
    """Render a prominent section divider. Optional tip_plain: short plain text shown on (i) hover."""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    tip_el = ""
    if tip_plain:
        ta = _html_mod.escape(tip_plain.strip().replace("\n", " "))
        tip_el = f"<span class='cf-tip' tabindex='0'>i<span class='cf-tiptext'>{ta}</span></span>"
    st.markdown(f"<div class='section-hdr'><h2>{title}</h2>{tip_el}{sub}</div>", unsafe_allow_html=True)

def _mini_sparkline(series, color="#00E5FF"):
    """Compact sparkline for glance cards."""
    def _to_rgba(c, alpha=0.14):
        c = (c or "").strip()
        if c.startswith("#") and len(c) == 7:
            r = int(c[1:3], 16)
            g = int(c[3:5], 16)
            b = int(c[5:7], 16)
            return f"rgba({r},{g},{b},{alpha})"
        return f"rgba(0,229,255,{alpha})"

    s = pd.Series(series).dropna()
    if s.empty:
        s = pd.Series([0.0, 0.0])
    # Light smoothing for noisy intraday prints while preserving direction.
    if len(s) >= 5:
        s = s.rolling(3, min_periods=1).mean()
    min_v = float(s.min())
    max_v = float(s.max())
    pad = max(0.001, (max_v - min_v) * 0.15)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(s))), y=s.tolist(), mode="lines",
        line=dict(color=color, width=3), hoverinfo="skip",
        fill="tozeroy", fillcolor=_to_rgba(color, 0.14)
    ))
    fig.update_layout(
        template=None, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=2, r=2, t=2, b=2), height=62,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(
            visible=False, fixedrange=True, range=[min_v - pad, max_v + pad]
        ),
        showlegend=False
    )
    return fig


def _glance_sparkline_svg(series, color="#00E5FF", w=112, h=44):
    """Single SVG path sparkline for glance cards (sidebar-safe; no Plotly iframe)."""
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 2:
        s = pd.Series([0.0, 1.0] if s.empty else [float(s.iloc[0]), float(s.iloc[0]) + 1e-6])
    vals = s.tolist()
    n = len(vals)
    vmin, vmax = min(vals), max(vals)
    pad = max(1e-9, (vmax - vmin) * 0.12)
    lo, hi = vmin - pad, vmax + pad
    span = hi - lo or 1.0
    pts = []
    for i, v in enumerate(vals):
        x = 2 + (i / max(1, n - 1)) * (w - 4)
        y = h - 2 - ((v - lo) / span) * (h - 4)
        pts.append(f"{x:.1f},{y:.1f}")
    d = "M " + " L ".join(pts)
    esc_color = _html_mod.escape(color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" class="glance-spark-svg" aria-hidden="true">'
        f'<path d="{d}" fill="none" stroke="{esc_color}" stroke-width="2.25" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def _glance_metric_card(label, value_html, caption_html, series, line_color):
    """One self-contained glass card: text left, SVG sparkline right (works with sidebar open)."""
    spark = _glance_sparkline_svg(series, line_color)
    return (
        "<div class='tc glass-card glance-card glance-card-whole'>"
        "<div class='glance-row-flex'>"
        "<div class='glance-text-col'>"
        f"<div class='glance-label'>{label}</div>"
        f"{value_html}"
        f"{caption_html}"
        "</div>"
        f"<div class='glance-spark-col'>{spark}</div>"
        "</div></div>"
    )


def _parse_watchlist_string(s):
    """Split user paste (commas, newlines, semicolons) into unique uppercase tickers."""
    if not s:
        return []
    s = str(s).replace("\n", ",").replace(";", ",")
    items, seen = [], set()
    for raw in s.split(","):
        t = raw.strip().upper()
        if t and t not in seen:
            items.append(t)
            seen.add(t)
    return items


# ═════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════

def main():
    cfg = load_config()

    # ── SIDEBAR ──
    with st.sidebar:
        st.markdown("""<div style='text-align:center;padding:20px 0'>
            <h1 style='font-size:1.5rem;background:linear-gradient(135deg,#10b981,#3b82f6);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:800;margin-bottom:4px'>CASHFLOW</h1>
            <p style='color:#64748b;font-size:.65rem;letter-spacing:.15em;text-transform:uppercase'>
            COMMAND CENTER v14.0</p></div>""", unsafe_allow_html=True)
        st.markdown("---")
        st.markdown("#### \U0001f50e Stock & watchlist")
        st.caption(
            "Type symbols in the box, then choose **Select stock to analyze** for the main dashboard. "
            "Reorder the list with the buttons below. Scanner order follows the list when “Custom order” is on."
        )
        # Streamlit forbids mutating session_state[sb_scanner] after the text_area exists.
        if "_sb_scanner_sync" in st.session_state:
            st.session_state["sb_scanner"] = st.session_state.pop("_sb_scanner_sync")
        elif "sb_scanner" not in st.session_state:
            st.session_state["sb_scanner"] = cfg.get("watchlist", DEFAULT_CONFIG["watchlist"])
        scanner_watchlist_raw = st.text_area(
            "Watchlist symbols",
            height=96,
            help="Paste from a spreadsheet, type commas, or put one ticker per line. Saved automatically.",
            key="sb_scanner",
            label_visibility="collapsed",
        )
        watch_items = _parse_watchlist_string(scanner_watchlist_raw)
        scanner_watchlist = ",".join(watch_items)

        if watch_items:
            if "_sb_watch_selected_sync" in st.session_state:
                st.session_state["sb_watch_selected"] = st.session_state.pop("_sb_watch_selected_sync")
            if st.session_state.get("sb_watch_selected") not in watch_items:
                st.session_state["sb_watch_selected"] = watch_items[0]
            selected_ticker = st.selectbox(
                "Select stock to analyze",
                options=watch_items,
                key="sb_watch_selected",
                help="Main chart, news, options, and scores use this ticker. Change anytime from the sidebar.",
            )
        else:
            st.session_state.pop("sb_watch_selected", None)
            st.info("Add at least one symbol in the box above (e.g. PLTR, NVDA).")

        _sort_default = (
            "Custom order"
            if cfg.get("scanner_sort_mode", "Custom watchlist order") == "Custom watchlist order"
            else "Confluence first"
        )
        _scan_seg = st.segmented_control(
            "Scanner order",
            options=["Custom order", "Confluence first"],
            default=_sort_default,
            key="sb_scan_seg",
            help="Custom: follow your list order. Confluence: strongest setups first.",
        )
        if _scan_seg is None:
            _scan_seg = _sort_default
        scanner_sort_mode = (
            "Custom watchlist order" if _scan_seg == "Custom order" else "Highest confluence first"
        )

        if watch_items:
            st.markdown(
                "<div style='font-size:.68rem;color:#94a3b8;margin:0 0 6px 0'>"
                + " · ".join(f"<span class='mono' style='color:#cbd5e1'>{_html_mod.escape(x)}</span>" for x in watch_items)
                + "</div>",
                unsafe_allow_html=True,
            )
            up_clicked = st.button("↑  Move up", use_container_width=True, key="sb_move_up")
            down_clicked = st.button("↓  Move down", use_container_width=True, key="sb_move_down")
            remove_clicked = st.button("✕  Remove symbol", use_container_width=True, key="sb_remove_ticker")
            sort_az = st.button("Sort A–Z", use_container_width=True, key="sb_sort_az")

            if up_clicked and selected_ticker in watch_items:
                idx = watch_items.index(selected_ticker)
                if idx > 0:
                    watch_items[idx - 1], watch_items[idx] = watch_items[idx], watch_items[idx - 1]
                    scanner_watchlist = ",".join(watch_items)
                    st.session_state["_sb_scanner_sync"] = scanner_watchlist
                    st.session_state["_sb_watch_selected_sync"] = selected_ticker
                    cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
                    save_config(cfg)
                    st.rerun()
            if down_clicked and selected_ticker in watch_items:
                idx = watch_items.index(selected_ticker)
                if idx < len(watch_items) - 1:
                    watch_items[idx + 1], watch_items[idx] = watch_items[idx], watch_items[idx + 1]
                    scanner_watchlist = ",".join(watch_items)
                    st.session_state["_sb_scanner_sync"] = scanner_watchlist
                    st.session_state["_sb_watch_selected_sync"] = selected_ticker
                    cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
                    save_config(cfg)
                    st.rerun()
            if remove_clicked and selected_ticker in watch_items:
                watch_items = [t for t in watch_items if t != selected_ticker]
                scanner_watchlist = ",".join(watch_items)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist
                if watch_items:
                    st.session_state["_sb_watch_selected_sync"] = watch_items[0]
                cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
                save_config(cfg)
                st.rerun()
            if sort_az and watch_items:
                watch_items = sorted(watch_items)
                scanner_watchlist = ",".join(watch_items)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist
                sel = st.session_state.get("sb_watch_selected")
                if sel not in watch_items:
                    st.session_state["_sb_watch_selected_sync"] = watch_items[0]
                cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
                save_config(cfg)
                st.rerun()

        if watch_items:
            ticker = selected_ticker
        else:
            ticker = "PLTR"

        st.markdown(
            "<div style='font-size:.72rem;color:#94a3b8;margin:10px 0 2px 0;font-weight:600'>"
            "Quick add (optional)</div>",
            unsafe_allow_html=True,
        )
        if "_sb_add_ticker_clear" in st.session_state:
            st.session_state["sb_add_ticker"] = ""
            st.session_state.pop("_sb_add_ticker_clear", None)
        add_ticker_raw = st.text_input(
            "Symbol",
            placeholder="e.g. AMD — then tap Add below",
            key="sb_add_ticker",
            label_visibility="collapsed",
        )
        add_clicked = st.button("Add symbol", use_container_width=True, key="sb_add_watch")
        add_ticker = (add_ticker_raw or "").strip().upper()
        if add_clicked:
            if add_ticker:
                if add_ticker not in watch_items:
                    watch_items.append(add_ticker)
                scanner_watchlist = ",".join(watch_items)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist
                st.session_state["_sb_watch_selected_sync"] = add_ticker
                st.session_state["_sb_add_ticker_clear"] = True
                cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
                save_config(cfg)
                st.rerun()
            else:
                st.toast("Enter a ticker in the box above, then tap Add symbol.")

        watch_cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
        if watch_cfg != cfg:
            save_config(watch_cfg)
            cfg = watch_cfg

        st.markdown("---")
        st.markdown("#### Strategy")
        st.markdown(
            '<p class="cf-widget-hint">Pick how you think about trades and the typical option window.</p>',
            unsafe_allow_html=True,
        )
        strat_mode = st.segmented_control(
            "Focus",
            options=["Sell premium", "Hybrid", "Growth"],
            default="Hybrid",
            key="sb_strat_seg",
            help="Sell premium: income first. Growth: more directional risk.",
        )
        if strat_mode is None:
            strat_mode = "Hybrid"
        horizon = st.segmented_control(
            "Horizon",
            options=["Weekly", "30 DTE", "45 DTE"],
            default="30 DTE",
            key="sb_horizon_seg",
            help="Rough target days-to-expiration for planning.",
        )
        if horizon is None:
            horizon = "30 DTE"
        st.markdown("---")
        st.markdown("#### Chart overlays")
        st.markdown(
            '<p class="cf-widget-hint">Flip layers on or off — the chart updates immediately.</p>',
            unsafe_allow_html=True,
        )
        o1, o2 = st.columns(2)
        with o1:
            show_ind = st.toggle("EMAs & Bollinger", value=True, key="sb_ema")
            show_gann = st.toggle("Gann Sq9", value=True, key="sb_gann")
            show_ichi = st.toggle("Ichimoku", value=False, key="sb_ichi")
            show_diamonds = st.toggle("Diamonds", value=True, key="sb_diamonds")
        with o2:
            show_fib = st.toggle("Fibonacci", value=True, key="sb_fib")
            show_sr = st.toggle("S/R levels", value=True, key="sb_sr")
            show_super = st.toggle("Supertrend", value=False, key="sb_super")
            show_gold_zone = st.toggle("Gold zone", value=True, key="sb_gold_zone")

        st.markdown("---")

        # Alert settings
        st.markdown("#### WhatsApp Alerts")
        wa_phone = st.text_input("WhatsApp Number", value=cfg.get("whatsapp_phone", ""),
                                  help="Your number with country code, no + (e.g. 13143266122)", key="sb_wa_phone")
        wa_apikey = st.text_input("WhatsApp API Key", value=cfg.get("whatsapp_apikey", ""),
                                   help="Your CallMeBot API key (e.g. 8186573)", key="sb_wa_apikey")
        st.markdown(
            '<p class="cf-widget-hint">Drag to set when WhatsApp should fire (if configured below).</p>',
            unsafe_allow_html=True,
        )
        alert_thresh = st.slider(
            "Alert when Quant Edge ≥",
            50,
            95,
            cfg.get("alert_threshold", 80),
            help="Send alert when the score crosses this threshold.",
            key="sb_alert_thresh",
        )

        # Persist alert settings
        alert_cfg = {**cfg, "whatsapp_phone": wa_phone, "whatsapp_apikey": wa_apikey, "alert_threshold": alert_thresh}
        if alert_cfg != cfg:
            save_config(alert_cfg)
            cfg = alert_cfg

        st.markdown("---")
        st.markdown("<div style='text-align:center;color:#64748b;font-size:.65rem'>Data: Yahoo Finance &middot; Not advice</div>", unsafe_allow_html=True)

    # ── HEADER ──
    st.markdown(f"<h1 style='margin:0;font-size:1.8rem;background:linear-gradient(135deg,#10b981,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent'>{ticker} COMMAND CENTER</h1>", unsafe_allow_html=True)

    # ── FETCH ──
    with st.spinner(f"Loading {ticker}..."):
        df = fetch_stock(ticker, "1y", "1d")
        df_wk = fetch_stock(ticker, "2y", "1wk")
        macro = fetch_macro()
        news = fetch_news(ticker)
        earnings_date_raw = fetch_earnings_date(ticker)

    if df is None or df.empty:
        st.error(f"Data feed unavailable for {ticker}. Yahoo Finance may be throttling or market is closed. Retrying on next refresh...")
        st.stop()

    # ── EARNINGS AMBUSH CHECK ──
    earnings_near = False
    earnings_dt = None
    days_to_earnings = None
    if earnings_date_raw is not None:
        try:
            if isinstance(earnings_date_raw, str):
                earnings_dt = datetime.strptime(earnings_date_raw[:10], "%Y-%m-%d")
            else:
                earnings_dt = pd.Timestamp(earnings_date_raw).to_pydatetime()
            if hasattr(earnings_dt, "tzinfo") and earnings_dt.tzinfo:
                earnings_dt = earnings_dt.replace(tzinfo=None)
            days_to_earnings = (earnings_dt - datetime.now()).days
            if 0 <= days_to_earnings <= 14:
                earnings_near = True
        except Exception:
            earnings_dt = None
            days_to_earnings = None

    if earnings_dt is not None and days_to_earnings is not None:
        if days_to_earnings < 0:
            earn_glance = f"Reported {abs(days_to_earnings)} days ago ({earnings_dt.strftime('%b %d')})"
        elif days_to_earnings == 0:
            earn_glance = "Earnings today"
        else:
            earn_glance = f"{days_to_earnings} days: {earnings_dt.strftime('%b %d, %Y')}"
    else:
        earn_glance = "No date from feed"

    if earnings_near and earnings_dt:
        st.markdown(f"""<div style='background:linear-gradient(135deg,rgba(245,158,11,.15),rgba(217,119,6,.1));
            border:2px solid #f59e0b;border-radius:12px;padding:16px 20px;margin:0 0 16px 0'>
            <span style='font-size:1.1rem;color:#f59e0b;font-weight:700'>⚠️ EARNINGS IN {days_to_earnings} DAYS</span>
            <span style='color:#94a3b8;font-size:.9rem;display:block;margin-top:4px'>
            Option prices are pumped up right now because earnings are coming. This is like a store raising prices before a big sale.
            The risk of getting your shares called away is higher than normal. Auto alerts are paused until after {earnings_dt.strftime('%b %d, %Y')}.</span></div>""", unsafe_allow_html=True)

    price = df["Close"].iloc[-1]
    prev = df["Close"].iloc[-2] if len(df) >= 2 else price
    chg = price - prev; chg_pct = chg/prev*100
    hi52, lo52 = df["High"].max(), df["Low"].min()
    vix_v = macro.get("VIX", {}).get("price", 0)
    qs, qb = quant_edge_score(df, vix_v)

    # ── GLANCE ROW (price, VIX, earnings, quant edge) ──
    vix_disp = f"{vix_v:.1f}" if vix_v else "N/A"
    if vix_v and vix_v > 25:
        vix_mood = "Fear is up. Premiums pay better."
    elif vix_v and vix_v > 18:
        vix_mood = "Balanced mood. Normal premiums."
    elif vix_v:
        vix_mood = "Calm tape. Premiums run thin."
    else:
        vix_mood = "VIX not loaded"
    price_7d_df = fetch_stock(ticker, "1mo", "1d")
    price_spark = price_7d_df["Close"].tail(7) if price_7d_df is not None and not price_7d_df.empty else df["Close"].tail(7)
    vix_7d_df = fetch_stock("^VIX", "1mo", "1d")
    vix_spark = vix_7d_df["Close"].tail(7) if vix_7d_df is not None and not vix_7d_df.empty else pd.Series([vix_v, vix_v, vix_v, vix_v, vix_v, vix_v, vix_v])
    if days_to_earnings is not None:
        earn_anchor = max(1, min(30, days_to_earnings if days_to_earnings >= 0 else 1))
        earnings_spark = pd.Series(np.linspace(earn_anchor + 1, max(0, earn_anchor - 1), 7))
    else:
        earnings_spark = pd.Series(np.linspace(24, 1, 7))
    qe_spark = pd.Series(np.linspace(max(0, qs - 10), min(100, qs + 4), 7))

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.markdown(
            _glance_metric_card(
                f"{_html_mod.escape(ticker)} PRICE",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:#e2e8f0'>${price:.2f}</div>",
                f"<div class='glance-caption'>{chg_pct:+.2f}% vs prior close</div>",
                price_spark,
                "#00E5FF",
            ),
            unsafe_allow_html=True,
        )
    with g2:
        st.markdown(
            _glance_metric_card(
                "MARKET MOOD (VIX)",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:#00E5FF'>{_html_mod.escape(vix_disp)}</div>",
                f"<div class='glance-caption'>{_html_mod.escape(vix_mood)}</div>",
                vix_spark,
                "#FF005C" if vix_v and vix_v > 20 else "#00FFA3",
            ),
            unsafe_allow_html=True,
        )
    with g3:
        st.markdown(
            _glance_metric_card(
                "EARNINGS COUNTDOWN",
                f"<div class='glance-value' style='font-size:1.0rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(earn_glance)}</div>",
                "<div class='glance-caption'>Plan size before the print</div>",
                earnings_spark,
                "#FFD700",
            ),
            unsafe_allow_html=True,
        )
    with g4:
        qe_color = "#00FFA3" if qs > 70 else ("#FFD700" if qs > 50 else "#FF005C")
        st.markdown(
            _glance_metric_card(
                "QUANT EDGE",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:{qe_color}'>{qs:.0f}/100</div>",
                "<div class='glance-caption'>24h directional momentum context</div>",
                qe_spark,
                qe_color,
            ),
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════════════
    #  SHARED COMPUTATIONS
    # ══════════════════════════════════════════════════════════════════
    wk_label, wk_color = weekly_trend_label(df_wk)
    struct, _, _ = TA.market_structure(df)
    fg = Sentiment.fear_greed(df, vix_v)
    fg_label, fg_emoji, fg_advice = Sentiment.interpret(fg)

    ml_v, sl_v, h_v = TA.macd(df["Close"])
    macd_bull = ml_v.iloc[-1] > sl_v.iloc[-1]
    obv_s = TA.obv(df)
    obv_up = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else True
    rsi_v = TA.rsi(df["Close"]).iloc[-1]
    al = Alerts.scan(df, ticker, vix_v)

    # ── DIAMOND / GOLD ZONE / CONFLUENCE ──
    gold_zone_price, gold_zone_components = calc_gold_zone(df, df_wk)
    cp_score, cp_max, cp_breakdown, cp_bearish = calc_confluence_points(df, df_wk, vix_v)
    diamonds = detect_diamonds(df, df_wk) if show_diamonds else []
    latest_d = latest_diamond_status(diamonds)
    d_wr, d_avg, d_n = diamond_win_rate(df, diamonds, forward_bars=10)

    cp_color = "#10b981" if cp_score >= 7 else ("#f59e0b" if cp_score >= 4 else "#ef4444")
    cp_label = "STRONG BULLISH" if cp_score >= 7 else ("BULLISH LEAN" if cp_score >= 5 else ("MIXED" if cp_score >= 3 else "BEARISH"))

    # Multi-timeframe bias
    daily_struct = struct
    weekly_struct = "UNKNOWN"
    if df_wk is not None and len(df_wk) >= 20:
        weekly_struct, _, _ = TA.market_structure(df_wk)

    qs_color = "#10b981" if qs > 70 else ("#f59e0b" if qs > 50 else "#ef4444")
    qs_status = "PRIME SELLING ENVIRONMENT" if qs > 70 else ("DECENT SETUP" if qs > 50 else "CAUTION. WAIT FOR A BETTER ENTRY.")

    # ── EARLY OPTIONS FETCH (populates BLUF with specific strikes) ──
    rfr = macro.get("10Y Yield", {}).get("price", 4.5) / 100
    bluf_cc, bluf_csp, bluf_exp, bluf_dte = None, None, None, 0
    opt_pair, opt_exps = fetch_options(ticker)
    if opt_exps:
        bluf_exp = opt_exps[min(2, len(opt_exps) - 1)]
        bluf_dte = max(1, (datetime.strptime(bluf_exp, "%Y-%m-%d") - datetime.now()).days)
        bluf_opt, _ = fetch_options(ticker, bluf_exp)
        bluf_calls, bluf_puts = bluf_opt
        cc_list = Opt.covered_calls(price, bluf_calls, bluf_dte, rfr)
        csp_list = Opt.cash_secured_puts(price, bluf_puts, bluf_dte, rfr)
        if cc_list:
            bluf_cc = next((c for c in cc_list if c.get("optimal")), cc_list[0])
        if csp_list:
            bluf_csp = next((c for c in csp_list if c.get("optimal")), csp_list[0])

    # ── DETERMINE BEST STRATEGY (example contract counts — no personal position data) ──
    nc = 1
    if struct == "BULLISH" and fg > 50:
        action_strat = "SELL COVERED CALLS"
        action_plain = (
            f"If you hold at least 100 shares, sell {nc} covered call contract(s) above the current price. "
            f"You collect premium today. If {ticker} stays below the strike by expiration, you keep the cash and your shares."
        )
    elif fg < 35:
        action_strat = "SELL CASH SECURED PUTS"
        action_plain = (
            f"The market is scared right now (fear score: {fg:.0f}). Buyers pay more for protection. "
            f"Sell cash-secured puts below the price. If assigned, you buy {ticker} at your strike."
        )
    elif struct != "BEARISH":
        action_strat = "BULL PUT SPREAD"
        action_plain = "Define-risk credit spread: collect premium with a capped max loss."
    else:
        action_strat = "BEAR CALL SPREAD"
        action_plain = "Define-risk credit spread when the tape is heavy — cap upside risk."

    # ── RECOMMENDED TRADE (optimal strike from options engine) ──
    master_kind, master_b = None, None
    if opt_exps and bluf_exp:
        br = struct in ("BULLISH", "RANGING")
        if br and bluf_cc:
            master_kind, master_b = "cc", bluf_cc
        elif br and bluf_csp:
            master_kind, master_b = "csp", bluf_csp
        elif bluf_csp:
            master_kind, master_b = "csp", bluf_csp
        elif bluf_cc:
            master_kind, master_b = "cc", bluf_cc

    master_html = ""
    if master_kind and master_b and bluf_exp:
        exp_disp = datetime.strptime(bluf_exp, "%Y-%m-%d").strftime("%B %d").upper()
        dte_m = max(1, (datetime.strptime(bluf_exp, "%Y-%m-%d") - datetime.now()).days)
        pop_pct = int(min(92, max(55, round((1.0 - abs(master_b["delta"])) * 100))))
        tk_esc = _html_mod.escape(ticker)
        if master_kind == "cc":
            n_c = nc
            prem_tot = master_b["prem_100"] * n_c
            headline = (
                f"SELL {n_c}x {tk_esc} ${master_b['strike']:.0f} CALLS EXP {exp_disp}. "
                f"COLLECT ${prem_tot:,.0f} CASH TODAY. {pop_pct} PERCENT PROBABILITY OF KEEPING SHARES."
            )
            rh_steps = [
                f"In your broker app, open {ticker} and go to options.",
                f"Choose expiration {bluf_exp} ({dte_m} days out).",
                f"Sell {n_c}x ${master_b['strike']:.0f} call(s) near mid, then confirm the order.",
            ]
        else:
            prem_tot = master_b["prem_100"]
            headline = (
                f"SELL 1x {tk_esc} ${master_b['strike']:.0f} PUTS EXP {exp_disp}. "
                f"COLLECT ${prem_tot:,.0f} CASH TODAY. {pop_pct} PERCENT ODDS OPTION EXPIRES WORTHLESS IF PRICE STAYS ABOVE THE STRIKE."
            )
            rh_steps = [
                f"In your broker app, open {ticker} and go to options.",
                f"Choose expiration {bluf_exp} ({dte_m} days out).",
                f"Sell 1x ${master_b['strike']:.0f} put near mid, then confirm the order.",
            ]
        stepper = "".join(
            f"<div class='rh-step'><div class='num'>{i}.</div><div class='txt'>{_html_mod.escape(s)}</div></div>"
            for i, s in enumerate(rh_steps, start=1)
        )
        strike_s = f"{master_b['strike']:.0f}"
        master_html = (
            f"<div class='trade-master'>"
            f"<div style='font-size:.72rem;font-weight:800;color:#00e5ff;letter-spacing:.2em;margin-bottom:8px'>PRIMARY MISSION OBJECTIVE</div>"
            f"<p style='color:#e2e8f0;font-size:1.05rem;line-height:1.55;margin:0 0 14px 0;font-weight:600'>{headline}</p>"
            f"<div class='strike-big' style='margin:8px 0 6px 0'>${_html_mod.escape(strike_s)}</div>"
            f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px'>Prop desk optimal strike · IV {master_b['iv']:.1f}% · dte {dte_m}</div>"
            f"<div style='font-size:.75rem;font-weight:700;color:#a5f3fc;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px'>Broker checklist</div>"
            f"<div class='rh-stepper'>{stepper}</div>"
            f"<p style='color:#64748b;font-size:.78rem;margin:14px 0 0 0'>Quotes can lag. Confirm credit in the app before you send the order.</p>"
            f"</div>"
        )
    elif not opt_exps:
        master_html = (
            "<div class='trade-master'>"
            "<div style='font-size:.72rem;font-weight:800;color:#00e5ff;letter-spacing:.2em;margin-bottom:8px'>PRIMARY MISSION OBJECTIVE</div>"
            "<p style='color:#e2e8f0;font-size:1rem;margin:0'>Options chain is offline right now. Retry after the market opens or scroll to Cash Flow Strategies.</p>"
            "</div>"
        )
    else:
        master_html = (
            "<div class='trade-master'>"
            "<div style='font-size:.72rem;font-weight:800;color:#00e5ff;letter-spacing:.2em;margin-bottom:8px'>PRIMARY MISSION OBJECTIVE</div>"
            "<p style='color:#e2e8f0;font-size:1rem;margin:0'>No liquid optimal strike passed our filters yet. Open Cash Flow Strategies and pick an expiration manually.</p>"
            "</div>"
        )

    # Build diamond status badge HTML
    d_badge_html = ""
    if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
        if latest_d["type"] == "blue":
            d_badge_html = f"<span class='diamond-badge badge-blue'>🔷 BLUE DIAMOND ACTIVE</span>"
        else:
            d_badge_html = f"<span class='diamond-badge badge-pink'>💎 PINK DIAMOND: TAKE PROFIT</span>"
    else:
        d_badge_html = "<span class='diamond-badge badge-none'>◇ No Active Diamond</span>"

    # Confluence bar segments HTML
    cp_bar_html = ""
    for i in range(cp_max):
        filled = i < cp_score
        color = "#10b981" if filled and cp_score >= 7 else ("#f59e0b" if filled and cp_score >= 4 else ("#ef4444" if filled else "#1e293b"))
        cp_bar_html += f"<div style='flex:1;height:10px;background:{color};border-radius:5px;margin:0 1px'></div>"

    gz_gap_pct = ((price / gold_zone_price - 1) * 100) if gold_zone_price else 0.0
    bluf_html = f"""<div class='bluf'>
        <div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px'>
            <div>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{qs_color}'>{qs:.0f}</span>
                <span style='color:{qs_color};font-size:.9rem;margin-left:8px'>{qs_status}</span>
            </div>
            <div style='text-align:center'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>CONFLUENCE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{cp_color}'>{cp_score}/{cp_max}</span>
                <span style='color:{cp_color};font-size:.9rem;display:block'>{cp_label}</span>
                <div style='display:flex;gap:2px;margin-top:6px;width:160px'>{cp_bar_html}</div>
            </div>
            <div style='text-align:right'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>WEEKLY TREND</div>
                <span style='font-size:1.2rem;font-weight:700;color:{wk_color}'>{wk_label}</span>
                <div style='margin-top:8px'>{d_badge_html}</div>
            </div>
        </div>
        <div style='display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;border-top:1px solid rgba(255,255,255,.06);padding-top:12px'>
            <div style='flex:1;min-width:250px'>
                <div style='font-size:.7rem;color:{"#eab308" if show_gold_zone else "#64748b"};text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px'>⬥ GOLD ZONE</div>
                <span class='mono' style='font-size:1.3rem;font-weight:700;color:#fbbf24'>${gold_zone_price:.2f}</span>
                <span style='color:#94a3b8;font-size:.8rem;margin-left:8px'>({gz_gap_pct:+.1f}% away)</span>
            </div>
            <div style='flex:1;min-width:250px'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px'>MULTI-TF BIAS</div>
                <span style='font-size:.85rem;color:{"#10b981" if daily_struct=="BULLISH" else ("#ef4444" if daily_struct=="BEARISH" else "#f59e0b")}'>Daily: {daily_struct}</span>
                <span style='margin:0 8px;color:#334155'>|</span>
                <span style='font-size:.85rem;color:{"#10b981" if weekly_struct=="BULLISH" else ("#ef4444" if weekly_struct=="BEARISH" else "#f59e0b")}'>Weekly: {weekly_struct}</span>
                <div style='margin-top:8px;font-size:.78rem;color:#64748b'>52 week: <span class='mono' style='color:#94a3b8'>${hi52:.2f}</span> high · <span class='mono' style='color:#94a3b8'>${lo52:.2f}</span> low</div>
            </div>
        </div>
        <div style='display:flex;gap:24px;flex-wrap:wrap;margin-top:14px;border-top:1px solid rgba(255,255,255,.06);padding-top:12px'>
            <div><span class='tl' style='background:{"#10b981" if macd_bull else "#ef4444"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Momentum: <strong style="color:#e2e8f0">{"Buyers are in control" if macd_bull else "Sellers are gaining ground"}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if obv_up else "#ef4444"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Volume: <strong style="color:#e2e8f0">{"Big money is buying" if obv_up else "Big money is selling"}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if vix_v and vix_v > 20 else "#f59e0b"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Premiums: <strong style="color:#e2e8f0">{"Huge. Fear is high." if vix_v and vix_v > 25 else ("Normal range" if vix_v and vix_v > 18 else "Thin. Market is too calm.")}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if 35 < rsi_v < 65 else "#f59e0b"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>RSI: <strong style="color:#e2e8f0">{rsi_v:.0f}. {"Perfect zone for selling" if 35 < rsi_v < 65 else ("Stock ran too fast" if rsi_v > 65 else "Stock dropped too fast")}</strong></span></div>
        </div>
    </div>"""

    # ══════════════════════════════════════════════════════════════════
    #  EXECUTION STRIP (aligned mission + context)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="execution" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    st.markdown(
        f"<div class='execution-shell'><div class='execution-col'>{master_html}</div><div class='execution-col'>{bluf_html}</div></div>",
        unsafe_allow_html=True
    )

    # ══════════════════════════════════════════════════════════════════
    #  PLTR EARNINGS INTELLIGENCE (Palantir-specific — only when PLTR is the dashboard symbol)
    # ══════════════════════════════════════════════════════════════════
    if ticker == "PLTR":
        next_print = datetime(2026, 5, 4)
        d_to_print = (next_print.date() - datetime.now().date()).days
        if d_to_print > 0:
            countdown_txt = f"{d_to_print} days to earnings ({next_print.strftime('%b %d, %Y')})"
        elif d_to_print == 0:
            countdown_txt = "Earnings expected today (May 04, 2026)"
        else:
            countdown_txt = f"Last projected print date passed by {abs(d_to_print)} days (May 04, 2026)"
        with st.expander("📊 STRATEGIC INTELLIGENCE: Q4 2025 / 2026 OUTLOOK", expanded=True):
            gc, bc = st.columns(2)
            with gc:
                st.markdown(
                    """
                    <div class='earn-col earn-good'>
                        <h4>THE GOOD (THE CATALYST)</h4>
                        <ul>
                            <li><strong>Hyper-Growth:</strong> Q4 2025 revenue grew 70% Y/Y to $1.41B. U.S. Commercial surged 137%.</li>
                            <li><strong>Rule of 40:</strong> Palantir is operating at an elite Rule of 40 score of 127%.</li>
                            <li><strong>2026 Guidance:</strong> Management guided to roughly 61% Y/Y growth with a $7.2B target.</li>
                            <li><strong>Profitability:</strong> GAAP Net Income reached $609M (43% margin); FCF hit $791M.</li>
                        </ul>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            with bc:
                st.markdown(
                    f"""
                    <div class='earn-col earn-bad'>
                        <h4>THE BAD (THE RISK)</h4>
                        <ul>
                            <li><strong>Valuation:</strong> Trading at about 125x-248x P/E, priced for near-perfection.</li>
                            <li><strong>International Lag:</strong> U.S. commercial +137% vs international commercial +2%.</li>
                            <li><strong>SBC &amp; Dilution:</strong> Heavy stock-based compensation remains a key bear argument.</li>
                            <li><strong>Upcoming Print:</strong> {countdown_txt}. Street EPS projection is $0.26-$0.29.</li>
                        </ul>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            st.markdown(
                """
                <div class='earn-meta'>
                    <span class='earn-pill'>Q4 2025 Revenue: $1.41B</span>
                    <span class='earn-pill'>U.S. Commercial: +137% Y/Y</span>
                    <span class='earn-pill'>2026 Guide: $7.2B</span>
                    <span class='earn-pill'>Projected EPS: $0.26-$0.29</span>
                </div>
                """,
                unsafe_allow_html=True
            )

    # ── ALERTS BAR ──
    hi_al = [a for a in al if a["p"] == "HIGH"]
    if hi_al:
        st.markdown(f"<div class='ac'>\U0001f514 <strong>{len(al)} Alert{'s' if len(al) > 1 else ''}</strong>: {hi_al[0]['m']}{'<em> +' + str(len(al) - 1) + ' more</em>' if len(al) > 1 else ''}</div>", unsafe_allow_html=True)

    # ── SEND PUSH ALERTS (persistent — survives page refresh) ──
    today_str = datetime.now().strftime("%Y-%m-%d")
    already_alerted = cfg.get("last_alert_date") == today_str
    if qs >= alert_thresh and not already_alerted and not earnings_near:
        alert_msg = f"CASHFLOW ALERT: {ticker} Quant Edge {qs:.0f}/100. {action_strat}\n{action_plain}\nPrice: ${price:.2f} VIX {vix_v:.1f}"
        sent = False
        if wa_phone and wa_apikey:
            sent = send_whatsapp_alert(wa_phone, wa_apikey, alert_msg)
        if sent:
            cfg["last_alert_date"] = today_str
            save_config(cfg)
            st.toast(f"WhatsApp alert sent! QE={qs:.0f} for {ticker}")
    elif earnings_near and qs >= alert_thresh:
        st.toast(f"Alert paused. Earnings within 14 days for {ticker}.")

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 1 \u2014 TECHNICAL CHART (always visible)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="charts" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Technical Chart", f"See exactly what {ticker} is doing right now. Price, volume, momentum, and Diamond Signals in one view.",
             tip_plain="Candles show each day. EMAs show trend. Blue Diamonds mark high confluence bullish bursts. Pink Diamonds mark exhaustion. Gold line is the Gold Zone. Volume shows participation. RSI shows heat. MACD shows momentum handoff.")
    fig = build_chart(df, ticker, show_ind, show_fib, show_gann, show_sr, show_ichi, show_super,
                      diamonds=diamonds if show_diamonds else None,
                      gold_zone=gold_zone_price if show_gold_zone else None)
    st.plotly_chart(fig, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    chart_mood = "bull" if struct == "BULLISH" else ("bear" if struct == "BEARISH" else "neutral")

    # ── DIAMOND SIGNAL CARDS (below chart) ──
    if show_diamonds and diamonds:
        recent_diamonds = [d for d in diamonds if (df.index[-1] - d["date"]).days <= 30]
        if recent_diamonds:
            st.markdown("#### Recent Diamond Signals")
            d_cols = st.columns(min(len(recent_diamonds), 4))
            for idx_d, d in enumerate(recent_diamonds[-4:]):
                with d_cols[idx_d]:
                    cls = "diamond-blue" if d["type"] == "blue" else "diamond-pink"
                    icon = "🔷" if d["type"] == "blue" else "💎"
                    label = "BLUE DIAMOND: Strong Buy" if d["type"] == "blue" else "PINK DIAMOND: Take Profit"
                    age = (df.index[-1] - d["date"]).days
                    prob_txt = f"Historical win rate: {d_wr:.0f}% over {d_n} signals" if d_n > 0 else "Insufficient history"
                    st.markdown(f"<div class='{cls}'>"
                        f"<div style='font-size:1.1rem;font-weight:700;margin-bottom:4px'>{icon} {label}</div>"
                        f"<div style='color:#94a3b8;font-size:.85rem'>Date: {d['date'].strftime('%b %d, %Y')} ({age}d ago)<br>"
                        f"Price: ${d['price']:.2f} | Score: {d['score']}/9 | RSI: {d['rsi']:.0f}<br>"
                        f"<span style='color:#fbbf24;font-size:.8rem'>📊 {prob_txt}</span></div></div>",
                        unsafe_allow_html=True)

            if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
                why_type = "BLUE DIAMOND" if latest_d["type"] == "blue" else "PINK DIAMOND"
                why_color = "#3b82f6" if latest_d["type"] == "blue" else "#ec4899"
                why_action = (
                    "Strong confluence aligned bullish. The market gave a high probability buy signal."
                    if latest_d["type"] == "blue"
                    else "Confluence collapsed or momentum exhausted. Time to protect gains."
                )
                flabels = _factor_checklist_labels()
                factor_lines = ""
                passed = 0
                for key, nice in flabels.items():
                    info = cp_breakdown.get(key)
                    if not info:
                        continue
                    ok = info["pts"] > 0
                    if ok:
                        passed += 1
                    mark = "&#10003;" if ok else ""
                    row_col = "#34d399" if ok else "#64748b"
                    factor_lines += (
                        f"<div style='padding:5px 0;display:flex;align-items:flex-start;gap:10px;color:{row_col};font-size:.9rem'>"
                        f"<span style='color:#34d399;font-weight:800;min-width:1.2em'>{mark}</span>"
                        f"<span><strong style='color:#e2e8f0'>{nice}</strong>"
                        f"<span style='color:#64748b;font-size:.8rem'> ({info['pts']}/{info['max']})</span></span></div>"
                    )
                wk_confirm = latest_d.get("weekly", "N/A")
                win_badge = (
                    f"<div style='margin:12px 0 8px 0'><span class='diamond-win-badge'>HISTORICAL WIN RATE: {d_wr:.0f}%</span>"
                    f"<span style='color:#94a3b8;font-size:.8rem;margin-left:10px'>({d_n} past signals)</span></div>"
                    if d_n > 0
                    else "<div style='color:#64748b;font-size:.85rem;margin:8px 0'>Not enough history for a win rate badge yet.</div>"
                )
                st.markdown(
                    f"<div style='background:rgba(15,23,42,.95);border:1px solid {why_color};border-radius:12px;padding:18px 20px;margin:12px 0'>"
                    f"<div style='font-size:.8rem;color:{why_color};text-transform:uppercase;letter-spacing:.1em;font-weight:700;margin-bottom:6px'>"
                    f"Why This {why_type}?</div>"
                    f"<div style='color:#e2e8f0;font-size:.95rem;margin-bottom:6px'>Signal fired at <strong>{latest_d['score']}/9</strong> confluence. "
                    f"Live checklist now shows <strong>{passed}/7</strong> headline factors green.</div>"
                    f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px;line-height:1.5'>{why_action}</div>"
                    f"{win_badge}"
                    f"<div style='font-size:.72rem;color:#64748b;text-transform:uppercase;margin-bottom:6px'>Diamond checklist</div>"
                    f"<div>{factor_lines}</div>"
                    f"<div style='margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,.06);font-size:.8rem;color:#94a3b8'>"
                    f"Weekly filter at signal: <strong style='color:{why_color}'>{wk_confirm}</strong>. "
                    f"RSI at signal: {latest_d['rsi']:.0f}.</div></div>",
                    unsafe_allow_html=True)

    # Gold Zone components breakdown
    if show_gold_zone:
        show_gz_detail = st.checkbox("Show Gold Zone Breakdown", value=False, key="chk_gold_zone_detail")
        if show_gz_detail:
            st.markdown(f"**Gold Zone Price: ${gold_zone_price:.2f}**. This is the weighted average of multiple key levels that institutional traders watch.")
            for comp_name, comp_val in gold_zone_components.items():
                dist = (comp_val / price - 1) * 100
                st.markdown(f"- **{comp_name}**: ${comp_val:.2f} ({dist:+.1f}% from current)")
            _explain("Why the Gold Zone matters",
                "The Gold Zone combines four of the strongest support/resistance signals into one level: "
                "Volume Profile POC (where the most shares traded), the 61.8% Fibonacci golden ratio, "
                "the nearest Gann Square of 9 natural level, and weekly support/resistance. "
                "When price is ABOVE the Gold Zone, bulls are in control. When it drops below, be cautious. "
                "This is the single most important price level on the chart.", "neutral")

    # Alert suggestion
    if latest_d and latest_d["type"] == "blue" and (df.index[-1] - latest_d["date"]).days <= 3:
        next_gz = gold_zone_price
        st.markdown(f"<div class='ac'>🔔 <strong>Alert Suggestion:</strong> Set an alert for next Blue Diamond at <strong>${next_gz:.2f}</strong> (Gold Zone). "
            f"If {ticker} pulls back to the Gold Zone and confluence rebuilds above 7/9, that is your next high probability entry.</div>", unsafe_allow_html=True)
    elif latest_d and latest_d["type"] == "pink" and (df.index[-1] - latest_d["date"]).days <= 3:
        st.markdown(f"<div class='ac'>🔔 <strong>Alert Suggestion:</strong> Pink Diamond fired at ${latest_d['price']:.2f}. "
            f"Consider taking partial profits. Set alert if {ticker} drops below Gold Zone ${gold_zone_price:.2f} for a full exit.</div>", unsafe_allow_html=True)

    _explain("\U0001f9e0 Quick read",
        "Hover the <strong>i</strong> icon in the section title above for the full tour. "
        "Bottom line: green candles and a rising short EMA mean buyers lead. Diamonds and Gold Zone are your institutional style GPS.",
        chart_mood)

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 2 \u2014 SETUP ANALYSIS
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="setup" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Setup Analysis", "Is the stock trending up, down, or sideways? Here is the answer and what to do about it.",
             tip_plain="This block tells you trend state fast. Trending up means lean into premium selling with room above price. Sideways means harvest both sides carefully. Downtrend means tighten risk and reduce size.")
    sa_left, sa_right = st.columns(2)
    with sa_left:
        cls = "sb" if struct == "BULLISH" else ("sr" if struct == "BEARISH" else "sn")
        st.markdown(f"<div class='{cls}'><strong>Market Structure: {struct}</strong></div>", unsafe_allow_html=True)
        struct_explain = {
            "BULLISH": "The stock is making higher highs and higher lows. Think of a store where sales grow every single quarter. The trend is your friend. Sell covered calls at the highs to collect rent on your shares.",
            "BEARISH": "The stock is making lower highs and lower lows. Think of a store where foot traffic drops every month. Be careful. Widen your safety buffers or wait for the bottom before selling options.",
            "RANGING": "The stock is bouncing between a ceiling and a floor. Think of a business in a steady market. This is actually great for selling options on both sides and collecting cash."}
        _explain("Why this matters for your trade", struct_explain[struct], chart_mood)

        # Hurst Exponent — market regime filter
        hurst_val = TA.hurst(df["Close"])
        if hurst_val > 0.55:
            h_label, h_color = "TRENDING", "#10b981"
        elif hurst_val < 0.45:
            h_label, h_color = "MEAN REVERTING", "#8b5cf6"
        else:
            h_label, h_color = "RANDOM WALK", "#f59e0b"
        st.markdown(f"<div class='tc' style='text-align:center;margin-bottom:12px'>"
            f"<div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Hurst Exponent (R/S)</div>"
            f"<div class='mono' style='font-size:1.3rem;color:{h_color}'>{hurst_val:.3f} = {h_label}</div></div>", unsafe_allow_html=True)
        if 0.45 <= hurst_val <= 0.55:
            _explain("\u26a0\ufe0f Random Walk Warning",
                f"Hurst is {hurst_val:.3f}. That means the price is moving randomly right now. Like flipping a coin. "
                "Trend tools like Supertrend, ADX, and MACD are not reliable when this happens. "
                "Your best move is to wait for a clear direction or use strategies that profit from sideways movement.", "bear")
        elif hurst_val > 0.55:
            _explain("Hurst says: Trending Market",
                f"Hurst is {hurst_val:.3f}. The stock has strong trending behavior. Whatever direction it is going, it is likely to keep going. "
                "Think of a business with sales growing every quarter. You can trust the trend. "
                "Trend tools like Supertrend and MACD are working correctly right now.", "bull")
        else:
            _explain("Hurst says: Prices Snap Back",
                f"Hurst is {hurst_val:.3f}. Prices are snapping back to the average faster than normal. "
                "Big moves tend to reverse quickly. This is perfect for selling options at extremes. "
                "You collect the premium and the stock comes back to you. Time decay works in your favor.", "bull")

        st.markdown(f"""<div class='qe'>
            <div style='font-size:.75rem;color:#8b5cf6;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE SCORE</div>
            <div style='font-size:3rem;font-weight:800;color:{qs_color};font-family:JetBrains Mono,monospace'>{qs:.0f}</div>
            <div style='font-size:.85rem;color:#94a3b8'>Your overall score from 5 independent checks</div></div>""", unsafe_allow_html=True)
        for k, v in qb.items():
            clr = "#10b981" if v > 70 else ("#f59e0b" if v > 50 else "#ef4444")
            st.markdown(f"<div style='display:flex;align-items:center;margin:3px 0'><span style='width:85px;color:#94a3b8;font-size:.8rem;text-transform:capitalize'>{k}</span><div style='flex:1;background:#1e293b;border-radius:4px;height:7px;margin:0 8px'><div style='width:{v}%;background:{clr};border-radius:4px;height:7px'></div></div><span class='mono' style='color:#e2e8f0;font-size:.8rem'>{v:.0f}</span></div>", unsafe_allow_html=True)

        # ── CONFLUENCE POINTS (0-9 visual meter) ──
        st.markdown(f"""<div class='confluence-meter' style='margin-top:16px'>
            <div style='font-size:.75rem;color:{cp_color};text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px'>💎 CONFLUENCE POINTS</div>
            <div style='font-size:2.2rem;font-weight:800;color:{cp_color};font-family:JetBrains Mono,monospace'>{cp_score}/{cp_max} {cp_label}</div>
            <div style='font-size:.8rem;color:#94a3b8;margin-top:2px'>{"🔷 Blue Diamond territory: strong buy signal active" if cp_score >= 7 else ("Approaching diamond zone: watch closely" if cp_score >= 5 else "Not enough confluence for a diamond signal")}</div>
        </div>""", unsafe_allow_html=True)
        for comp_name, comp_data in cp_breakdown.items():
            pts = comp_data["pts"]
            mx = comp_data["max"]
            detail = comp_data["detail"]
            bar_pct = (pts / mx * 100) if mx > 0 else 0
            clr = "#10b981" if pts == mx else ("#f59e0b" if pts > 0 else "#334155")
            st.markdown(f"<div style='display:flex;align-items:center;margin:3px 0'>"
                f"<span style='width:95px;color:#94a3b8;font-size:.78rem'>{comp_name}</span>"
                f"<div style='flex:1;background:#1e293b;border-radius:4px;height:7px;margin:0 8px'>"
                f"<div style='width:{bar_pct}%;background:{clr};border-radius:4px;height:7px'></div></div>"
                f"<span class='mono' style='color:#e2e8f0;font-size:.78rem;width:30px;text-align:right'>{pts}/{mx}</span>"
                f"<span style='color:#64748b;font-size:.72rem;margin-left:8px;width:120px'>{detail}</span></div>",
                unsafe_allow_html=True)

    with sa_right:
        st.markdown("**Key Price Levels**")
        if len(df) >= 50:
            rec = df.iloc[-60:]
            fl = TA.fib_retracement(rec["High"].max(), rec["Low"].min())
            st.dataframe(pd.DataFrame([{"Level": k, "Price": f"${v:.2f}", "Dist": f"{(v / price - 1) * 100:+.1f}%"} for k, v in fl.items()]), width="stretch", hide_index=True)
        _explain("What are Fibonacci levels?",
            "After a big move, stocks tend to pull back to specific levels before continuing. The key levels are 38.2%, 50%, and 61.8%. "
            "The 61.8% level is called the golden ratio. It is the most watched level by professional traders. "
            "Why you care: set your put strikes near Fibonacci support. You collect cash AND you buy at a natural price floor.", "neutral")
        if st.checkbox("Gann Square of 9", key="exp_1"):
            gl = TA.gann_sq9(price)
            st.dataframe(pd.DataFrame([{"Level": k, "Price": f"${v:.2f}", "Dist": f"{(v / price - 1) * 100:+.1f}%"} for k, v in gl.items()]), width="stretch", hide_index=True)
        if st.checkbox("Gann Angles", key="exp_2"):
            ang, sp = TA.gann_angles(df)
            st.markdown(f"**Swing Low:** ${sp:.2f}")
            for n_g, p_v in ang.items():
                st.markdown(f"- **{n_g}** -> ${p_v:.2f} ({(p_v / price - 1) * 100:+.1f}%)")
        if st.checkbox("Gann Time Cycles", key="exp_3"):
            for cyc in TA.gann_time_cycles(df):
                st.markdown(f"- **{cyc['cycle']}-bar** -> {cyc['date'].strftime('%Y-%m-%d')} ({cyc['status']})")

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 3 \u2014 QUANT DASHBOARD (two-column: metric + explanation)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="quant-dashboard" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Quant Dashboard", "Every number explained in plain English. What it means. What to do.",
             tip_plain="Use this as your instrument panel. Green bars confirm edge. Weak bars mean do less. Confluence and Gold Zone are the two numbers to trust first.")
    rv2 = TA.rsi2(df["Close"]).iloc[-1] if len(df) > 5 else 50
    adx_v, dip, din = TA.adx(df)
    cci_v = TA.cci(df).iloc[-1]
    st_l, st_d = TA.supertrend(df)
    _, kj, sa_ich, sb_ich, _ = TA.ichimoku(df)
    an = adx_v.iloc[-1] if not pd.isna(adx_v.iloc[-1]) else 0

    # RSI
    il, ir = st.columns([1, 2])
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>RSI (14)</div><div class='mono' style='font-size:1.5rem;color:{'#ef4444' if rsi_v > 70 else ('#10b981' if rsi_v < 30 else '#e2e8f0')}'>{rsi_v:.1f}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>RSI-2: {rv2:.1f}</div></div>", unsafe_allow_html=True)
    with ir:
        if rsi_v > 70:
            _explain("RSI: Stock is Overheated", f"RSI is {rsi_v:.0f}. The stock ran up too fast. Think of a product flying off shelves after a viral review. Buyers are overpaying right now. This is the ideal time to sell Covered Calls and collect cash at peak excitement.", "bear")
        elif rsi_v < 30:
            _explain("RSI: Stock is On Sale", f"RSI is {rsi_v:.0f}. Sellers have panicked. Think of a clearance sale that went too deep. This is your signal to sell Cash Secured Puts. You get paid cash today and you might buy shares at a bargain price.", "bull")
        else:
            _explain("RSI: Stock is Resting", f"RSI is {rsi_v:.0f}. The stock is calm. Buyers are not panicking. Sellers are not panicking. This is the perfect zone to collect cash from selling options.", "neutral")

    # MACD
    il, ir = st.columns([1, 2])
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>MACD</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if macd_bull else '#ef4444'}'>{'BULLISH' if macd_bull else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Hist: {h_v.iloc[-1]:.3f}</div></div>", unsafe_allow_html=True)
    with ir:
        if macd_bull:
            _explain("MACD: Buyers Are Winning", "Recent momentum is stronger than the longer term average. Think of a store where this month's sales beat the quarterly average. Buyers are in charge. You can sell Covered Calls at higher strikes with more confidence.", "bull")
        else:
            _explain("MACD: Sellers Are Winning", "Recent momentum dropped below the longer term average. Think of a store where this month's sales fell below the quarterly trend. Be more careful when picking your strike prices.", "bear")

    # ADX
    il, ir = st.columns([1, 2])
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>ADX</div><div class='mono' style='font-size:1.5rem;color:{'#10b981' if an > 25 else '#f59e0b'}'>{an:.1f}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>+DI: {dip.iloc[-1]:.1f} | -DI: {din.iloc[-1]:.1f}</div></div>", unsafe_allow_html=True)
    with ir:
        di_w = "Buyers (+DI)" if dip.iloc[-1] > din.iloc[-1] else "Sellers ( DI)"
        if an > 25:
            _explain("ADX: Strong Trend Detected", f"ADX is {an:.0f}. That is above 25 which means a strong trend is happening. The winner right now is: {di_w}. Think of a business with a clear growth direction. Sell your options in the direction of the trend for the safest play.", "bull" if dip.iloc[-1] > din.iloc[-1] else "bear")
        else:
            _explain("ADX: No Clear Trend", f"ADX is {an:.0f}. That is below 25 which means the market has no clear direction right now. Think of a business in a holding pattern. This is a good time for strategies that profit from sideways movement.", "neutral")

    # CCI + Supertrend row
    il, ir = st.columns([1, 2])
    stb = st_d.iloc[-1] == 1
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>CCI (20)</div><div class='mono' style='font-size:1.5rem;color:{'#ef4444' if not pd.isna(cci_v) and cci_v > 100 else ('#10b981' if not pd.isna(cci_v) and cci_v < -100 else '#e2e8f0')}'>{cci_v:.0f}</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='tc' style='text-align:center;margin-top:8px'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Supertrend</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if stb else '#ef4444'}'>{'BULLISH' if stb else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>${st_l.iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
    with ir:
        cci_txt = f"CCI is {cci_v:.0f}. " + ("That is above +100. The stock is trading way above its average price. Buyers are overheating. Great time to sell calls and collect premium. " if not pd.isna(cci_v) and cci_v > 100 else ("That is below  100. The stock has been beaten down below its average price. Sellers went too far. Look for put selling opportunities. " if not pd.isna(cci_v) and cci_v < -100 else "That is in the normal zone. No extreme to exploit right now. "))
        st_price = st_l.iloc[-1]
        st_txt = f"The Supertrend is your price floor. It is BULLISH at ${st_price:.2f}. As long as the stock stays above this green line, your shares are safe." if stb else f"The Supertrend is BEARISH at ${st_price:.2f}. It is acting as a falling ceiling above the price. The trend is down. Be defensive and protect your shares."
        _explain("CCI and Supertrend", cci_txt + st_txt, "bull" if stb else "bear")

    # Ichimoku + OBV row
    above_cloud = not pd.isna(sa_ich.iloc[-1]) and not pd.isna(sb_ich.iloc[-1]) and price > max(sa_ich.iloc[-1], sb_ich.iloc[-1])
    ou = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else True
    il, ir = st.columns([1, 2])
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Ichimoku</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if above_cloud else '#ef4444'}'>{'ABOVE CLOUD' if above_cloud else 'IN/BELOW'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Kijun: ${kj.iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='tc' style='text-align:center;margin-top:8px'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>OBV</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if ou else '#ef4444'}'>{'RISING' if ou else 'FALLING'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>{'Accumulation' if ou else 'Distribution'}</div></div>", unsafe_allow_html=True)
    with ir:
        ich_txt = "The price is above the Ichimoku Cloud. The cloud acts as a thick safety net below the stock. When the price floats above it, the trend is strongly in your favor. Your shares are protected. " if above_cloud else "The price is inside or below the cloud. The trend is unclear right now. Think of it like driving through fog. Wait for visibility before you sell options aggressively. "
        obv_txt = "OBV is rising. Big institutional players are quietly buying up shares. Think of your biggest wholesale customers stocking up before a price increase. That is a bullish sign. " if ou else "OBV is falling. Big money is selling into rallies. Think of your best customers reducing their orders. The price may follow them down. Be careful. "
        _explain("Ichimoku Cloud and Volume Flow", ich_txt + obv_txt, "bull" if above_cloud and ou else ("bear" if not above_cloud and not ou else "neutral"))

    # Divergence Scanner
    st.markdown("#### Divergence Scanner")
    rsi_s = TA.rsi(df["Close"])
    divs_rsi = TA.detect_divergences(df["Close"], rsi_s)
    obv_divs = TA.detect_divergences(df["Close"], obv_s)
    all_divs = [(d, "RSI") for d in divs_rsi] + [(d, "OBV") for d in obv_divs]
    if all_divs:
        for d, src in all_divs[-5:]:
            st.markdown(f"<div class='ac'>{'🟢' if d['type'] == 'bullish' else '🔴'} <strong>{d['type'].title()} {src} divergence</strong> near ${d['price']:.2f} on {d['idx'].strftime('%Y-%m-%d')}</div>", unsafe_allow_html=True)
        _explain("What is a divergence?", "The price makes a new high or low but the indicator does not agree. Think of a company reporting record revenue but declining profits. The numbers do not match. That is an early warning that the trend might reverse soon.", "neutral")
    else:
        st.info("No divergences found. All indicators agree with the current trend.")

    # Volume Profile
    vp = TA.volume_profile(df)
    if not vp.empty:
        poc = vp.loc[vp["volume"].idxmax()]
        fig_vp = go.Figure(go.Bar(x=vp["volume"], y=vp["mid"], orientation="h",
            marker_color=["#10b981" if v == vp["volume"].max() else "#3b82f6" for v in vp["volume"]]))
        fig_vp.add_hline(y=poc["mid"], line_dash="solid", line_color="#f59e0b", annotation_text=f"POC ${poc['mid']:.2f}")
        fig_vp.update_layout(template="plotly_dark", paper_bgcolor="#080c14", plot_bgcolor="#080c14", height=300,
            margin=dict(l=60, r=20, t=20, b=40), yaxis_title="Price", xaxis_title="Volume", font=dict(family="JetBrains Mono", color="#94a3b8"))
        st.plotly_chart(fig_vp, use_container_width=True, config=_PLOTLY_UI_CONFIG)
        _explain("\U0001f9e0 Volume Profile", f"The Point of Control (POC) is ${poc['mid']:.2f}. This is the most traded price. Think of it as the price point where your store sees the most customers. The stock is pulled toward this price like a magnet. Use it to pick your option strike prices.", "neutral")

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 4 \u2014 CASH-FLOW STRATEGIES
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="strategies" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Cash Flow Strategies", f"Exactly which options to sell for {ticker} at ${price:.2f}. Copy strikes into your broker.",
             tip_plain="Pick the top optimal strike first. Covered calls are for owned shares. Cash secured puts are for cash income with possible entry. Spreads cap risk when you need tighter control.")
    st.markdown(
        f"<div class='tc'><div style='text-align:center'><span style='color:#64748b;font-size:.8rem'>ANALYZING</span><br>"
        f"<span style='font-size:1.4rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(ticker)} @ ${price:.2f}</span></div></div>",
        unsafe_allow_html=True,
    )

    if opt_exps:
        sel_exp = st.selectbox("Expiration", opt_exps[:10], index=min(2, len(opt_exps) - 1), key="sel_exp")
        dte = max(1, (datetime.strptime(sel_exp, "%Y-%m-%d") - datetime.now()).days)
        result_sel, _ = fetch_options(ticker, sel_exp)
        calls, puts = result_sel
        if not calls.empty or not puts.empty:
            s1, s2 = st.columns(2)
            with s1:
                st.markdown("#### Covered Calls")
                cc = Opt.covered_calls(price, calls, dte, rfr)
                if cc:
                    opt_cc = next((c for c in cc if c.get("optimal")), cc[0])
                    b = opt_cc; nc_s = 1
                    opt_html = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                    in_zone = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                    delta_color = "#10b981" if in_zone else "#f59e0b"
                    st.markdown(f"<div class='sb'>{opt_html}<strong>SELL {nc_s}x ${b['strike']:.0f}C @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color}'>\u0394 {b['delta']:.2f}</strong><br>Premium: <strong style='color:#10b981'>${b['prem_100'] * nc_s:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Ann: {b['ann_yield']:.1f}% | OI: {b['oi']:,}</span></div>", unsafe_allow_html=True)
                    if st.checkbox("All CC strikes", key="exp_5"):
                        st.dataframe(pd.DataFrame(cc)[["strike", "mid", "delta", "otm_pct", "prem_100", "ann_yield", "iv", "volume", "oi", "optimal"]].rename(columns={"strike": "K", "mid": "Mid", "delta": "\u0394", "otm_pct": "OTM%", "prem_100": "$/K", "ann_yield": "Ann%", "iv": "IV%", "volume": "Vol", "oi": "OI", "optimal": "PropDesk"}), width="stretch", hide_index=True)
                else:
                    st.info("No liquid covered call strikes found. We need at least 100 open interest and 10 volume.")
            with s2:
                st.markdown("#### Cash Secured Puts")
                csp = Opt.cash_secured_puts(price, puts, dte, rfr)
                if csp:
                    opt_csp = next((c for c in csp if c.get("optimal")), csp[0])
                    b = opt_csp
                    opt_html_p = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                    in_zone_p = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                    delta_color_p = "#10b981" if in_zone_p else "#f59e0b"
                    st.markdown(f"<div class='sb'>{opt_html_p}<strong>SELL 1x ${b['strike']:.0f}P @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color_p}'>\u0394 {b['delta']:.2f}</strong><br>Premium: <strong style='color:#10b981'>${b['prem_100']:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Eff buy: ${b['eff_buy']:.2f} | OI: {b['oi']:,}</span></div>", unsafe_allow_html=True)
                    if st.checkbox("All CSP strikes", key="exp_6"):
                        st.dataframe(pd.DataFrame(csp)[["strike", "mid", "delta", "otm_pct", "prem_100", "ann_yield", "iv", "volume", "oi", "eff_buy", "optimal"]].rename(columns={"strike": "K", "mid": "Mid", "delta": "\u0394", "otm_pct": "OTM%", "prem_100": "$/K", "ann_yield": "Ann%", "iv": "IV%", "volume": "Vol", "oi": "OI", "eff_buy": "EffBuy", "optimal": "PropDesk"}), width="stretch", hide_index=True)
                else:
                    st.info("No liquid put strikes found. We need at least 100 open interest and 10 volume.")

            _explain("\U0001f9e0 What are Delta and Theta?",
                "<strong>Delta is your win probability.</strong> A Delta of 0.16 means you have an 84 percent chance to keep all the cash and keep your shares. Lower Delta means safer. "
                "<strong>Theta is your daily paycheck.</strong> Every day that passes, the option loses value. That lost value goes straight into your pocket. Time is literally paying you. "
                "<strong>OI is how busy the market is.</strong> Higher OI means more traders are active. That means you get better prices when you sell. We filter out anything below 100 OI to protect you.", "neutral")

            st.markdown("---")
            sp1, sp2 = st.columns(2)
            with sp1:
                st.markdown("#### Bull Put Spread")
                ps = Opt.credit_spreads(price, puts, "put_credit")
                if ps:
                    b = ps[0]
                    st.markdown(f"<div class='sb'><strong>${b['short']:.0f}P/${b['long']:.0f}P</strong> | Cr: ${b['credit_100']:.0f} | ML: ${b['max_loss']:.0f} | POP: {b['pop']:.0f}%</div>", unsafe_allow_html=True)
            with sp2:
                st.markdown("#### Bear Call Spread")
                cs = Opt.credit_spreads(price, calls, "call_credit")
                if cs:
                    b = cs[0]
                    st.markdown(f"<div class='sr'><strong>${b['short']:.0f}C/${b['long']:.0f}C</strong> | Cr: ${b['credit_100']:.0f} | ML: ${b['max_loss']:.0f} | POP: {b['pop']:.0f}%</div>", unsafe_allow_html=True)

            _explain("\U0001f9e0 What is a credit spread?",
                "A credit spread is like selling insurance with a cap on your worst case. You sell one option and collect cash. Then you buy a cheaper one further away to limit your risk. "
                "<strong>POP</strong> is your Probability of Profit. <strong>ML</strong> is your Max Loss, the absolute worst case. <strong>Cr</strong> is the cash you receive today. "
                "A 75% POP means you win roughly 3 out of every 4 times you make this trade.", "neutral")

            # ── DIAMOND-TRIGGERED OPTIONS SUGGESTIONS ──
            if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
                st.markdown("---")
                if latest_d["type"] == "blue":
                    st.markdown(f"""<div class='diamond-blue'>
                        <div style='font-size:1rem;font-weight:700;margin-bottom:8px'>🔷 BLUE DIAMOND AUTO-SUGGESTIONS</div>
                        <div style='color:#94a3b8;font-size:.85rem;margin-bottom:10px'>
                            A Blue Diamond fired {(df.index[-1] - latest_d['date']).days} day(s) ago at ${latest_d['price']:.2f} with confluence {latest_d['score']}/9.
                            Historical probability of profit: <strong style='color:#10b981'>{d_wr:.0f}%</strong> ({d_n} signals backtested).
                        </div>
                        <div style='color:#e2e8f0;font-size:.9rem;line-height:1.8'>""", unsafe_allow_html=True)
                    suggestions = []
                    if cc:
                        b = cc[0]
                        suggestions.append(f"<strong>Covered Call:</strong> Sell {nc}x ${b['strike']:.0f}C exp {sel_exp} @ ${b['mid']:.2f} (collect ${b['prem_100']*nc:,.0f})")
                    if csp:
                        b = csp[0]
                        suggestions.append(f"<strong>Cash Secured Put:</strong> Sell 1x ${b['strike']:.0f}P exp {sel_exp} @ ${b['mid']:.2f} (collect ${b['prem_100']:,.0f})")
                    if ps:
                        b = ps[0]
                        suggestions.append(f"<strong>Bull Put Spread:</strong> ${b['short']:.0f}/${b['long']:.0f}P exp {sel_exp} credit ${b['credit_100']:,.0f} POP {b['pop']:.0f}%")
                    for sug in suggestions:
                        st.markdown(f"<div style='margin:4px 0'>• {sug}</div>", unsafe_allow_html=True)
                    st.markdown("</div></div>", unsafe_allow_html=True)
                    _explain("Why these trades on a Blue Diamond?",
                        f"The Blue Diamond means {latest_d['score']} out of 9 confluence factors aligned bullish. "
                        "Historically, similar setups have a strong track record. "
                        "Covered Calls collect premium while riding the trend. "
                        "Cash Secured Puts let you buy the dip if it comes. "
                        "Bull Put Spreads give you bullish exposure with capped risk. "
                        "Pick the strategy that matches your capital and conviction.", "bull")
                else:
                    st.markdown(f"""<div class='diamond-pink'>
                        <div style='font-size:1rem;font-weight:700;margin-bottom:8px'>💎 PINK DIAMOND: DEFENSIVE POSTURE</div>
                        <div style='color:#94a3b8;font-size:.85rem;margin-bottom:10px'>
                            A Pink Diamond fired {(df.index[-1] - latest_d['date']).days} day(s) ago at ${latest_d['price']:.2f}.
                            Confluence dropped to {latest_d['score']}/9. Momentum is exhausting.
                        </div>
                        <div style='color:#e2e8f0;font-size:.9rem;line-height:1.8'>""", unsafe_allow_html=True)
                    if cs:
                        b = cs[0]
                        st.markdown(f"<div style='margin:4px 0'>• <strong>Bear Call Spread:</strong> ${b['short']:.0f}/${b['long']:.0f}C credit ${b['credit_100']:,.0f} POP {b['pop']:.0f}%</div>", unsafe_allow_html=True)
                    if cc:
                        b = cc[0]
                        st.markdown(f"<div style='margin:4px 0'>• <strong>Aggressive Covered Call:</strong> Sell ATM or near-ATM ${b['strike']:.0f}C to maximize premium capture</div>", unsafe_allow_html=True)
                    st.markdown(f"<div style='margin:4px 0'>• <strong>Tighten Stops:</strong> If below Gold Zone ${gold_zone_price:.2f}, consider reducing exposure</div>", unsafe_allow_html=True)
                    st.markdown("</div></div>", unsafe_allow_html=True)
                    _explain("Why go defensive on a Pink Diamond?",
                        "The Pink Diamond means bullish momentum has exhausted or confluence collapsed. "
                        "This does not mean crash. It means the easy money in the current leg is done. "
                        "Bear Call Spreads profit from a pullback. Aggressive CCs lock in premium at the top. "
                        "Wait for the next Blue Diamond before entering again aggressively.", "bear")

            # Greeks, EV & Vol Skew
            st.markdown("---")
            st.markdown("#### Greeks, Expected Value & Volatility Skew")
            gk1, gk2, gk3 = st.columns(3)
            with gk1:
                if cc:
                    b0 = cc[0]; iv_d = b0["iv"] / 100 if b0["iv"] > 0 else 0.5; T_y = dte / 365
                    gr = bs_greeks(price, b0["strike"], T_y, rfr, iv_d, "call")
                    fv = bs_price(price, b0["strike"], T_y, rfr, iv_d, "call")
                    edge = b0["mid"] - fv
                    edge_c = "#10b981" if edge > 0 else "#ef4444"
                    st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>TOP CC GREEKS (r={rfr * 100:.2f}%)</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>Delta: <strong style='color:#e2e8f0'>{gr['delta']:.3f}</strong><br>Theta: <strong style='color:#10b981'>${gr['theta']:.3f}/day</strong><br>Vega: <strong style='color:#e2e8f0'>${gr['vega']:.3f}/1%IV</strong><br>Fair: <strong style='color:#e2e8f0'>${fv:.2f}</strong> | Edge: <strong style='color:{edge_c}'>${edge:+.2f}</strong></div></div>", unsafe_allow_html=True)
                else:
                    st.markdown("<div class='tc'><span style='color:#64748b'>No CC data for Greeks</span></div>", unsafe_allow_html=True)
            with gk2:
                ev_lines = []
                if cc:
                    b0 = cc[0]; pop_cc = min(85, max(50, 100 - b0["otm_pct"] * 5))
                    ev_cc = calc_ev(b0["prem_100"], b0["prem_100"] * 3, pop_cc)
                    ec = "#10b981" if ev_cc > 0 else "#ef4444"
                    ev_lines.append(f"CC ${b0['strike']:.0f}: <strong style='color:{ec}'>${ev_cc:+.0f}</strong> (POP ~{pop_cc:.0f}%)")
                if ps:
                    b0 = ps[0]; ev_ps = calc_ev(b0["credit_100"], b0["max_loss"], b0["pop"])
                    ec = "#10b981" if ev_ps > 0 else "#ef4444"
                    ev_lines.append(f"Put Spread: <strong style='color:{ec}'>${ev_ps:+.0f}</strong> (POP {b0['pop']:.0f}%)")
                joined = "<br>".join(ev_lines) if ev_lines else "N/A"
                st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>EXPECTED VALUE</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>{joined}</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>Positive = edge. Negative = avoid.</div></div>", unsafe_allow_html=True)
            with gk3:
                skew, p_iv, c_iv = calc_vol_skew(price, calls, puts)
                if skew is not None:
                    sc = "#ef4444" if skew > 10 else ("#f59e0b" if skew > 5 else "#10b981")
                    sm = "Institutions hedging heavily" if skew > 10 else ("Mild put skew" if skew > 5 else "Balanced")
                    st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>VOL SKEW</div><div class='mono' style='font-size:1.3rem;color:{sc};margin-top:8px'>{skew:+.1f}%</div><div style='color:#94a3b8;font-size:.85rem;margin-top:4px'>Put IV: {p_iv:.1f}% | Call IV: {c_iv:.1f}%</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>{sm}</div></div>", unsafe_allow_html=True)
                else:
                    st.markdown("<div class='tc'><div style='font-size:.7rem;color:#64748b'>VOL SKEW</div><div style='color:#94a3b8;margin-top:8px'>Insufficient IV data</div></div>", unsafe_allow_html=True)

            _explain("\U0001f9e0 What do these numbers mean for me?",
                "<strong>Expected Value (EV)</strong> is your long term profit margin. Think of it like calculating net profit per product after returns. Positive EV means you have a real edge. Negative means avoid the trade. "
                "<strong>Volatility Skew</strong> tells you if big institutions are buying crash insurance. When put prices are much higher than call prices, fear is elevated. You get fatter premiums but the risk is also higher. "
                "<strong>Edge</strong> is the difference between the market price and the mathematically fair price. Positive Edge means the market is overpaying you. That is exactly what you want.", "neutral")
        else:
            st.warning("Options data currently unavailable. Try again or check market hours.")
    else:
        st.warning("Options data currently unavailable for this ticker.")

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 5 \u2014 PSYCHOLOGY & RISK MANAGEMENT
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="risk" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Psychology and Risk Management", "How scared or greedy is the market? How much should you bet? Your safety rules live here.",
             tip_plain="This keeps you safe. Fear and Greed tells pricing pressure. Kelly and ATR tell max size. If signals conflict, size down and wait for cleaner alignment.")
    p1, p2 = st.columns(2)
    with p1:
        gc = "#10b981" if fg < 30 else ("#f59e0b" if fg < 60 else "#ef4444")
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>FEAR & GREED</div><div style='font-size:3.5rem;font-weight:800;color:{gc};margin:12px 0;font-family:JetBrains Mono,monospace'>{fg:.0f}</div><div style='font-size:1.1rem;color:{gc}'>{fg_emoji} {fg_label}</div><div style='color:#94a3b8;margin-top:8px;font-size:.85rem'>{fg_advice}</div></div>", unsafe_allow_html=True)
        _explain("Why sentiment matters",
            "Fear and Greed is like reading the room before you set your prices. "
            "<strong style='color:#10b981'>High fear (low score)</strong>: Customers are panicking. They will pay you extra for protection. Sell options aggressively and collect fat premiums. "
            "<strong style='color:#ef4444'>High greed (high score)</strong>: Everyone is euphoric. Premiums get thinner and the risk of losing your shares goes up. Be very selective.",
            "bull" if fg < 40 else ("bear" if fg > 60 else "neutral"))
        st.markdown("#### Macro Environment")
        for k, v in macro.items():
            dc = "#10b981" if v["chg"] >= 0 else "#ef4444"
            st.markdown(f"<div style='display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1e293b'><span style='color:#94a3b8'>{k}</span><span class='mono' style='color:#e2e8f0'>{v['price']:.2f} <span style='color:{dc}'>{v['chg']:+.2f}%</span></span></div>", unsafe_allow_html=True)
    with p2:
        mrt = REF_NOTIONAL * RISK_PCT_EXAMPLE / 100
        st.markdown(
            f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>EXAMPLE MAX RISK/TRADE</div>"
            f"<div class='mono' style='font-size:1.3rem;color:#e2e8f0'>${mrt:,.0f}</div>"
            f"<div style='font-size:.65rem;color:#64748b;margin-top:6px'>{RISK_PCT_EXAMPLE:.0f}% of ${REF_NOTIONAL:,.0f} reference (illustrative)</div></div>",
            unsafe_allow_html=True,
        )
        atr_v = TA.atr(df).iloc[-1]
        if pd.isna(atr_v) or atr_v <= 0:
            atr_v = price * .03
        sh_atr = int(mrt / (atr_v * 2)) if atr_v > 0 else 0
        st.markdown(f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>ATR SIZING</div><div style='color:#94a3b8;font-size:.85rem;margin-top:8px'>ATR: ${atr_v:.2f} | Max shares: {sh_atr} | Contracts: {sh_atr // 100}</div></div>", unsafe_allow_html=True)
        _explain("Position sizing in plain English",
            f"ATR is ${atr_v:.2f}. That is how much this stock moves on an average day. Think of it as the normal daily price swing. "
            f"Using an illustrative {RISK_PCT_EXAMPLE:.0f}% risk budget on a ${REF_NOTIONAL:,.0f} reference account (${mrt:,.0f} max loss per trade), "
            f"you could size up to about {sh_atr} shares or {max(0, sh_atr // 100)} option contracts. Scale to your own account and rules.", "neutral")

        # Kelly Criterion — mathematically optimal allocation
        k_full, k_half = 0.0, 0.0
        k_source = ""
        if bluf_cc:
            k_pop = min(85, max(50, 100 - bluf_cc["otm_pct"] * 5))
            k_win = bluf_cc["prem_100"]
            k_loss = k_win * 3
            k_full, k_half = kelly_criterion(k_pop, k_win, k_loss)
            k_source = f"CC ${bluf_cc['strike']:.0f}"
        elif bluf_csp:
            k_pop = min(85, max(50, 100 - bluf_csp["otm_pct"] * 5))
            k_win = bluf_csp["prem_100"]
            k_loss = bluf_csp["strike"] * 100 - k_win
            k_full, k_half = kelly_criterion(k_pop, k_win, k_loss)
            k_source = f"CSP ${bluf_csp['strike']:.0f}"
        if k_half > 0:
            k_dollars = REF_NOTIONAL * k_half / 100
            kc = "#10b981" if k_half <= RISK_PCT_EXAMPLE * 5 else "#f59e0b"
            st.markdown(
                f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>KELLY CRITERION (HALF-KELLY)</div>"
                f"<div class='mono' style='font-size:1.3rem;color:{kc}'>{k_half:.1f}% = ${k_dollars:,.0f}</div>"
                f"<div style='font-size:.7rem;color:#64748b;margin-top:4px'>Full Kelly: {k_full:.1f}% | Source: {k_source}</div></div>",
                unsafe_allow_html=True)
            _explain("Kelly Criterion in plain English",
                f"The Kelly formula suggests about {k_full:.1f}% of a reference portfolio for this edge. "
                f"We show <strong>Half Kelly ({k_half:.1f}%)</strong> for safety — on a <strong>${REF_NOTIONAL:,.0f}</strong> illustrative account that is <strong>${k_dollars:,.0f}</strong>. "
                "Scale to your own capital and risk rules; this app does not store your balances.", "neutral")
        else:
            st.markdown("<div class='tc'><div style='font-size:.75rem;color:#64748b'>KELLY CRITERION</div>"
                "<div style='color:#94a3b8;font-size:.85rem;margin-top:6px'>Not enough data yet. No liquid option strikes available to calculate your optimal bet size.</div></div>",
                unsafe_allow_html=True)

        st.markdown("#### Active Alerts")
        if al:
            for a in al:
                ic = "\U0001f7e2" if a["t"] == "bullish" else ("\U0001f534" if a["t"] == "bearish" else "\U0001f7e1")
                st.markdown(f"<div class='ac'>{ic} [{a['p']}] {a['m']}</div>", unsafe_allow_html=True)
        else:
            st.info("No alerts.")

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 6 \u2014 PREMIUM SIMULATOR
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="simulator" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Premium Simulator", "What if you had been selling covered calls for the past year? See the proof right here.",
             tip_plain="Stress test before placing real orders. Change OTM, hold days, and IV assumptions. Prefer settings that stay robust across market moods.")
    st.warning("This uses estimated premiums based on historical volatility. It is not exact. Think of it as a dress rehearsal. Real results will vary.")
    bc1, bc2, bc3, bc4 = st.columns(4)
    bt_otm = bc1.slider("OTM%", 2, 15, 5, key="sim_otm") / 100
    bt_hold = bc2.slider("Hold (d)", 7, 45, 30, key="sim_hold")
    bt_per = bc3.selectbox("Period", ["6mo", "1y"], index=1, key="sim_period")
    bt_iv = bc4.slider("IV Mult", .5, 2.0, 1.0, .1, key="sim_iv")
    bt_df = fetch_stock(ticker, bt_per, "1d")
    if bt_df is not None and len(bt_df) > bt_hold + 20:
        br = Backtest.cc_sim(bt_df, bt_otm, bt_hold, bt_iv)
        if not br.empty:
            tp = br["premium"].sum() * 1
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Trades", len(br))
            m2.metric("Win Rate", f"{(br['profit'] > 0).mean() * 100:.0f}%")
            m3.metric("Avg Ret", f"{br['ret_pct'].mean():.1f}%")
            m4.metric("Est Premium", f"${tp:,.0f}")
            br["cum"] = br["ret_pct"].cumsum()
            fig_b = go.Figure(go.Scatter(x=br["entry_date"], y=br["cum"], mode="lines+markers",
                line=dict(color="#10b981", width=2), marker=dict(size=5)))
            fig_b.update_layout(template="plotly_dark", paper_bgcolor="#080c14", plot_bgcolor="#080c14",
                height=300, margin=dict(l=40, r=20, t=20, b=40), yaxis_title="Cum Ret %",
                font=dict(family="JetBrains Mono", color="#94a3b8"))
            st.plotly_chart(fig_b, use_container_width=True, config=_PLOTLY_UI_CONFIG)
            wr = (br["profit"] > 0).mean() * 100
            _explain("\U0001f9e0 What does this backtest tell me?",
                f"Over {len(br)} simulated trades, selling {bt_otm * 100:.0f}% out of the money covered calls every {bt_hold} days would have made roughly <strong>${tp:,.0f}</strong> in premium cash. "
                f"The win rate was {wr:.0f}%. That means most of your options expired worthless and you kept all the cash. "
                "Think of this as reviewing last year's sales numbers before planning this year's budget. It is your proof of concept.",
                "bull" if wr > 60 else "neutral")

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 7 — MARKET SCANNER (multi-ticker diamond & confluence scan)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="scanner" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("🔎 Market Scanner", "Scan your entire watchlist for Diamond Signals, Confluence Points, and Gold Zone proximity in one view.",
             tip_plain="Find the best ticker quickly. Start with highest confluence and active Blue Diamond. If no clean setup appears, do nothing and preserve capital.")

    watchlist_tickers = [t.strip().upper() for t in scanner_watchlist.split(",") if t.strip()]
    if watchlist_tickers:
        if st.button("Scan Watchlist", key="run_scanner"):
            scanner_results = []
            scan_progress = st.progress(0)
            for si, tkr in enumerate(watchlist_tickers):
                scan_progress.progress((si + 1) / len(watchlist_tickers), text=f"Scanning {tkr}...")
                result = scan_single_ticker(tkr)
                if result:
                    scanner_results.append(result)
            scan_progress.empty()

            if scanner_results:
                if scanner_sort_mode == "Highest confluence first":
                    scanner_results.sort(key=lambda x: x["cp_score"], reverse=True)
                else:
                    order = {t: i for i, t in enumerate(watchlist_tickers)}
                    scanner_results.sort(key=lambda x: order.get(x["ticker"], 10_000))

                for r in scanner_results:
                    pc = "#10b981" if r["chg_pct"] >= 0 else "#ef4444"
                    cpc = "#10b981" if r["cp_score"] >= 7 else ("#f59e0b" if r["cp_score"] >= 4 else "#ef4444")
                    qec = "#10b981" if r["qs"] > 70 else ("#f59e0b" if r["qs"] > 50 else "#ef4444")
                    gz_c = "#10b981" if r["dist_gz"] > 0 else "#ef4444"

                    cp_mini_bar = ""
                    for bi in range(r["cp_max"]):
                        filled = bi < r["cp_score"]
                        bc = "#10b981" if filled and r["cp_score"] >= 7 else ("#f59e0b" if filled and r["cp_score"] >= 4 else ("#ef4444" if filled else "#1e293b"))
                        cp_mini_bar += f"<div style='flex:1;height:6px;background:{bc};border-radius:3px;margin:0 1px'></div>"

                    st.markdown(f"""<div class='scanner-row'>
                        <div class='scanner-grid'>
                            <div style='min-width:80px'>
                                <div style='font-size:1.1rem;font-weight:700;color:#e2e8f0'>{r['ticker']}</div>
                                <div class='mono' style='font-size:.9rem;color:{pc}'>${r['price']:.2f} ({r['chg_pct']:+.1f}%)</div>
                            </div>
                            <div style='text-align:center;min-width:70px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>QE Score</div>
                                <div class='mono' style='color:{qec};font-weight:700'>{r['qs']:.0f}/100</div>
                            </div>
                            <div style='text-align:center;min-width:100px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Confluence</div>
                                <div class='mono' style='color:{cpc};font-weight:700'>{r['cp_score']}/{r['cp_max']}</div>
                                <div style='display:flex;gap:1px;margin-top:3px;width:80px'>{cp_mini_bar}</div>
                            </div>
                            <div style='text-align:center;min-width:100px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Diamond</div>
                                <span class='diamond-badge {r["d_class"]}'>{r['d_status']}</span>
                            </div>
                            <div style='text-align:center;min-width:90px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Gold Zone</div>
                                <div class='mono' style='font-size:.8rem;color:#fbbf24'>${r['gold_zone']:.2f}</div>
                                <div style='font-size:.7rem;color:{gz_c}'>{r['dist_gz']:+.1f}%</div>
                            </div>
                            <div style='text-align:center;min-width:60px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Daily</div>
                                <div style='font-size:.8rem;color:{"#10b981" if r["struct"]=="BULLISH" else ("#ef4444" if r["struct"]=="BEARISH" else "#f59e0b")}'>{r['struct']}</div>
                            </div>
                            <div style='flex:1;min-width:180px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Summary</div>
                                <div class='scan-summary' style='font-size:.82rem;color:#e2e8f0;line-height:1.4'>{r['summary']}</div>
                            </div>
                        </div>
                    </div>""", unsafe_allow_html=True)

                _explain("🔎 How to use the Scanner",
                    "Look for tickers with <strong>7+ confluence points</strong> and an active <strong>Blue Diamond</strong>. "
                    "Those are your highest-probability setups across the entire watchlist. "
                    "Tickers near their Gold Zone with rising confluence are about to trigger. "
                    "Pink Diamonds mean take profits or avoid new entries on that ticker. "
                    "Sort mentally by confluence score. The higher the number, the stronger the setup.", "neutral")
            else:
                st.info("No scanner results. Check your ticker symbols.")
    else:
        st.info("Add tickers to your watchlist in the sidebar to use the scanner.")

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 8 \u2014 NEWS & MACRO
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="news" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("News and Market Conditions", f"Latest headlines and big picture forces affecting {ticker} right now",
             tip_plain="News explains sudden moves and premium spikes. Read macro with price action. If headline risk is high near earnings, keep strikes safer and reduce size.")
    n1, n2 = st.columns([3, 2])
    with n1:
        st.markdown(f"#### {ticker} News")
        if news:
            for item in news:
                lnk = f"<a href='{item['link']}' target='_blank' style='color:#06b6d4'>Read</a>" if item["link"] else ""
                st.markdown(f"<div class='ni'><strong style='color:#e2e8f0'>{item['title']}</strong><br><span style='color:#64748b;font-size:.8rem'>{item['pub']} {item['time']}</span>{' | ' + lnk if lnk else ''}</div>", unsafe_allow_html=True)
        else:
            st.info("No news found.")
    with n2:
        st.markdown("#### Macro Dashboard")
        for k, v in macro.items():
            dc = "#10b981" if v["chg"] >= 0 else "#ef4444"
            st.markdown(f"<div class='tc' style='padding:10px 14px;margin-bottom:6px'><div style='display:flex;justify-content:space-between'><span style='color:#94a3b8'>{k}</span><span class='mono' style='color:#e2e8f0'>{v['price']:.2f} <span style='color:{dc}'>{v['chg']:+.2f}%</span></span></div></div>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 9 \u2014 QUICK REFERENCE GUIDE (always visible)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="guide" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Quick Reference Guide", "Every tool and strategy on this page explained like you are five. Bookmark this section.",
             tip_plain="Use this glossary when a metric feels unclear. Fast clarity prevents bad clicks and overtrading.")
    edu = [
        ("Blue Diamond Signal", "A Blue Diamond appears when 7 or more out of 9 confluence factors align bullish at the same time. Think of it as every traffic light on your route turning green simultaneously. It means Supertrend, Ichimoku, ADX, OBV, Structure, and Gold Zone all agree: this is a high probability buy zone. Buy on Blue Diamonds."),
        ("Pink Diamond Signal", "A Pink Diamond appears when bullish confluence collapses or momentum exhausts (RSI > 75 with weak confluence). Think of it as your dashboard warning lights all turning on. It means the easy money in this move is done. Take profits, sell aggressive covered calls, or tighten your stops. Sell on Pink Diamonds."),
        ("Gold Zone", "The Gold Zone is a single dynamic price level calculated from Volume Profile POC, the 61.8% Fibonacci golden ratio, the nearest Gann Square of 9 level, and weekly support or resistance. When the stock is above the Gold Zone, bulls are in control. Below it, bears have the edge. Use the Gold Zone as your anchor for all strike selection."),
        ("Confluence Points (0-9)", "The Confluence score checks 9 independent bullish factors: Supertrend direction (2pts), Ichimoku cloud position (2pts), ADX trend strength (1pt), OBV accumulation (1pt), bullish divergences (1pt), position vs Gold Zone (1pt), and market structure (1pt). Scores of 7+ trigger Blue Diamonds. Scores below 4 signal caution."),
        ("Covered Call", "You own 100 shares. You sell 1 call above the current price. You collect cash today. If the stock stays below that price, you keep the cash AND you keep your shares. Target: 1 to 3 percent per month in pure cash income."),
        ("Cash Secured Put and The Wheel", "You sell a put and hold cash to buy shares if needed. If you get assigned, you sell Covered Calls on those new shares. When shares get called away, you sell puts again. This is the cash flow loop. Repeat forever."),
        ("Credit Spreads", "You sell one option and collect cash. Then you buy a cheaper one further away to cap your worst case loss. Bull Put Spread means you are bullish. Bear Call Spread means you are bearish. Uses less money than Cash Secured Puts."),
        ("RSI (Relative Strength Index)", "RSI is a 0 to 100 energy meter for the stock. Above 70 means buyers are exhausted. Great time to sell calls. Below 30 means sellers panicked. Great time to sell puts. The sweet spot for collecting cash is 40 to 60."),
        ("MACD", "MACD shows who is winning: buyers or sellers. When the blue line crosses above the orange line, buyers are taking over. When it crosses below, sellers are winning. Think of it as comparing this month's sales to the quarterly average."),
        ("ADX (Trend Strength)", "ADX is a 0 to 100 gauge for how strong the trend is. Above 25 means a strong trend is happening. Below 20 means the market is going nowhere. ADX does not tell you the direction. It only tells you the strength."),
        ("Ichimoku Cloud", "The cloud is a safety net for the stock price. When the price floats above the cloud, the trend is bullish. When it falls into or below the cloud, the trend is weak. When all 5 parts agree, that is the strongest signal you can get."),
        ("Supertrend", "The Supertrend is your price floor or ceiling. Green line below the price means bullish. Your shares are safe. Red line above the price means bearish. When it flips color, that is your signal to act."),
        ("OBV (On Balance Volume)", "OBV tracks what the big money is doing. Rising OBV means institutions are quietly buying. Think of wholesale customers stocking up. Falling OBV means they are selling. If OBV disagrees with the price, a reversal may be coming."),
        ("Fibonacci Retracement", "After a big move, stocks pull back to key levels before continuing: 38.2%, 50%, and 61.8%. The 61.8% level is the golden ratio. It is the most watched level on Wall Street. Set your put strikes near these levels for the safest entries."),
        ("Volatility Skew", "When put options cost much more than call options, big institutions are buying crash insurance. That means premiums are fat for you to sell. But it also means the smart money is nervous. Collect the cash but stay aware."),
        ("Expected Value", "EV is your long term profit per trade. The formula: (Win percent times your gain) minus (Loss percent times your loss). Positive EV means you have a real edge. Negative EV means walk away."),
        ("Gann Square of 9", "These are natural support and resistance levels calculated from mathematical spirals. Stocks tend to stop or bounce at these prices. Use them to pick smarter strike prices for your options."),
        ("Quant Edge Score", "Your overall score from 0 to 100. It checks five things: Trend, Momentum, Volume, Volatility, and Structure. Above 70 means prime conditions to sell options. Below 40 means wait for a better setup."),
        ("Market Scanner", "The Scanner checks your entire watchlist in seconds. It calculates Confluence Points, Diamond Status, Gold Zone distance, and Quant Edge for every ticker. Sort by confluence to find the strongest setups across all your stocks. Tickers with 7+ confluence and a Blue Diamond are your best opportunities."),
    ]
    for i in range(0, len(edu), 2):
        ec1, ec2 = st.columns(2)
        with ec1:
            st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i][1]}</div></div>", unsafe_allow_html=True)
        with ec2:
            if i + 1 < len(edu):
                st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i + 1][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i + 1][1]}</div></div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
