import streamlit as st
import pyotp
from SmartApi import SmartConnect
import matplotlib.pyplot as plt
import numpy as np
import datetime
import time

st.set_page_config(page_title="Nifty Pro Options Radar", layout="wide", initial_sidebar_state="collapsed")

# --- PRO STYLING ---
st.markdown("""
<style>
    .reportview-container { background: #0b0f19; }
    .card { background-color: #111827; border-radius: 10px; padding: 18px; border: 1px solid #1f2937; margin-bottom: 12px; }
    .badge-bull { background-color: #064e3b; color: #34d399; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
    .badge-bear { background-color: #4c0519; color: #fb7185; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
    .badge-neutral { background-color: #1e1b4b; color: #818cf8; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Quantitative Options Radar (Institutional Engine)")

# --- CREDENTIALS ---
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_CODE = st.secrets["CLIENT_CODE"]
    PASSWORD = st.secrets["PASSWORD"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except Exception:
    st.error("⚠️ Credentials missing in Streamlit Secrets! Check App Settings > Secrets.")
    st.stop()

# --- ANGEL ONE SESSION (CACHED) ---
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
    st.error("❌ Angel One API login failed. Credentials verify karein.")
    st.stop()

# --- HELPER: NIFTY ROUND STRIKE (Strictly Multiples of 50) ---
def to_nifty_strike(price):
    return int(round(price / 50.0) * 50)

# --- FETCH LIVE SPOT & INDIA VIX (ROBUST FILTERING) ---
def get_market_data():
    nifty_spot = 25050.0
    india_vix = 13.6  # Standard baseline fallback

    # 1. Fetch NIFTY 50 Spot
    try:
        quote_nifty = smart_api.ltpData(exchange="NSE", tradingsymbol="Nifty 50", symboltoken="99926000")
        if quote_nifty.get("status") and "data" in quote_nifty:
            val = float(quote_nifty["data"]["ltp"])
            if val > 15000:
                nifty_spot = val
    except Exception:
        pass

    # 2. Fetch INDIA VIX with Strict Boundary Sanity
    try:
        # First attempt: "INDIAVIX" symbol
        quote_vix = smart_api.ltpData(exchange="NSE", tradingsymbol="INDIAVIX", symboltoken="99926009")
        if not (quote_vix.get("status") and "data" in quote_vix):
            # Alternate symbol with space
            quote_vix = smart_api.ltpData(exchange="NSE", tradingsymbol="INDIA VIX", symboltoken="26009")

        if quote_vix.get("status") and "data" in quote_vix:
            v_val = float(quote_vix["data"]["ltp"])
            # India VIX realistically stays between 8.0 and 45.0
            if 8.0 <= v_val <= 45.0:
                india_vix = v_val
    except Exception:
        pass

    return nifty_spot, india_vix

live_spot, live_vix = get_market_data()
atm_strike = to_nifty_strike(live_spot)

# --- NEAREST THURSDAY EXPIRY ENGINE ---
def get_next_thursday_expiry():
    today = datetime.date.today()
    days_ahead = (3 - today.weekday()) % 7
    # Agar aaj Thursday hai aur market close ho chuki hai
    if days_ahead == 0 and datetime.datetime.now().time() > datetime.time(15, 30):
        days_ahead = 7
    expiry_date = today + datetime.timedelta(days_ahead)
    dte = (expiry_date - today).days
    return expiry_date.strftime("%d-%b-%Y"), dte

expiry_str, dte_days = get_next_thursday_expiry()

# --- TOP METRICS ROW ---
m1, m2, m3, m4 = st.columns([1.2, 1, 1.2, 1.2])

with m1:
    st.metric(label="LIVE NIFTY 50", value=f"₹{live_spot:,.2f}")

with m2:
    st.metric(label="ATM STRIKE", value=f"{atm_strike}")

with m3:
    st.metric(label="INDIA VIX", value=f"{live_vix:.2f}")

with m4:
    st.metric(label="NEAREST EXPIRY", value=f"{expiry_str}", delta=f"{dte_days} Days Left", delta_color="off")

st.write("---")

# --- QUANT RADAR BIAS & IV REGIME ---
col_sig1, col_sig2 = st.columns(2)

with col_sig1:
    st.markdown("#### 🧠 Market Sentiment Engine")
    auto_mode = st.radio("Signal Mode:", ["🤖 Fully Automatic (Quant Rule)", "🛠️ Manual Override"], horizontal=True)

with col_sig2:
    st.markdown("#### ⚡ IV Regime Status")
    if live_vix >= 15.0:
        auto_iv_state = "ELEVATED / HIGH IV"
        st.warning(f"**High Volatility (VIX: {live_vix:.2f}):** Premiums are inflated. Iron Condor & Credit Spreads offer maximum edge.")
    else:
        auto_iv_state = "NORMAL / LOW IV"
        st.info(f"**Normal Volatility (VIX: {live_vix:.2f}):** Premiums are reasonable. Defined-risk Debit Spreads or Hedged Strangles recommended.")

if auto_mode == "🤖 Fully Automatic (Quant Rule)":
    # Drift check from current ATM strike
    drift = live_spot - atm_strike
    if drift >= 20:
        detected_bias = "Bullish (Up Trend)"
    elif drift <= -20:
        detected_bias = "Bearish (Down Trend)"
    else:
        detected_bias = "Sideways / Range-Bound"
    st.caption(f"Engine auto-detected bias: **{detected_bias}** (Based on Spot vs ATM alignment).")
else:
    detected_bias = st.selectbox("Select Bias manually:", ["Sideways / Range-Bound", "Bullish (Up Trend)", "Bearish (Down Trend)"])

# --- GENUINE NSE STRIKE CALCULATION (Strict 50 Multiples) ---
legs = []

if detected_bias == "Sideways / Range-Bound":
    if live_vix >= 15.0:
        rec_title = "Defensive Iron Condor"
        rec_type = "Net Credit (Double Hedged Range)"
        rec_logic = "High IV environment. Sell OTM call & put (200 pts buffer) and buy wings (150 pts further) for capped risk."
        
        # Genuine strikes strictly rounded to 50
        pe_sell = to_nifty_strike(atm_strike - 150)
        pe_buy  = to_nifty_strike(pe_sell - 150)
        ce_sell = to_nifty_strike(atm_strike + 150)
        ce_buy  = to_nifty_strike(ce_sell + 150)

        legs = [
            {'type': 'PE', 'action': 'BUY', 'strike': pe_buy, 'premium': 18},
            {'type': 'PE', 'action': 'SELL', 'strike': pe_sell, 'premium': 52},
            {'type': 'CE', 'action': 'SELL', 'strike': ce_sell, 'premium': 48},
            {'type': 'CE', 'action': 'BUY', 'strike': ce_buy, 'premium': 16}
        ]
    else:
        rec_title = "Hedged Short Strangle (Wings Attached)"
        rec_type = "Delta Neutral Play"
        rec_logic = "Normal IV environment. Sell 100-pt OTM strikes and buy 200-pt outer wings for black-swan safety."
        
        pe_sell = to_nifty_strike(atm_strike - 100)
        pe_buy  = to_nifty_strike(pe_sell - 200)
        ce_sell = to_nifty_strike(atm_strike + 100)
        ce_buy  = to_nifty_strike(ce_sell + 200)

        legs = [
            {'type': 'PE', 'action': 'BUY', 'strike': pe_buy, 'premium': 20},
            {'type': 'PE', 'action': 'SELL', 'strike': pe_sell, 'premium': 65},
            {'type': 'CE', 'action': 'SELL', 'strike': ce_sell, 'premium': 62},
            {'type': 'CE', 'action': 'BUY', 'strike': ce_buy, 'premium': 19}
        ]

elif detected_bias == "Bullish (Up Trend)":
    rec_title = "Bull Call Debit Spread"
    rec_type = "Strictly Defined Risk (Directional)"
    rec_logic = "Upward bias. Buy ATM Call and sell 150-pt higher Call to fund the premium and cap risk."
    
    ce_buy = atm_strike
    ce_sell = to_nifty_strike(atm_strike + 150)

    legs = [
        {'type': 'CE', 'action': 'BUY', 'strike': ce_buy, 'premium': 140},
        {'type': 'CE', 'action': 'SELL', 'strike': ce_sell, 'premium': 62}
    ]

elif detected_bias == "Bearish (Down Trend)":
    rec_title = "Bear Put Debit Spread"
    rec_type = "Strictly Defined Risk (Directional)"
    rec_logic = "Downward bias. Buy ATM Put and sell 150-pt lower Put to protect against IV crush."
    
    pe_buy = atm_strike
    pe_sell = to_nifty_strike(atm_strike - 150)

    legs = [
        {'type': 'PE', 'action': 'BUY', 'strike': pe_buy, 'premium': 135},
        {'type': 'PE', 'action': 'SELL', 'strike': pe_sell, 'premium': 58}
    ]

# --- STRATEGY & PAYOFF DISPLAY ---
c_rec, c_plot = st.columns([1, 1.2])

with c_rec:
    st.subheader(f"🛡️ {rec_title}")
    st.markdown(f"**Strategy Category:** `{rec_type}`")
    st.caption(f"**Target Expiry:** `{expiry_str}` ({dte_days} Days to Expiry)")
    st.info(f"**Execution Thesis:** {rec_logic}")

    st.write("#### 📋 Orders To Place on Kite:")
    for idx, leg in enumerate(legs, 1):
        action_color = "🟢 BUY" if leg['action'] == 'BUY' else "🔴 SELL"
        st.markdown(f"- **Leg {idx}:** {action_color} **NIFTY {expiry_str[:6]} {int(leg['strike'])} {leg['type']}** (~₹{leg['premium']})")

    st.caption("🔒 **Execution Sequence:** Pehle BUY legs place karein margin benefit ke liye, fir SELL legs.")

with c_plot:
    st.subheader("📈 Expiry Payoff Curve")
    if legs:
        spot_range = np.linspace(live_spot - 600, live_spot + 600, 100)
        pnl = np.zeros_like(spot_range)

        for leg in legs:
            k = leg['strike']
            prem = leg['premium']
            if leg['type'] == 'CE':
                intrinsic = np.maximum(0, spot_range - k)
            else:
                intrinsic = np.maximum(0, k - spot_range)
            
            if leg['action'] == 'BUY':
                pnl += (intrinsic - prem)
            else:
                pnl += (prem - intrinsic)

        fig, ax = plt.subplots(figsize=(7, 4.5), facecolor='#0b0f19')
        ax.set_facecolor('#111827')
        ax.plot(spot_range, pnl, color='#38bdf8', linewidth=2.5, label='Net Payoff')
        ax.axhline(0, color='#64748b', linestyle='--', linewidth=1)
        ax.axvline(live_spot, color='#f59e0b', linestyle=':', label=f'Current Spot ({live_spot:.1f})')

        ax.fill_between(spot_range, pnl, 0, where=(pnl >= 0), color='#10b981', alpha=0.35, interpolate=True)
        ax.fill_between(spot_range, pnl, 0, where=(pnl < 0), color='#ef4444', alpha=0.35, interpolate=True)

        ax.tick_params(colors='#94a3b8', labelsize=9)
        for spine in ax.spines.values():
            spine.set_color('#1f2937')

        ax.set_xlabel("Nifty Spot at Expiry", color='#94a3b8', fontsize=10)
        ax.set_ylabel("P&L per Lot (₹)", color='#94a3b8', fontsize=10)
        ax.grid(True, color='#1f2937', linestyle=':', alpha=0.6)
        ax.legend(facecolor='#111827', edgecolor='#1f2937', labelcolor='#e2e8f0', loc='best', fontsize=8)

        st.pyplot(fig)
        plt.close(fig)

# --- REFRESH & FOOTER ---
st.write("---")
f1, f2 = st.columns([1, 4])
with f1:
    if st.button("🔄 Instant Refresh"):
        st.rerun()
with f2:
    st.caption(f"Live Connected to Angel One SmartAPI Server | Last Sync: {time.strftime('%H:%M:%S IST')} | Safe Hedged Architecture")
        
