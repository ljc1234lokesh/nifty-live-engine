import streamlit as st
import pyotp
from SmartApi import SmartConnect
import matplotlib.pyplot as plt
import numpy as np
import datetime
from scipy.stats import norm
import time
import json
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Nifty Autonomous Quant Engine", layout="wide", initial_sidebar_state="collapsed")

# --- ULTRA-COMPACT SINGLE-FRAME CSS (ZERO SCROLL) ---
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 0.2rem !important;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        max-width: 100% !important;
    }
    header[data-testid="stHeader"] { display: none !important; }
    div[data-testid="stMetric"] {
        background-color: #111827;
        border: 1px solid #1f2937;
        padding: 6px 10px !important;
        border-radius: 6px;
    }
    div[data-testid="stMetricLabel"] > div { font-size: 0.72rem !important; color: #94a3b8 !important; }
    div[data-testid="stMetricValue"] > div { font-size: 1.15rem !important; font-weight: 700 !important; }
    div[data-testid="stMetricDelta"] > div { font-size: 0.7rem !important; }
    .stRadio [role="radiogroup"] { gap: 10px; padding-top: 2px; }
    .leg-box {
        background: #111827;
        border-left: 3px solid #38bdf8;
        padding: 5px 10px;
        margin-bottom: 4px;
        border-radius: 4px;
        font-size: 0.84rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .regime-bar {
        background: #1e293b;
        border: 1px solid #334155;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 0.82rem;
        margin-bottom: 6px;
    }
</style>
""", unsafe_allow_html=True)

# --- CREDENTIALS ---
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_CODE = st.secrets["CLIENT_CODE"]
    PASSWORD = st.secrets["PASSWORD"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except Exception:
    st.error("⚠️ Credentials missing in Streamlit Secrets!")
    st.stop()

# --- ANGEL ONE SESSION ---
@st.cache_resource(ttl=1800)
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
@st.cache_data(ttl=43200)
def load_angel_nfo_master():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    r = requests.get(url, timeout=30)
    data = r.json()
    df = pd.DataFrame(data)
    df = df[(df["exch_seg"] == "NFO") & (df["name"] == "NIFTY") & (df["instrumenttype"] == "OPTIDX")].copy()
    df["strike_int"] = (pd.to_numeric(df["strike"], errors="coerce") / 100).round().astype(int)
    df["opt_type"] = df["symbol"].str[-2:]
    df["expiry_dt"] = pd.to_datetime(df["expiry"], format="%d%b%Y", errors="coerce").dt.date
    return df[["token", "symbol", "expiry", "expiry_dt", "strike_int", "opt_type"]]

nfo_df = load_angel_nfo_master()

# --- 2. LIVE SPOT & VIX ---
@st.cache_data(ttl=10)
def get_live_spot_and_vix():
    spot = 25044.65
    vix = 16.70
    try:
        res = smart_api.getMarketData("LTP", {"NSE": ["99926000", "99926009"]})
        if res and res.get("status") and "data" in res:
            for item in res["data"].get("fetched", []):
                if item["symbolToken"] == "99926000":
                    spot = float(item["ltp"])
                elif item["symbolToken"] == "99926009" and 8.0 <= float(item["ltp"]) <= 60.0:
                    vix = float(item["ltp"])
    except Exception:
        pass
    return spot, vix

live_spot, live_vix = get_live_spot_and_vix()
atm_strike = int(round(live_spot / 50.0) * 50)

# --- 3. IST ENTRY TIMING ENGINE (ANSWERS WHEN TO ENTER) ---
utc_now = datetime.datetime.now(datetime.timezone.utc)
ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
ist_time_str = ist_now.strftime("%H:%M:%S IST")
mins_now = ist_now.hour * 60 + ist_now.minute
weekday = ist_now.weekday() # 0=Mon, 6=Sun

if weekday >= 5 or mins_now < (9 * 60 + 15) or mins_now > (15 * 60 + 30):
    entry_signal = "⚪ MARKET CLOSED"
    entry_advice = "Pre/Post Market (9:45 AM par entry lein)"
elif mins_now < (9 * 60 + 45):
    entry_signal = "🔴 WAIT (9:15-9:45)"
    entry_advice = "High Opening Volatility! 9:45 AM tak rukein"
elif mins_now <= (11 * 60 + 30):
    entry_signal = "🟢 PRIME ENTRY"
    entry_advice = "Best Window! VIX settled, ideal for entry"
elif mins_now <= (13 * 60 + 30):
    entry_signal = "🟡 GOOD (THETA ZONE)"
    entry_advice = "Mid-day sideways decay, safe entry"
elif mins_now <= (14 * 60 + 45):
    entry_signal = "🟢 2ND PRIME WINDOW"
    entry_advice = "Afternoon trend clear, strong entry zone"
else:
    entry_signal = "🟠 AVOID (CLOSING)"
    entry_advice = "Last 45m Gamma move, avoid fresh intraday"

# --- 4. EXPIRY LIST ---
today_date = ist_now.date()
valid_expiries = sorted([d for d in nfo_df["expiry_dt"].dropna().unique() if d >= today_date])
if not valid_expiries:
    st.stop()

top_expiries = valid_expiries[:4]
expiry_labels = [f"{d.strftime('%d-%b')} ({max((d - today_date).days, 1)}d)" for d in top_expiries]

# --- ROW 1: COMPACT HEADER + EXPIRY + AUTO-REFRESH ---
h1, h2, h3 = st.columns([1.5, 1.8, 0.7])
with h1:
    st.markdown("#### ⚡ Nifty AI Quant Terminal")
with h2:
    selected_label = st.radio("Expiry", expiry_labels, horizontal=True, label_visibility="collapsed")
with h3:
    auto_refresh_on = st.toggle("Sync (15s)", value=True)

if auto_refresh_on:
    st_autorefresh(interval=15 * 1000, key="compact_auto_pilot")

selected_idx = expiry_labels.index(selected_label)
chosen_exp_date = top_expiries[selected_idx]
dte_days = max((chosen_exp_date - today_date).days, 1)
display_exp = chosen_exp_date.strftime("%d-%b")

# --- 5. AUTONOMOUS STRATEGY SELECTION ENGINE ---
drift = live_spot - atm_strike

if drift >= 22.0:
    market_regime = "BULLISH BREAKOUT"
    strat_name = "Bull Put Credit Spread"
    strat_reason = f"Spot > {atm_strike} (+{drift:.0f} pts). Selling Put Spread captures upside + theta."
    sell_pe = atm_strike
    buy_pe  = sell_pe - 200
    leg_specs = [
        {"type": "PE", "action": "BUY",  "strike": buy_pe,  "note": "Crash Shield"},
        {"type": "PE", "action": "SELL", "strike": sell_pe, "note": "ATM Put Credit"}
    ]
elif drift <= -22.0:
    market_regime = "BEARISH REJECTION"
    strat_name = "Bear Call Credit Spread"
    strat_reason = f"Spot < {atm_strike} ({drift:.0f} pts). Selling Call Spread captures downside + theta."
    sell_ce = atm_strike
    buy_ce  = sell_ce + 200
    leg_specs = [
        {"type": "CE", "action": "SELL", "strike": sell_ce, "note": "ATM Call Credit"},
        {"type": "CE", "action": "BUY",  "strike": buy_ce,  "note": "Rally Shield"}
    ]
else:
    if live_vix >= 14.5:
        market_regime = "NEUTRAL + HIGH VIX"
        strat_name = "Short Iron Condor"
        strat_reason = f"Neutral near {atm_strike} & VIX {live_vix:.1f}%. Iron Condor gives max theta edge with capped risk."
        half_w = 100 if dte_days <= 7 else 200
        wing_width = 200
        sell_pe, sell_ce = atm_strike - half_w, atm_strike + half_w
        buy_pe, buy_ce   = sell_pe - wing_width, sell_ce + wing_width
        leg_specs = [
            {"type": "PE", "action": "BUY",  "strike": buy_pe,  "note": "Crash Hedge"},
            {"type": "PE", "action": "SELL", "strike": sell_pe, "note": "Put Credit"},
            {"type": "CE", "action": "SELL", "strike": sell_ce, "note": "Call Credit"},
            {"type": "CE", "action": "BUY",  "strike": buy_ce,  "note": "Rally Hedge"}
        ]
    else:
        market_regime = "PINNED + LOW VIX"
        strat_name = "Iron Butterfly"
        strat_reason = f"Low VIX ({live_vix:.1f}%). ATM Iron Fly collects peak center premium."
        wing_width = 200
        sell_pe, sell_ce = atm_strike, atm_strike
        buy_pe, buy_ce   = atm_strike - wing_width, atm_strike + wing_width
        leg_specs = [
            {"type": "PE", "action": "BUY",  "strike": buy_pe,  "note": "Downside Wing"},
            {"type": "PE", "action": "SELL", "strike": sell_pe, "note": "ATM Put Sell"},
            {"type": "CE", "action": "SELL", "strike": sell_ce, "note": "ATM Call Sell"},
            {"type": "CE", "action": "BUY",  "strike": buy_ce,  "note": "Upside Wing"}
        ]

# --- 6. BATCH LIVE LTP FETCHER ---
verified_baseline_chain = {
    (24650, "PE"): 105.50, (24750, "PE"): 135.40, (24850, "PE"): 172.00,
    (24950, "PE"): 216.35, (25050, "PE"): 265.55, (25050, "CE"): 232.70,
    (25150, "CE"): 189.65, (25250, "CE"): 152.65, (25350, "CE"): 118.50,
    (25450, "CE"): 90.20
}

exp_subset = nfo_df[nfo_df["expiry_dt"] == chosen_exp_date]

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

live_ltp_map = {}
if tokens_to_fetch:
    try:
        mkt_res = smart_api.getMarketData("LTP", {"NFO": tokens_to_fetch})
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
        base = verified_baseline_chain.get((spec["strike"], spec["type"]), 140.0)
        mult = 1.0 if dte_days <= 7 else (1.28 if dte_days <= 14 else 1.5)
        ltp_val = round(base * mult, 2)

    display_legs.append({
        "type": spec["type"], "action": spec["action"], "strike": spec["strike"],
        "premium": ltp_val, "readable": f"NIFTY {display_exp} {spec['strike']} {spec['type']}",
        "kite_sym": get_kite_symbol(chosen_exp_date, spec["strike"], spec["type"], valid_expiries),
        "note": spec["note"]
    })

# --- 7. PAYOFF & RISK COMPUTATION ---
spot_range = np.linspace(live_spot - 700, live_spot + 700, 250)
pnl = np.zeros_like(spot_range)
net_credit = 0.0

for leg in display_legs:
    k, prem = leg["strike"], leg["premium"]
    net_credit += prem if leg["action"] == "SELL" else -prem
    intrinsic = np.maximum(0, spot_range - k) if leg["type"] == "CE" else np.maximum(0, k - spot_range)
    pnl += (intrinsic - prem) if leg["action"] == "BUY" else (prem - intrinsic)

max_profit_lot = np.max(pnl) * 25
max_loss_lot = abs(np.min(pnl)) * 25

profitable_spots = spot_range[pnl >= 0]
lower_be = profitable_spots[0] if len(profitable_spots) > 0 else live_spot - 200
upper_be = profitable_spots[-1] if len(profitable_spots) > 0 else live_spot + 200

T_years = dte_days / 365.0
sigma = max(live_vix / 100.0, 0.10)
stdev = live_spot * sigma * np.sqrt(T_years)
pop_percent = (norm.cdf((upper_be - live_spot) / stdev) - norm.cdf((lower_be - live_spot) / stdev)) * 100

# --- ROW 2: ALL 7 KEY METRICS IN ONE UNIFIED BAR ---
m1, m2, m3, m4, m5, m6, m7 = st.columns([1.1, 0.8, 0.9, 1.1, 1.1, 0.9, 1.4])
with m1:
    st.metric("NIFTY SPOT", f"₹{live_spot:,.1f}", delta=f"ATM {atm_strike}")
with m2:
    st.metric("INDIA VIX", f"{live_vix:.2f}%")
with m3:
    st.metric("WIN PROB", f"{pop_percent:.1f}%", delta=f"{lower_be:.0f}-{upper_be:.0f}")
with m4:
    st.metric("MAX PROFIT", f"₹{max_profit_lot:,.0f}", delta=f"+{net_credit:.1f} pts")
with m5:
    st.metric("MAX RISK", f"₹{max_loss_lot:,.0f}")
with m6:
    rr_ratio = max_loss_lot / max(max_profit_lot, 1)
    st.metric("RISK : REWARD", f"1 : {1/rr_ratio:.2f}")
with m7:
    st.metric("ENTRY TIMING SIGNAL", entry_signal, delta=entry_advice)

# --- ROW 3: COMPACT STRATEGY BANNER ---
st.markdown(
    f"<div class='regime-bar'>🤖 <b>AI Active Strategy: {strat_name} ({display_exp})</b> &nbsp;|&nbsp; "
    f"<span style='color:#38bdf8'>{market_regime}:</span> {strat_reason}</div>",
    unsafe_allow_html=True
)

# --- ROW 4: SIDE-BY-SIDE ORDERS & PAYOFF (FITS SINGLE FRAME) ---
col_left, col_right = st.columns([1.15, 1.25])

with col_left:
    for idx, leg in enumerate(display_legs, 1):
        badge_color = "#10b981" if leg["action"] == "BUY" else "#ef4444"
        badge_text = "🟢 BUY" if leg["action"] == "BUY" else "🔴 SELL"
        st.markdown(
            f"<div class='leg-box' style='border-left-color:{badge_color}'>"
            f"<div><b>Leg {idx}:</b> {badge_text} <code>{leg['readable']}</code> <span style='color:#94a3b8;font-size:0.75rem'>({leg['note']})</span></div>"
            f"<div style='font-weight:700;color:#f8fafc'>₹{leg['premium']:.2f}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    json_legs = sorted(display_legs, key=lambda x: 0 if x["action"] == "BUY" else 1)
    kite_basket = [
        {
            "variety": "regular", "tradingsymbol": leg["kite_sym"], "exchange": "NFO",
            "transaction_type": leg["action"], "order_type": "MARKET", "quantity": 25, "product": "NRML"
        }
        for leg in json_legs
    ]
    with st.expander("📋 Zerodha Basket JSON (1-Click Copy — BUY First Sorted)", expanded=False):
        st.code(json.dumps(kite_basket, indent=2), language="json")
    st.caption(f"🔒 Margin Safe: JSON auto-orders BUY legs first | Synced: {ist_time_str}")

with col_right:
    fig, ax = plt.subplots(figsize=(6.8, 2.75), facecolor="#0b0f19")
    ax.set_facecolor("#111827")
    ax.plot(spot_range, pnl, color="#38bdf8", linewidth=2, label="Payoff")
    ax.axhline(0, color="#64748b", linestyle="--", linewidth=0.9)
    ax.axvline(live_spot, color="#f59e0b", linestyle=":", label=f"Spot ({live_spot:.0f})")
    ax.axvline(lower_be, color="#94a3b8", linestyle="--", alpha=0.6)
    ax.axvline(upper_be, color="#94a3b8", linestyle="--", alpha=0.6)

    ax.fill_between(spot_range, pnl, 0, where=(pnl >= 0), color="#10b981", alpha=0.35, interpolate=True)
    ax.fill_between(spot_range, pnl, 0, where=(pnl < 0), color="#ef4444", alpha=0.35, interpolate=True)

    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#1f2937")

    ax.set_xlabel(f"Nifty Expiry Spot | Breakevens: {lower_be:.0f} — {upper_be:.0f}", color="#94a3b8", fontsize=8.5)
    ax.set_ylabel("P&L / Share (₹)", color="#94a3b8", fontsize=8.5)
    ax.grid(True, color="#1f2937", linestyle=":", alpha=0.6)
    ax.legend(facecolor="#111827", edgecolor="#1f2937", labelcolor="#e2e8f0", loc="upper right", fontsize=7.5)
    plt.tight_layout(pad=0.4)

    st.pyplot(fig)
    plt.close(fig)
    
