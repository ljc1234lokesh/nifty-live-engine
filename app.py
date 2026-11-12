import streamlit as st
import pyotp
from SmartApi import SmartConnect
import matplotlib.pyplot as plt
import numpy as np
import datetime
from scipy.stats import norm
import time
import json
import os
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Nifty Institutional Analytics Terminal", layout="wide", initial_sidebar_state="collapsed")

# --- PROFESSIONAL TRADING TERMINAL STYLING (LIGHT & DARK MODE CONTRAST LOCKED) ---
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        max-width: 100% !important;
    }
    header[data-testid="stHeader"] { display: none !important; }
    [data-stale="true"] { opacity: 1 !important; transition: none !important; }
    div[data-testid="stStatusWidget"] { display: none !important; }
    .analytics-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 10px;
        margin-bottom: 12px;
    }
    .card {
        background: #111827 !important;
        border: 1px solid #1f2937 !important;
        border-radius: 8px;
        padding: 10px 12px;
        color: #f8fafc !important;
    }
    .card-label {
        font-size: 0.72rem;
        color: #94a3b8 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 3px;
    }
    .card-val {
        font-size: 1.15rem;
        font-weight: 700;
        color: #f8fafc !important;
        white-space: nowrap;
    }
    .card-sub {
        font-size: 0.72rem;
        color: #38bdf8 !important;
        margin-top: 3px;
    }
    .section-box {
        background: #111827 !important;
        border: 1px solid #1f2937 !important;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 12px;
        color: #f8fafc !important;
    }
    .section-box b, .section-box div, .section-box span {
        color: inherit;
    }
    .leg-row {
        background: #0b0f19 !important;
        border-left: 4px solid #38bdf8;
        padding: 8px 12px;
        margin-bottom: 6px;
        border-radius: 6px;
        font-size: 0.88rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: #f8fafc !important;
    }
    .leg-row b {
        color: #f8fafc !important;
    }
    .leg-row code {
        background: #1e293b !important;
        color: #38bdf8 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-weight: 600 !important;
        border: 1px solid #334155 !important;
    }
    .index-ticker {
        background: #111827 !important;
        border: 1px solid #1f2937 !important;
        border-radius: 6px;
        padding: 8px;
        text-align: center;
        color: #f8fafc !important;
    }
</style>
""", unsafe_allow_html=True)

# --- PERMANENT FILE STORAGE FOR SAVED STRATEGIES ---
STORAGE_FILE = "saved_strategies.json"

def load_saved_strategies():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_strategies_to_disk(strat_list):
    try:
        with open(STORAGE_FILE, "w") as f:
            json.dump(strat_list, f, indent=2)
    except Exception:
        pass

if "saved_strategies" not in st.session_state:
    st.session_state.saved_strategies = load_saved_strategies()

# --- CREDENTIALS ---
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_CODE = st.secrets["CLIENT_CODE"]
    PASSWORD = st.secrets["PASSWORD"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except Exception:
    st.error("⚠️ Angel One Credentials missing in Streamlit Secrets!")
    st.stop()

TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

def send_telegram_alert(message_text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message_text, "parse_mode": "HTML"}
        r = requests.post(url, json=payload, timeout=8)
        return r.status_code == 200
    except Exception:
        return False

# --- ANGEL ONE SESSION ---
@st.cache_resource(ttl=1800, show_spinner=False)
def get_angel_session(api_key, client_code, pwd, totp_sec):
    try:
        smart_api = SmartConnect(api_key)
        totp = pyotp.TOTP(totp_sec).now()
        session = smart_api.generateSession(client_code, pwd, totp)
        if session.get("status"):
            return smart_api
        return None
    except Exception:
        return None

smart_api = get_angel_session(API_KEY, CLIENT_CODE, PASSWORD, TOTP_SECRET)

if not smart_api:
    st.error("❌ Angel One API se connect nahi ho paya.")
    st.stop()

# --- 1. OFFICIAL SCRIP MASTER CACHE ---
@st.cache_data(ttl=43200, show_spinner=False)
def load_angel_master_data():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    r = requests.get(url, timeout=30)
    data = r.json()
    df = pd.DataFrame(data)
    
    idx_map = {
        "NIFTY": "99926000",
        "BANKNIFTY": "99926009",
        "VIX": "99926017",
        "SENSEX": "99919000"
    }
    
    idx_df = df[df["instrumenttype"] == "AMXIDX"]
    for _, row in idx_df.iterrows():
        nm = str(row["name"]).upper().strip()
        sym = str(row["symbol"]).upper().strip()
        tok = str(row["token"]).strip()
        if nm == "INDIA VIX" or sym == "INDIA VIX":
            idx_map["VIX"] = tok
        elif (nm == "SENSEX" or sym == "SENSEX") and str(row["exch_seg"]) == "BSE":
            idx_map["SENSEX"] = tok

    opt_df = df[(df["exch_seg"] == "NFO") & (df["name"] == "NIFTY") & (df["instrumenttype"] == "OPTIDX")].copy()
    opt_df["strike_int"] = (pd.to_numeric(opt_df["strike"], errors="coerce") / 100).round().astype(int)
    opt_df["lotsize_int"] = pd.to_numeric(opt_df["lotsize"], errors="coerce").fillna(65).astype(int)
    opt_df["opt_type"] = opt_df["symbol"].str[-2:]
    opt_df["expiry_dt"] = pd.to_datetime(opt_df["expiry"], format="%d%b%Y", errors="coerce").dt.date
    return opt_df[["token", "symbol", "expiry", "expiry_dt", "strike_int", "opt_type", "lotsize_int"]], idx_map

nfo_df, INDEX_TOKENS = load_angel_master_data()

# --- 2. DAILY OHLC CACHE (SILENT BACKGROUND FETCH EVERY 60s) ---
@st.cache_data(ttl=60, show_spinner=False)
def get_daily_ohlc_cached(idx_tokens):
    ohlc = {
        "nifty": {"open": 25213.50, "high": 25384.80, "low": 25142.95, "close": 25255.05},
        "banknifty": {"open": 60801.85, "high": 61406.35, "low": 60723.10, "close": 60792.40},
        "sensex": {"open": 81762.27, "high": 82325.61, "low": 81576.15, "close": 81879.40}
    }
    to_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    from_date = datetime.datetime.now().strftime("%Y-%m-%d 09:00")
    for idx_key, tok_val, exch in [
        ("nifty", idx_tokens["NIFTY"], "NSE"),
        ("banknifty", idx_tokens["BANKNIFTY"], "NSE"),
        ("sensex", idx_tokens["SENSEX"], "BSE")
    ]:
        try:
            candle_req = {
                "exchange": exch,
                "symboltoken": tok_val,
                "interval": "ONE_DAY",
                "fromdate": from_date,
                "todate": to_date
            }
            c_res = smart_api.getCandleData(candle_req)
            if c_res and c_res.get("status") and "data" in c_res and len(c_res["data"]) > 0:
                latest_candle = c_res["data"][-1]
                ohlc[idx_key] = {
                    "open": float(latest_candle[1]),
                    "high": float(latest_candle[2]),
                    "low": float(latest_candle[3]),
                    "close": float(latest_candle[4])
                }
        except Exception:
            pass
    return ohlc

# --- 3. FAST LIVE LTP FETCHER (SILENT BACKGROUND FETCH EVERY 5s) ---
@st.cache_data(ttl=5, show_spinner=False)
def get_comprehensive_indices(idx_tokens):
    ohlc_data = get_daily_ohlc_cached(idx_tokens)
    out = {
        "nifty": {"ltp": 25243.30, **ohlc_data["nifty"]},
        "banknifty": {"ltp": 61281.05, **ohlc_data["banknifty"]},
        "sensex": {"ltp": 81871.62, **ohlc_data["sensex"]},
        "vix": 16.88
    }
    try:
        t_nifty = idx_tokens["NIFTY"]
        t_bnf   = idx_tokens["BANKNIFTY"]
        t_vix   = idx_tokens["VIX"]
        t_snx   = idx_tokens["SENSEX"]

        res_nse = smart_api.getMarketData("LTP", {"NSE": [t_nifty, t_bnf, t_vix]})
        if res_nse and res_nse.get("status") and "data" in res_nse:
            for item in res_nse["data"].get("fetched", []):
                tok = str(item["symbolToken"])
                ltp = float(item["ltp"])
                if tok == t_nifty and ltp > 10000:
                    out["nifty"]["ltp"] = ltp
                elif tok == t_bnf and ltp > 25000:
                    out["banknifty"]["ltp"] = ltp
                elif tok == t_vix and ltp > 0:
                    out["vix"] = ltp

        res_bse = smart_api.getMarketData("LTP", {"BSE": [t_snx]})
        if res_bse and res_bse.get("status") and "data" in res_bse:
            for item in res_bse["data"].get("fetched", []):
                if str(item["symbolToken"]) == t_snx:
                    out["sensex"]["ltp"] = float(item["ltp"])
    except Exception:
        pass
    return out

market_data = get_comprehensive_indices(INDEX_TOKENS)
live_spot = market_data["nifty"]["ltp"]
live_vix = market_data["vix"]
atm_strike = int(round(live_spot / 50.0) * 50)

# --- 4. REAL-TIME OPTION CHAIN OI ENGINE (LIVE PCR, MAX PAIN & OI WALLS) ---
@st.cache_data(ttl=15, show_spinner=False)
def get_live_option_chain_oi(exp_date_str, atm_val):
    fallback = {
        "pcr": 0.92,
        "max_pain": atm_val,
        "call_wall": atm_val + 150,
        "put_wall": atm_val - 150,
        "call_wall_oi": 0,
        "put_wall_oi": 0,
        "is_live": False,
        "ltp_dict": {}
    }
    try:
        exp_dt_obj = datetime.date.fromisoformat(exp_date_str)
        sub_df = nfo_df[nfo_df["expiry_dt"] == exp_dt_obj]
        if sub_df.empty:
            return fallback

        strikes_scan = [atm_val + i * 50 for i in range(-8, 9)]
        scan_df = sub_df[sub_df["strike_int"].isin(strikes_scan)]
        tokens = scan_df["token"].astype(str).tolist()
        if not tokens:
            return fallback

        res_full = smart_api.getMarketData("FULL", {"NFO": tokens})
        if not (res_full and res_full.get("status") and "data" in res_full):
            return fallback

        fetched = res_full["data"].get("fetched", [])
        if not fetched:
            return fallback

        tok_meta = {}
        for _, r in scan_df.iterrows():
            tok_meta[str(r["token"])] = (int(r["strike_int"]), str(r["opt_type"]))

        ce_oi_map = {}
        pe_oi_map = {}
        ltp_dict = {}

        for item in fetched:
            tok = str(item.get("symbolToken", ""))
            if tok in tok_meta:
                st_k, o_type = tok_meta[tok]
                oi_val = float(item.get("opnInterest", 0))
                ltp_val = float(item.get("ltp", 0))
                ltp_dict[tok] = ltp_val
                if o_type == "CE":
                    ce_oi_map[st_k] = oi_val
                elif o_type == "PE":
                    pe_oi_map[st_k] = oi_val

        tot_ce_oi = sum(ce_oi_map.values())
        tot_pe_oi = sum(pe_oi_map.values())

        if tot_ce_oi <= 0 or tot_pe_oi <= 0:
            fallback["ltp_dict"] = ltp_dict
            return fallback

        pcr_live = round(tot_pe_oi / tot_ce_oi, 2)

        # Call Wall = Strike >= ATM with highest Call OI
        otm_ce = {k: v for k, v in ce_oi_map.items() if k >= atm_val}
        call_wall_k = max(otm_ce, key=otm_ce.get) if otm_ce else max(ce_oi_map, key=ce_oi_map.get)

        # Put Wall = Strike <= ATM with highest Put OI
        otm_pe = {k: v for k, v in pe_oi_map.items() if k <= atm_val}
        put_wall_k = max(otm_pe, key=otm_pe.get) if otm_pe else max(pe_oi_map, key=pe_oi_map.get)

        # True Max Pain Calculation across scanned strikes
        min_pain_val = float("inf")
        max_pain_k = atm_val
        for candidate_spot in strikes_scan:
            pain = 0.0
            for k_c, oi_c in ce_oi_map.items():
                if candidate_spot > k_c:
                    pain += (candidate_spot - k_c) * oi_c
            for k_p, oi_p in pe_oi_map.items():
                if candidate_spot < k_p:
                    pain += (k_p - candidate_spot) * oi_p
            if pain < min_pain_val:
                min_pain_val = pain
                max_pain_k = candidate_spot

        return {
            "pcr": pcr_live,
            "max_pain": max_pain_k,
            "call_wall": call_wall_k,
            "put_wall": put_wall_k,
            "call_wall_oi": int(ce_oi_map.get(call_wall_k, 0)),
            "put_wall_oi": int(pe_oi_map.get(put_wall_k, 0)),
            "is_live": True,
            "ltp_dict": ltp_dict
        }
    except Exception:
        return fallback

# --- 5. IST ENTRY TIMING & QUANT CLOCK ---
utc_now = datetime.datetime.now(datetime.timezone.utc)
ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
ist_time_str = ist_now.strftime("%H:%M:%S IST")
mins_now = ist_now.hour * 60 + ist_now.minute
weekday = ist_now.weekday()

if weekday >= 5 or mins_now < (9 * 60 + 15) or mins_now > (15 * 60 + 30):
    entry_signal = "⚪ MARKET CLOSED"
    entry_advice = "Best Entry: 09:45 AM – 11:30 AM IST"
    sig_color = "#94a3b8"
elif mins_now < (9 * 60 + 45):
    entry_signal = "🔴 WAIT (OPENING NOISE)"
    entry_advice = "09:15–09:45 AM Volatility! Wait till 09:45"
    sig_color = "#ef4444"
elif mins_now <= (11 * 60 + 30):
    entry_signal = "🟢 PRIME ENTRY WINDOW"
    entry_advice = "09:45–11:30 AM Institutional Settlement Time"
    sig_color = "#10b981"
elif mins_now <= (13 * 60 + 30):
    entry_signal = "🟡 SAFE THETA ZONE"
    entry_advice = "11:30–01:30 PM Sideways Decay Window"
    sig_color = "#eab308"
elif mins_now <= (14 * 60 + 45):
    entry_signal = "🟢 2ND PRIME WINDOW"
    entry_advice = "01:30–02:45 PM Afternoon Trend Window"
    sig_color = "#10b981"
else:
    entry_signal = "🟠 AVOID FRESH ENTRY"
    entry_advice = "Closing Gamma Move! Avoid New Positions"
    sig_color = "#f97316"

# --- 6. EXPIRY SELECTOR & TOP TICKER (OHLC) ---
today_date = ist_now.date()
valid_expiries = sorted([d for d in nfo_df["expiry_dt"].dropna().unique() if d >= today_date])
if not valid_expiries:
    st.stop()

top_expiries = valid_expiries[:4]
expiry_labels = [f"{d.strftime('%d-%b')} ({max((d - today_date).days, 1)}d)" for d in top_expiries]

t1, t2, t3 = st.columns(3)
with t1:
    nf = market_data["nifty"]
    st.markdown(f"""
    <div class="index-ticker">
        <div style="font-weight:700; color:#38bdf8; font-size:0.9rem;">NIFTY 50: ₹{nf['ltp']:,.2f}</div>
        <div style="font-size:0.7rem; color:#94a3b8;">O: {nf['open']:,.1f} | H: {nf['high']:,.1f} | L: {nf['low']:,.1f} | C: {nf['close']:,.1f}</div>
    </div>
    """, unsafe_allow_html=True)
with t2:
    bn = market_data["banknifty"]
    st.markdown(f"""
    <div class="index-ticker">
        <div style="font-weight:700; color:#38bdf8; font-size:0.9rem;">BANKNIFTY: ₹{bn['ltp']:,.2f}</div>
        <div style="font-size:0.7rem; color:#94a3b8;">O: {bn['open']:,.1f} | H: {bn['high']:,.1f} | L: {bn['low']:,.1f} | C: {bn['close']:,.1f}</div>
    </div>
    """, unsafe_allow_html=True)
with t3:
    sx = market_data["sensex"]
    st.markdown(f"""
    <div class="index-ticker">
        <div style="font-weight:700; color:#38bdf8; font-size:0.9rem;">SENSEX: ₹{sx['ltp']:,.2f}</div>
        <div style="font-size:0.7rem; color:#94a3b8;">O: {sx['open']:,.1f} | H: {sx['high']:,.1f} | L: {sx['low']:,.1f} | C: {sx['close']:,.1f}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# --- NAVIGATION & AUTO REFRESH (LOCKED TAB KEYS) ---
nav_col1, nav_col2 = st.columns([3, 1])
with nav_col1:
    nav_mode = st.radio(
        "Mode",
        ["⚡ Quant Terminal", "🛡️ Saved Live Tracker"],
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav_mode"
    )
with nav_col2:
    auto_refresh_on = st.toggle("Sync (10s)", value=True)

if auto_refresh_on:
    st_autorefresh(interval=10 * 1000, key="terminal_refresh_silent_v5")

# ==============================================================================
# MODE 2: SAVED LIVE TRACKER (WITH STRIKE PRICES, LIVE LTP & TELEGRAM ALERTS)
# ==============================================================================
if nav_mode == "🛡️ Saved Live Tracker":
    st.markdown(f"### 🛡️ Live Saved Strategies & Strike Tracker ({len(st.session_state.saved_strategies)})")
    
    # Telegram Status Bar
    tg_col1, tg_col2 = st.columns([3.5, 1.5])
    with tg_col1:
        if TG_BOT_TOKEN and TG_CHAT_ID:
            st.caption("📲 **Telegram Live Alerts: ACTIVE** (Target Hit ya Stop-Loss par automatic message jayega)")
        else:
            st.caption("🔕 **Telegram Alerts: OFF** (Streamlit Secrets mein `TELEGRAM_BOT_TOKEN` aur `TELEGRAM_CHAT_ID` jodein)")
    with tg_col2:
        if TG_BOT_TOKEN and TG_CHAT_ID:
            if st.button("🔔 Send Test Alert", key="test_tg_btn"):
                ok = send_telegram_alert(f"✅ <b>Quant Terminal Connected!</b>\nNifty Spot: ₹{live_spot:,.2f}\nTime: {ist_time_str}")
                if ok:
                    st.toast("✅ Telegram par Test Alert bhej diya gaya hai!")
                else:
                    st.toast("❌ Telegram message fail hua. Token/Chat ID check karein.")

    if not st.session_state.saved_strategies:
        st.info("ℹ️ Koi bhi strategy save nahi ki gayi hai. 'Quant Terminal' mein jaakar 'Save Strategy' par click karein.")
    else:
        all_saved_tokens = []
        for s in st.session_state.saved_strategies:
            for leg in s.get("legs", []):
                if leg.get("token"):
                    all_saved_tokens.append(str(leg["token"]))
        
        saved_live_ltps = {}
        if all_saved_tokens:
            try:
                res_opt = smart_api.getMarketData("LTP", {"NFO": list(set(all_saved_tokens))})
                if res_opt and res_opt.get("status") and "data" in res_opt:
                    for item in res_opt["data"].get("fetched", []):
                        saved_live_ltps[str(item["symbolToken"])] = float(item["ltp"])
            except Exception:
                pass

        state_changed = False
        for idx, strat in enumerate(st.session_state.saved_strategies[:]):
            col_info, col_del = st.columns([5.5, 1])
            lot_qty = strat.get("lot_size", 65)
            
            running_pnl_pts = 0.0
            leg_html_rows = ""
            for l_idx, leg in enumerate(strat.get("legs", []), 1):
                entry_p = float(leg["premium"])
                tok = str(leg.get("token", ""))
                curr_p = saved_live_ltps.get(tok, entry_p)
                if curr_p <= 0.05:
                    curr_p = entry_p
                
                leg_pnl_pts = (entry_p - curr_p) if leg["action"] == "SELL" else (curr_p - entry_p)
                running_pnl_pts += leg_pnl_pts
                leg_pnl_rs = leg_pnl_pts * lot_qty
                
                b_col = "#10b981" if leg["action"] == "BUY" else "#ef4444"
                b_txt = "🟢 BUY" if leg["action"] == "BUY" else "🔴 SELL"
                pnl_col = "#10b981" if leg_pnl_rs >= 0 else "#ef4444"
                pnl_sign = "+" if leg_pnl_rs >= 0 else ""
                
                leg_html_rows += (
                    f"<div class='leg-row' style='border-left-color:{b_col}; margin-bottom:4px; padding:6px 10px;'>"
                    f"<div><b>Leg {l_idx}:</b> {b_txt} <code>{leg['readable']}</code></div>"
                    f"<div style='font-size:0.82rem; color:#e2e8f0;'>"
                    f"Entry: <b>₹{entry_p:.2f}</b> &rarr; Live: <b>₹{curr_p:.2f}</b> &nbsp;|&nbsp; "
                    f"<span style='color:{pnl_col}; font-weight:700;'>{pnl_sign}₹{leg_pnl_rs:,.0f}</span>"
                    f"</div></div>"
                )

            total_running_pnl = running_pnl_pts * lot_qty
            tot_col = "#10b981" if total_running_pnl >= 0 else "#ef4444"
            tot_sign = "+" if total_running_pnl >= 0 else ""

            with col_info:
                st.markdown(f"""
                <div class="section-box" style="margin-bottom: 6px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                        <div style="color:#f8fafc;"><b>#{idx+1} - {strat['name']}</b> ({strat['expiry']}) <span style="color:#94a3b8; font-size:0.75rem;">| Saved at {strat.get('time', '')}</span></div>
                        <div style="font-size: 0.85rem; color:#e2e8f0;">
                            Entry Spot: <b style="color:#38bdf8;">₹{strat['entry_spot']:,.2f}</b> &nbsp;|&nbsp; 
                            Live Spot: <b style="color:#f59e0b;">₹{live_spot:,.2f}</b>
                        </div>
                    </div>
                    <hr style="border-color:#1f2937; margin:8px 0;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <div style="font-size:0.83rem; color:#cbd5e1;">
                            Max Profit: <b style="color:#10b981;">₹{strat['max_profit']:,.0f}</b> &nbsp;|&nbsp; 
                            Max Risk: <b style="color:#ef4444;">₹{strat['max_loss']:,.0f}</b>
                        </div>
                        <div style="font-size:0.95rem; font-weight:700; color:{tot_col};">
                            Live P&L: {tot_sign}₹{total_running_pnl:,.0f}
                        </div>
                    </div>
                    {leg_html_rows}
                </div>
                """, unsafe_allow_html=True)
            
            with col_del:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️ Delete", key=f"del_strat_{idx}"):
                    st.session_state.saved_strategies.pop(idx)
                    save_strategies_to_disk(st.session_state.saved_strategies)
                    st.rerun()

            # Live Decision Engine + Anti-Spam Telegram Trigger
            price_drift = live_spot - strat['entry_spot']
            max_p = max(strat.get('max_profit', 1), 1)
            max_l = max(strat.get('max_loss', 1), 1)
            last_alert = strat.get("last_alert_state", "HOLD")

            if total_running_pnl >= 0.65 * max_p:
                st.markdown("🟣 **STATUS: TARGET HIT (BOOK PROFIT)** — Aapke Max Profit ka 65%+ target aa chuka hai! Lalach mat karein, position close karke profit book karein.")
                if last_alert != "TARGET_HIT":
                    msg = (
                        f"🟣 <b>TARGET HIT — BOOK PROFIT!</b>\n"
                        f"Strategy: <b>{strat['name']} ({strat['expiry']})</b>\n"
                        f"Live P&L: <b>+₹{total_running_pnl:,.0f}</b> (Target 65%+ Reached)\n"
                        f"Nifty Spot: ₹{live_spot:,.2f} | Time: {ist_time_str}"
                    )
                    if send_telegram_alert(msg):
                        st.session_state.saved_strategies[idx]["last_alert_state"] = "TARGET_HIT"
                        state_changed = True
            elif total_running_pnl <= -0.50 * max_l or abs(price_drift) >= 160:
                st.markdown("🔴 **STATUS: EXIT / STOP-LOSS ALERT** — Market aapki safe range tod rahi hai ya risk badh gaya hai. Turant position adjust ya exit karein!")
                if last_alert != "SL_HIT":
                    msg = (
                        f"🔴 <b>STOP-LOSS / EXIT ALERT!</b>\n"
                        f"Strategy: <b>{strat['name']} ({strat['expiry']})</b>\n"
                        f"Live P&L: <b>{tot_sign}₹{total_running_pnl:,.0f}</b>\n"
                        f"Spot Drift: {price_drift:+.1f} pts | Nifty: ₹{live_spot:,.2f}"
                    )
                    if send_telegram_alert(msg):
                        st.session_state.saved_strategies[idx]["last_alert_state"] = "SL_HIT"
                        state_changed = True
            elif abs(price_drift) < 70:
                st.markdown("🟢 **STATUS: TIKE RAHO (HOLD)** — Market abhi aapke entry zone ke paas safe corridor mein hai. Theta decay ka fayda uthayein.")
            else:
                st.markdown(f"🟡 **STATUS: MONITOR CLOSELY** — Market mein movement badh rahi hai (Spot Drift: {price_drift:+.1f} pts). Apne breakeven levels par nazar rakhein.")
            st.markdown("---")

        if state_changed:
            save_strategies_to_disk(st.session_state.saved_strategies)

# ==============================================================================
# MODE 1: QUANT TERMINAL (REAL-TIME OPTION CHAIN OI + MULTI-STRATEGY)
# ==============================================================================
else:
    c_head1, c_head2, c_head3 = st.columns([1.2, 2.0, 1.5])
    with c_head1:
        st.markdown("### ⚡ Quant Terminal")
    with c_head2:
        selected_label = st.radio("Expiry", expiry_labels, horizontal=True, label_visibility="collapsed")
    with c_head3:
        strat_mode_choice = st.selectbox(
            "Strategy Mode",
            [
                "🤖 AI Auto-Select (OI-Synced)",
                "🦅 Short Iron Condor (Rangebound)",
                "🦋 Iron Butterfly (High Theta Pinning)",
                "🐻 Bear Call Spread (Resistance Defense)",
                "🐂 Bull Put Spread (Support Defense)"
            ],
            label_visibility="collapsed"
        )

    selected_idx = expiry_labels.index(selected_label)
    chosen_exp_date = top_expiries[selected_idx]
    dte_days = max((chosen_exp_date - today_date).days, 1)
    display_exp = chosen_exp_date.strftime("%d-%b")

    # --- 7. FETCH REAL-TIME OPTION CHAIN OI DATA ---
    oi_data = get_live_option_chain_oi(chosen_exp_date.isoformat(), atm_strike)
    live_pcr = oi_data["pcr"]
    live_max_pain = oi_data["max_pain"]
    call_wall = oi_data["call_wall"]
    put_wall  = oi_data["put_wall"]
    oi_source_tag = "🟢 Live Option Chain OI" if oi_data["is_live"] else "🟡 Estimated OI"

    if live_pcr >= 1.15:
        pcr_sentiment = "Bullish (Strong Put Writing)"
    elif live_pcr <= 0.75:
        pcr_sentiment = "Bearish (Heavy Call Writing)"
    else:
        pcr_sentiment = "Neutral / Rangebound"

    # --- 8. MULTI-STRATEGY ENGINE (POWERED BY LIVE OI WALLS) ---
    if "AI Auto-Select" in strat_mode_choice:
        if live_spot >= call_wall - 35 or live_pcr <= 0.72:
            active_strat_key = "BEAR_CALL"
        elif live_spot <= put_wall + 35 or live_pcr >= 1.25:
            active_strat_key = "BULL_PUT"
        elif live_vix >= 15.5 and abs(live_spot - live_max_pain) <= 50:
            active_strat_key = "IRON_FLY"
        else:
            active_strat_key = "IRON_CONDOR"
    elif "Iron Condor" in strat_mode_choice:
        active_strat_key = "IRON_CONDOR"
    elif "Iron Butterfly" in strat_mode_choice:
        active_strat_key = "IRON_FLY"
    elif "Bear Call" in strat_mode_choice:
        active_strat_key = "BEAR_CALL"
    else:
        active_strat_key = "BULL_PUT"

    if active_strat_key == "BEAR_CALL":
        strat_name = "Bear Call Credit Spread"
        strat_reason = f"Live Call OI Wall at {call_wall} (PCR: {live_pcr:.2f}). Defending upside resistance with hedged credit spread."
        leg_specs = [
            {"type": "CE", "action": "SELL", "strike": call_wall,       "note": f"Live Call Wall ({call_wall} OI)"},
            {"type": "CE", "action": "BUY",  "strike": call_wall + 200, "note": "Upside Protection Wing"}
        ]
    elif active_strat_key == "BULL_PUT":
        strat_name = "Bull Put Credit Spread"
        strat_reason = f"Live Put OI Wall at {put_wall} (PCR: {live_pcr:.2f}). Defending downside support with hedged credit spread."
        leg_specs = [
            {"type": "PE", "action": "SELL", "strike": put_wall,       "note": f"Live Put Wall ({put_wall} OI)"},
            {"type": "PE", "action": "BUY",  "strike": put_wall - 200, "note": "Downside Protection Wing"}
        ]
    elif active_strat_key == "IRON_FLY":
        strat_name = "Short Iron Butterfly (ATM Pinning)"
        strat_reason = f"High VIX ({live_vix:.2f}) & Live Max Pain at {live_max_pain}. Capturing maximum ATM theta decay with 200-pt wings."
        leg_specs = [
            {"type": "PE", "action": "BUY",  "strike": atm_strike - 200, "note": "Downside Hedge Wing"},
            {"type": "PE", "action": "SELL", "strike": atm_strike,       "note": f"ATM Put Sell ({atm_strike} Pin)"},
            {"type": "CE", "action": "SELL", "strike": atm_strike,       "note": f"ATM Call Sell ({atm_strike} Pin)"},
            {"type": "CE", "action": "BUY",  "strike": atm_strike + 200, "note": "Upside Hedge Wing"}
        ]
    else:
        # Ensure minimum 100-pt buffer on wings if OI wall is very close to ATM
        safe_put_sell = min(put_wall, atm_strike - 100)
        safe_call_sell = max(call_wall, atm_strike + 100)
        strat_name = "Short Iron Condor (Live OI-Synced)"
        strat_reason = f"Live Max Pain at {live_max_pain} & PCR {live_pcr:.2f}. Operating inside {safe_put_sell} - {safe_call_sell} OI walls."
        leg_specs = [
            {"type": "PE", "action": "BUY",  "strike": safe_put_sell - 200,  "note": "Put Wall Protection Wing"},
            {"type": "PE", "action": "SELL", "strike": safe_put_sell,        "note": f"Put Credit ({safe_put_sell} OI Support)"},
            {"type": "CE", "action": "SELL", "strike": safe_call_sell,       "note": f"Call Credit ({safe_call_sell} OI Resistance)"},
            {"type": "CE", "action": "BUY",  "strike": safe_call_sell + 200, "note": "Call Wall Protection Wing"}
        ]

    # --- 9. LTP FETCHER & LOT SIZE (65) ---
    verified_baseline_chain = {
        (24800, "PE"): 90.95, (25000, "PE"): 159.30, (25200, "CE"): 206.10, (25400, "CE"): 133.55
    }

    exp_subset = nfo_df[nfo_df["expiry_dt"] == chosen_exp_date]
    LOT_SIZE = 65
    if not exp_subset.empty and "lotsize_int" in exp_subset.columns:
        detected_lot = int(exp_subset["lotsize_int"].iloc[0])
        if detected_lot > 0:
            LOT_SIZE = detected_lot

    def get_contract_info(strike_val, opt_type_val):
        row = exp_subset[(exp_subset["strike_int"] == strike_val) & (exp_subset["opt_type"] == opt_type_val)]
        if not row.empty:
            return str(row.iloc[0]["token"]), str(row.iloc[0]["symbol"])
        return None, None

    def get_kite_symbol(exp_date, strike, opt_type, all_exp_dates):
        yy = exp_date.strftime("%y")
        same_month_exps = [d for d in all_exp_dates if d.year == exp_date.year and d.month == exp_date.month]
        if exp_date == max(same_month_exps):
            return f"NIFTY{yy}{exp_date.strftime('%b').upper()}{strike}{opt_type}"
        month_codes = {1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'O', 11: 'N', 12: 'D'}
        return f"NIFTY{yy}{month_codes.get(exp_date.month, 'N')}{exp_date.strftime('%d')}{strike}{opt_type}"

    tokens_to_fetch = []
    for spec in leg_specs:
        tok, sym = get_contract_info(spec["strike"], spec["type"])
        spec["token"] = tok
        if tok:
            tokens_to_fetch.append(tok)

    # Reuse already fetched LTPs from OI scan first, fetch any missing wing tokens
    live_ltp_map = dict(oi_data.get("ltp_dict", {}))
    missing_tokens = [t for t in tokens_to_fetch if t not in live_ltp_map or live_ltp_map[t] <= 0]
    if missing_tokens:
        try:
            mkt_res = smart_api.getMarketData("LTP", {"NFO": missing_tokens})
            if mkt_res and mkt_res.get("status") and "data" in mkt_res:
                for item in mkt_res["data"].get("fetched", []):
                    live_ltp_map[str(item["symbolToken"])] = float(item["ltp"])
        except Exception:
            pass

    display_legs = []
    for spec in leg_specs:
        tok = spec["token"]
        ltp_val = live_ltp_map.get(tok, 0.0)
        if ltp_val <= 0.5:
            base = verified_baseline_chain.get((spec["strike"], spec["type"]), 130.0)
            mult = 1.0 if dte_days <= 7 else 1.3
            ltp_val = round(base * mult, 2)

        display_legs.append({
            "type": spec["type"], "action": spec["action"], "strike": spec["strike"],
            "token": tok, "premium": ltp_val,
            "readable": f"NIFTY {display_exp} {spec['strike']} {spec['type']}",
            "kite_sym": get_kite_symbol(chosen_exp_date, spec["strike"], spec["type"], valid_expiries),
            "note": spec["note"]
        })

    # --- 10. RISK & PAYOFF COMPUTATION ---
    spot_range = np.linspace(live_spot - 800, live_spot + 800, 300)
    pnl = np.zeros_like(spot_range)
    net_credit = 0.0

    for leg in display_legs:
        k, prem = leg["strike"], leg["premium"]
        net_credit += prem if leg["action"] == "SELL" else -prem
        intrinsic = np.maximum(0, spot_range - k) if leg["type"] == "CE" else np.maximum(0, k - spot_range)
        pnl += (intrinsic - prem) if leg["action"] == "BUY" else (prem - intrinsic)

    max_profit_lot = np.max(pnl) * LOT_SIZE
    max_loss_lot = abs(np.min(pnl)) * LOT_SIZE

    profitable_spots = spot_range[pnl >= 0]
    lower_be = profitable_spots[0] if len(profitable_spots) > 0 else live_spot - 250
    upper_be = profitable_spots[-1] if len(profitable_spots) > 0 else live_spot + 250

    T_years = dte_days / 365.0
    sigma = max(live_vix / 100.0, 0.10)
    stdev = live_spot * sigma * np.sqrt(T_years)
    pop_percent = (norm.cdf((upper_be - live_spot) / stdev) - norm.cdf((lower_be - live_spot) / stdev)) * 100
    rr_ratio = max_loss_lot / max(max_profit_lot, 1)

    # --- SECTION 1: INSTITUTIONAL ANALYTICS DASHBOARD ---
    st.markdown(f"### 📊 Institutional OI & Sentiment Dashboard <span style='font-size:0.78rem; font-weight:500; color:#38bdf8;'>({oi_source_tag})</span>", unsafe_allow_html=True)
    put_oi_str = f"OI: {oi_data['put_wall_oi']:,}" if oi_data["put_wall_oi"] > 0 else "Heavy Put OI Base"
    call_oi_str = f"OI: {oi_data['call_wall_oi']:,}" if oi_data["call_wall_oi"] > 0 else "Heavy Call OI Wall"

    st.markdown(f"""
    <div class="analytics-grid">
        <div class="card">
            <div class="card-label">India VIX</div>
            <div class="card-val" style="color:#f59e0b !important;">{live_vix:.2f}</div>
            <div class="card-sub">Volatility Index</div>
        </div>
        <div class="card">
            <div class="card-label">Live PCR Ratio</div>
            <div class="card-val">{live_pcr:.2f}</div>
            <div class="card-sub">{pcr_sentiment}</div>
        </div>
        <div class="card">
            <div class="card-label">Max Pain Level</div>
            <div class="card-val">₹{live_max_pain}</div>
            <div class="card-sub">Expiry Magnet Point</div>
        </div>
        <div class="card">
            <div class="card-label">Put Support Wall</div>
            <div class="card-val">₹{put_wall}</div>
            <div class="card-sub">{put_oi_str}</div>
        </div>
        <div class="card">
            <div class="card-label">Call Resistance Wall</div>
            <div class="card-val">₹{call_wall}</div>
            <div class="card-sub">{call_oi_str}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- SECTION 2: QUANT STRATEGY & ENTRY CLOCK ---
    st.markdown(f"""
    <div class="section-box" style="background:#1e293b !important; border-color:#334155 !important;">
        <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-bottom:6px; color:#f8fafc !important;">
            <div>🤖 <b style="color:#f8fafc !important;">Active Strategy: <span style="color:#38bdf8 !important;">{strat_name} ({display_exp})</span></b></div>
            <div>⏰ <b style="color:#f8fafc !important;">Entry Clock: <span style="color:{sig_color} !important;">{entry_signal}</span></b></div>
        </div>
        <div style="color:#e2e8f0 !important; font-size:0.83rem; margin-bottom:4px;">💡 {strat_reason}</div>
        <div style="color:#94a3b8 !important; font-size:0.75rem;">Advice: {entry_advice}</div>
    </div>
    """, unsafe_allow_html=True)

    # --- SECTION 3: TRADE EXECUTION & PAYOFF CURVE ---
    col_left, col_right = st.columns([1.1, 1.2])

    with col_left:
        st.markdown("#### 📋 Strategy Legs & Risk Metrics")
        st.markdown(f"""
        <div class="section-box" style="padding:10px;">
            <div style="font-size:0.8rem; color:#cbd5e1 !important; margin-bottom:8px;">
                <b style="color:#f8fafc !important;">Win Probability:</b> {pop_percent:.1f}% &nbsp;|&nbsp; <b style="color:#f8fafc !important;">Lot Size:</b> {LOT_SIZE}
            </div>
            <div style="font-size:0.8rem; color:#10b981 !important; margin-bottom:4px;">🟢 Max Profit: <b style="color:#10b981 !important;">₹{max_profit_lot:,.0f}</b> (+{net_credit:.2f} pts)</div>
            <div style="font-size:0.8rem; color:#ef4444 !important; margin-bottom:4px;">🔴 Max Risk: <b style="color:#ef4444 !important;">₹{max_loss_lot:,.0f}</b> (R:R = 1 : {1/rr_ratio:.2f})</div>
        </div>
        """, unsafe_allow_html=True)

        for idx, leg in enumerate(display_legs, 1):
            badge_color = "#10b981" if leg["action"] == "BUY" else "#ef4444"
            badge_text = "🟢 BUY" if leg["action"] == "BUY" else "🔴 SELL"
            st.markdown(
                f"<div class='leg-row' style='border-left-color:{badge_color};'>"
                f"<div style='color:#f8fafc !important;'><b style='color:#f8fafc !important;'>Leg {idx}:</b> {badge_text} <code>{leg['readable']}</code><br/><span style='color:#94a3b8 !important;font-size:0.75rem'>{leg['note']}</span></div>"
                f"<div style='font-weight:700;color:#f8fafc !important; font-size:0.95rem;'>₹{leg['premium']:.2f}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

        json_legs = sorted(display_legs, key=lambda x: 0 if x["action"] == "BUY" else 1)
        kite_basket = [
            {
                "variety": "regular", "tradingsymbol": leg["kite_sym"], "exchange": "NFO",
                "transaction_type": leg["action"], "order_type": "MARKET", "quantity": LOT_SIZE, "product": "NRML"
            }
            for leg in json_legs
        ]
        with st.expander(f"📋 Zerodha Basket JSON (1 Lot = {LOT_SIZE} Qty — BUY First)", expanded=False):
            st.code(json.dumps(kite_basket, indent=2), language="json")
            
        if st.button("💾 Save Strategy & Strikes to Live Tracker"):
            strategy_payload = {
                "name": strat_name,
                "expiry": display_exp,
                "lot_size": LOT_SIZE,
                "legs": display_legs,
                "max_profit": float(max_profit_lot),
                "max_loss": float(max_loss_lot),
                "entry_spot": float(live_spot),
                "time": ist_time_str,
                "last_alert_state": "HOLD"
            }
            st.session_state.saved_strategies.append(strategy_payload)
            save_strategies_to_disk(st.session_state.saved_strategies)
            if TG_BOT_TOKEN and TG_CHAT_ID:
                legs_txt = "\n".join([f"• {l['action']} {l['readable']} @ ₹{l['premium']:.2f}" for l in display_legs])
                send_telegram_alert(
                    f"💾 <b>New Strategy Saved!</b>\n"
                    f"<b>{strat_name} ({display_exp})</b>\n"
                    f"Entry Spot: ₹{live_spot:,.2f}\n"
                    f"{legs_txt}\n"
                    f"Max Profit: ₹{max_profit_lot:,.0f} | Max Risk: ₹{max_loss_lot:,.0f}"
                )
            st.success("✅ Strategy + Strike Prices permanently save ho gaye hain!")
            st.rerun()

        st.caption(f"🔒 Margin Safe: BUY orders sorted first | Synced: {ist_time_str}")

    with col_right:
        st.markdown(f"#### 📈 Payoff Curve & Breakevens ({display_exp})")
        fig, ax = plt.subplots(figsize=(6.8, 3.4), facecolor="#0b0f19")
        ax.set_facecolor("#111827")
        ax.plot(spot_range, pnl * LOT_SIZE, color="#38bdf8", linewidth=2.2, label="Total P&L (₹)")
        ax.axhline(0, color="#64748b", linestyle="--", linewidth=0.9)
        ax.axvline(live_spot, color="#f59e0b", linestyle=":", label=f"Spot ({live_spot:.0f})")
        ax.axvline(lower_be, color="#94a3b8", linestyle="--", alpha=0.7)
        ax.axvline(upper_be, color="#94a3b8", linestyle="--", alpha=0.7)

        ax.fill_between(spot_range, pnl * LOT_SIZE, 0, where=(pnl >= 0), color="#10b981", alpha=0.35, interpolate=True)
        ax.fill_between(spot_range, pnl * LOT_SIZE, 0, where=(pnl < 0), color="#ef4444", alpha=0.35, interpolate=True)

        ax.tick_params(colors="#94a3b8", labelsize=8.5)
        for spine in ax.spines.values():
            spine.set_color("#1f2937")

        ax.set_xlabel(f"Nifty Expiry Spot | Breakevens: {lower_be:.0f} — {upper_be:.0f}", color="#94a3b8", fontsize=9)
        ax.set_ylabel(f"Total P&L (₹ for {LOT_SIZE} Qty)", color="#94a3b8", fontsize=9)
        ax.grid(True, color="#1f2937", linestyle=":", alpha=0.6)
        ax.legend(facecolor="#111827", edgecolor="#1f2937", labelcolor="#e2e8f0", loc="upper right", fontsize=8)
        plt.tight_layout(pad=0.5)

        st.pyplot(fig)
        plt.close(fig)
