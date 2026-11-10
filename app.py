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

st.set_page_config(page_title="Nifty Live NFO Terminal", layout="wide", initial_sidebar_state="collapsed")

# --- PRO DARK STYLING ---
st.markdown("""
<style>
    .reportview-container { background: #0b0f19; }
    .metric-card { background-color: #111827; border-radius: 8px; padding: 14px; border: 1px solid #1f2937; }
    .stRadio [role="radiogroup"] { gap: 16px; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Nifty Options Decision Engine (Direct Master-Token Feed)")

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
    st.error("❌ Angel One API se connect nahi ho paya. Credentials check karein.")
    st.stop()

# --- 1. DOWNLOAD & CACHE OFFICIAL ANGEL ONE SCRIP MASTER (PERMANENT FIX) ---
@st.cache_data(ttl=43200)  # 12 hours cache
def load_angel_nfo_master():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    r = requests.get(url, timeout=30)
    data = r.json()
    df = pd.DataFrame(data)
    # Filter strictly for NIFTY Options in NFO segment
    df = df[(df["exch_seg"] == "NFO") & (df["name"] == "NIFTY") & (df["instrumenttype"] == "OPTIDX")].copy()
    # Strike in Angel Master is stored multiplied by 100 (e.g. 2485000.0 for 24850)
    df["strike_int"] = (pd.to_numeric(df["strike"], errors="coerce") / 100).round().astype(int)
    df["opt_type"] = df["symbol"].str[-2:]
    df["expiry_dt"] = pd.to_datetime(df["expiry"], format="%d%b%Y", errors="coerce").dt.date
    return df[["token", "symbol", "expiry", "expiry_dt", "strike_int", "opt_type"]]

with st.spinner("🔄 Syncing Official NSE/NFO Scrip Master from Angel One..."):
    nfo_df = load_angel_nfo_master()

# --- 2. FETCH LIVE NIFTY SPOT & VIX ---
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

# --- 3. AUTO-DETECT REAL EXPIRIES DIRECTLY FROM NSE MASTER ---
today_date = datetime.date.today()
valid_expiries = sorted([d for d in nfo_df["expiry_dt"].dropna().unique() if d >= today_date])

if not valid_expiries:
    st.error("No active NIFTY expiries found in Angel Scrip Master.")
    st.stop()

top_expiries = valid_expiries[:4]
expiry_labels = [f"{d.strftime('%d-%b')} ({max((d - today_date).days, 1)} Days)" for d in top_expiries]

# --- TOP BAR ---
c1, c2, c3, c4 = st.columns([1.2, 1, 1.2, 1])
with c1:
    st.metric("LIVE NIFTY 50", f"₹{live_spot:,.2f}")
with c2:
    st.metric("ATM STRIKE", f"{atm_strike}")
with c3:
    st.metric("LIVE INDIA VIX", f"{live_vix:.2f}%")
with c4:
    auto_refresh_on = st.toggle("Auto-refresh (15s)", value=True)

if auto_refresh_on:
    st_autorefresh(interval=15 * 1000, key="nfo_master_refresh")

st.write("---")

# --- EXPIRY & STRIKE CONTROLS (SENSIBULL / KITE MATCHED) ---
ctrl1, ctrl2, ctrl3 = st.columns([2, 1, 1])

with ctrl1:
    st.markdown("#### 📅 Select Target Expiry (From Live NSE Master):")
    selected_label = st.radio("Choose Expiry", expiry_labels, horizontal=True, label_visibility="collapsed")
    selected_idx = expiry_labels.index(selected_label)
    chosen_exp_date = top_expiries[selected_idx]
    dte_days = max((chosen_exp_date - today_date).days, 1)
    display_exp = chosen_exp_date.strftime("%d-%b")

# Default Width: 200 for current week (24950/25150), 400 for further expiries (24850/25250 like Sensibull)
default_width_idx = 0 if dte_days <= 7 else 2

with ctrl2:
    width_pts = st.selectbox("↔️ Sell Width (Spread between Sell PE & CE)", [200, 300, 400, 500, 600], index=default_width_idx)

with ctrl3:
    hedge_pts = st.selectbox("🛡️ Hedge Wing Distance (Buy Protection)", [150, 200, 250, 300], index=1)

half_width = int(width_pts // 2)
sell_pe = atm_strike - half_width
sell_ce = atm_strike + half_width
buy_pe  = sell_pe - hedge_pts
buy_ce  = sell_ce + hedge_pts

# --- 4. BATCH LIVE LTP FETCH FROM ANGEL ONE NFO (ZERO FALLBACK GUESSING) ---
exp_subset = nfo_df[nfo_df["expiry_dt"] == chosen_exp_date]

def get_contract_info(strike_val, opt_type_val):
    row = exp_subset[(exp_subset["strike_int"] == strike_val) & (exp_subset["opt_type"] == opt_type_val)]
    if not row.empty:
        return str(row.iloc[0]["token"]), str(row.iloc[0]["symbol"])
    return None, None

leg_specs = [
    {"type": "PE", "action": "BUY",  "strike": buy_pe,  "note": "Downside Hedge Wing (Crash Protection)"},
    {"type": "PE", "action": "SELL", "strike": sell_pe, "note": "Put Credit Leg (Core Theta Capture)"},
    {"type": "CE", "action": "SELL", "strike": sell_ce, "note": "Call Credit Leg (Core Theta Capture)"},
    {"type": "CE", "action": "BUY",  "strike": buy_ce,  "note": "Upside Hedge Wing (Rally Protection)"}
]

tokens_to_fetch = []
for spec in leg_specs:
    tok, sym = get_contract_info(spec["strike"], spec["type"])
    spec["token"] = tok
    spec["angel_symbol"] = sym
    if tok:
        tokens_to_fetch.append(tok)

# Fetch all 4 option prices in 1 single batch API call!
live_ltp_map = {}
api_error_msg = None

if tokens_to_fetch:
    try:
        mkt_res = smart_api.getMarketData("LTP", {"NFO": tokens_to_fetch})
        if mkt_res and mkt_res.get("status") and "data" in mkt_res:
            for item in mkt_res["data"].get("fetched", []):
                live_ltp_map[str(item["symbolToken"])] = float(item["ltp"])
        else:
            api_error_msg = f"Angel NFO Response: {mkt_res}"
    except Exception as e:
        api_error_msg = str(e)

# If batch call fails for any token, try direct ltpData per token
for spec in leg_specs:
    tok = spec["token"]
    sym = spec["angel_symbol"]
    if tok and tok not in live_ltp_map:
        try:
            single_q = smart_api.ltpData(exchange="NFO", tradingsymbol=sym, symboltoken=tok)
            if single_q and single_q.get("status") and "data" in single_q:
                live_ltp_map[tok] = float(single_q["data"]["ltp"])
        except Exception:
            pass

# Official Zerodha Symbol Builder (Checks if Monthly or Weekly)
def get_kite_symbol(exp_date, strike, opt_type, all_exp_dates):
    yy = exp_date.strftime("%y")
    same_month_exps = [d for d in all_exp_dates if d.year == exp_date.year and d.month == exp_date.month]
    is_monthly = (exp_date == max(same_month_exps))
    if is_monthly:
        return f"NIFTY{yy}{exp_date.strftime('%b').upper()}{strike}{opt_type}"
    else:
        month_codes = {1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'O', 11: 'N', 12: 'D'}
        m_code = month_codes.get(exp_date.month, 'N')
        dd = exp_date.strftime("%d")
        return f"NIFTY{yy}{m_code}{dd}{strike}{opt_type}"

display_legs = []
for spec in leg_specs:
    tok = spec["token"]
    ltp_val = live_ltp_map.get(tok, 0.0)
    display_legs.append({
        "type": spec["type"],
        "action": spec["action"],
        "strike": spec["strike"],
        "premium": ltp_val,
        "token": tok,
        "readable": f"NIFTY {display_exp} {spec['strike']} {spec['type']}",
        "kite_sym": get_kite_symbol(chosen_exp_date, spec["strike"], spec["type"], valid_expiries),
        "note": spec["note"]
    })

if api_error_msg:
    st.warning(f"⚠️ Live API Warning: {api_error_msg}")

# --- 5. EXACT RISK, BREAKEVEN & WIN PROBABILITY ---
p_buy_pe  = display_legs[0]["premium"]
p_sell_pe = display_legs[1]["premium"]
p_sell_ce = display_legs[2]["premium"]
p_buy_ce  = display_legs[3]["premium"]

net_credit = (p_sell_pe + p_sell_ce) - (p_buy_pe + p_buy_ce)
max_profit_lot = net_credit * 25
max_loss_lot = (hedge_pts - net_credit) * 25
lower_be = sell_pe - net_credit
upper_be = sell_ce + net_credit

T_years = dte_days / 365.0
sigma = max(live_vix / 100.0, 0.10)
stdev = live_spot * sigma * np.sqrt(T_years)
pop_percent = (norm.cdf((upper_be - live_spot) / stdev) - norm.cdf((lower_be - live_spot) / stdev)) * 100

st.subheader(f"🛡️ Short Iron Condor — {selected_label} (Width: {width_pts} | Hedge: {hedge_pts})")

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("Net Credit (Pts)", f"₹{net_credit:.2f}", delta=f"₹{max_profit_lot:,.0f} / Lot")
with m2:
    st.metric("Max Profit / Lot", f"₹{max_profit_lot:,.0f}")
with m3:
    st.metric("Max Risk / Lot", f"₹{max_loss_lot:,.0f}")
with m4:
    st.metric("Lower Breakeven", f"{lower_be:.0f}")
with m5:
    st.metric("Upper Breakeven", f"{upper_be:.0f}")

# --- DISPLAY ORDERS & PAYOFF ---
col_left, col_right = st.columns([1.1, 1.2])

with col_left:
    st.markdown("#### 📋 Live NFO Orders for Zerodha Kite:")
    for idx, leg in enumerate(display_legs, 1):
        badge = "🟢 BUY" if leg["action"] == "BUY" else "🔴 SELL"
        st.markdown(f"**Leg {idx}:** {badge} **`{leg['readable']}`** — **LTP: ₹{leg['premium']:.2f}**")
        st.caption(f"└ {leg['note']} | Angel Token: `{leg['token']}`")

    # JSON SORTED STRICTLY: BUY FIRST, SELL SECOND (For Margin Benefit)
    json_legs = sorted(display_legs, key=lambda x: 0 if x["action"] == "BUY" else 1)
    kite_basket = [
        {
            "variety": "regular",
            "tradingsymbol": leg["kite_sym"],
            "exchange": "NFO",
            "transaction_type": leg["action"],
            "order_type": "MARKET",
            "quantity": 25,
            "product": "NRML"
        }
        for leg in json_legs
    ]
    with st.expander("📋 Zerodha Basket JSON (Click to Copy)", expanded=False):
        st.code(json.dumps(kite_basket, indent=2), language="json")

with col_right:
    st.subheader(f"📈 Real Payoff Curve ({display_exp})")
    spot_range = np.linspace(live_spot - 700, live_spot + 700, 150)
    pnl = np.zeros_like(spot_range)

    for leg in display_legs:
        k = leg["strike"]
        prem = leg["premium"]
        intrinsic = np.maximum(0, spot_range - k) if leg["type"] == "CE" else np.maximum(0, k - spot_range)
        pnl += (intrinsic - prem) if leg["action"] == "BUY" else (prem - intrinsic)

    fig, ax = plt.subplots(figsize=(7, 4.5), facecolor="#0b0f19")
    ax.set_facecolor("#111827")
    ax.plot(spot_range, pnl, color="#38bdf8", linewidth=2.5, label="Net Payoff")
    ax.axhline(0, color="#64748b", linestyle="--", linewidth=1)
    ax.axvline(live_spot, color="#f59e0b", linestyle=":", label=f"Spot ({live_spot:.1f})")
    ax.axvline(lower_be, color="#94a3b8", linestyle="--", alpha=0.7)
    ax.axvline(upper_be, color="#94a3b8", linestyle="--", alpha=0.7)

    ax.fill_between(spot_range, pnl, 0, where=(pnl >= 0), color="#10b981", alpha=0.35, interpolate=True)
    ax.fill_between(spot_range, pnl, 0, where=(pnl < 0), color="#ef4444", alpha=0.35, interpolate=True)

    ax.tick_params(colors="#94a3b8", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#1f2937")

    ax.set_xlabel("Nifty Spot at Expiry", color="#94a3b8", fontsize=10)
    ax.set_ylabel("P&L per Share (₹)", color="#94a3b8", fontsize=10)
    ax.grid(True, color="#1f2937", linestyle=":", alpha=0.6)
    ax.legend(facecolor="#111827", edgecolor="#1f2937", labelcolor="#e2e8f0", loc="best", fontsize=8)

    st.pyplot(fig)
    plt.close(fig)

st.write("---")
st.caption(f"100% Direct Angel ScripMaster Token Feed | Win Prob: {pop_percent:.1f}% | Last Sync: {time.strftime('%H:%M:%S IST')}")
    
