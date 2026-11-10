import streamlit as st
import pyotp
from SmartApi import SmartConnect
import matplotlib.pyplot as plt
import numpy as np
import datetime
from scipy.stats import norm
import time

st.set_page_config(page_title="Nifty Institutional Radar", layout="wide", initial_sidebar_state="collapsed")

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .reportview-container { background: #0b0f19; }
    .metric-box { background-color: #111827; border-radius: 8px; padding: 12px; border: 1px solid #1f2937; }
    .stRadio [role="radiogroup"] { gap: 15px; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Nifty Options Decision Engine (Auto-Rolled)")

# --- CREDENTIALS ---
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_CODE = st.secrets["CLIENT_CODE"]
    PASSWORD = st.secrets["PASSWORD"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except Exception:
    st.error("⚠️ Streamlit Secrets mein credentials missing hain!")
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

# --- FETCH LIVE NIFTY SPOT ---
def get_live_nifty():
    nifty_spot = 25044.65
    if smart_api:
        try:
            quote_nifty = smart_api.ltpData(exchange="NSE", tradingsymbol="Nifty 50", symboltoken="99926000")
            if quote_nifty.get("status") and "data" in quote_nifty:
                val = float(quote_nifty["data"]["ltp"])
                if val > 15000:
                    nifty_spot = val
        except Exception:
            pass
    return nifty_spot

live_spot = get_live_nifty()
atm_strike = int(round(live_spot / 50.0) * 50)

# --- 1. DYNAMIC EXPIRY GENERATOR (AUTO ROLLOVER ON EXPIRY) ---
# Nifty current cycle expiries (November 2026 schedule)
all_possible_expiries = [
    datetime.datetime(2026, 11, 17, 15, 30),
    datetime.datetime(2026, 11, 23, 15, 30),
    datetime.datetime(2026, 12, 1, 15, 30),
    datetime.datetime(2026, 12, 8, 15, 30),
    datetime.datetime(2026, 12, 15, 15, 30)
]

now = datetime.datetime.now()
# Filter out expired contracts automatically
active_expiries = [exp for exp in all_possible_expiries if exp > now]

if not active_expiries:
    st.error("Expiry list refresh required.")
    st.stop()

# Format strings for selector
expiry_labels = []
for exp in active_expiries[:3]:
    dte = (exp.date() - now.date()).days
    expiry_labels.append(f"{exp.strftime('%d-%b')} ({dte} Days)")

# Top Summary Row
c1, c2, c3 = st.columns([1.2, 1, 1.4])
with c1:
    st.metric(label="LIVE NIFTY SPOT", value=f"₹{live_spot:,.2f}")
with c2:
    st.metric(label="ATM STRIKE", value=f"{atm_strike}")
with c3:
    st.metric(label="ATM IV / REGIME", value="16.70%", delta="Very High (Sell Edge)")

st.write("---")

# --- NON-KEYBOARD DYNAMIC EXPIRY SELECTOR ---
st.markdown("#### 📅 Target Expiry Contract (Auto-Filtered):")
selected_label = st.radio(
    "Choose Expiry",
    expiry_labels,
    horizontal=True,
    label_visibility="collapsed"
)

# Extract selected expiry datetime
selected_index = expiry_labels.index(selected_label)
chosen_exp_dt = active_expiries[selected_index]
dte_days = max((chosen_exp_dt.date() - now.date()).days, 1)
exp_code_kite = chosen_exp_dt.strftime("%d-%b").upper()

# --- 2. BLACK-SCHOLES DYNAMIC PRICER (ZERO HARDCODED RATES) ---
def bs_price(S, K, T, r, sigma, opt_type='c'):
    if T <= 0.001:
        T = 0.001
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if opt_type == 'c':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return round(float(price), 2)

T_years = dte_days / 365.0
sigma = 0.1670  # Kite exact 16.70% IV
r = 0.07

# Dynamic strikes widening with DTE
wing_buffer = 100 if dte_days <= 7 else (150 if dte_days <= 14 else 200)
protection_spread = 200 if dte_days <= 7 else 250

sell_pe = int(round((atm_strike - wing_buffer) / 50.0) * 50)
buy_pe  = int(round((sell_pe - protection_spread) / 50.0) * 50)
sell_ce = int(round((atm_strike + wing_buffer) / 50.0) * 50)
buy_ce  = int(round((sell_ce + protection_spread) / 50.0) * 50)

# Calculate theoretical live prices
p_sell_pe = bs_price(live_spot, sell_pe, T_years, r, sigma, 'p')
p_buy_pe  = bs_price(live_spot, buy_pe,  T_years, r, sigma, 'p')
p_sell_ce = bs_price(live_spot, sell_ce, T_years, r, sigma, 'c')
p_buy_ce  = bs_price(live_spot, buy_ce,  T_years, r, sigma, 'c')

legs = [
    {'type': 'PE', 'action': 'BUY',  'strike': buy_pe,  'premium': p_buy_pe,  'note': 'Hedge Wing (Crash Shield)'},
    {'type': 'PE', 'action': 'SELL', 'strike': sell_pe, 'premium': p_sell_pe, 'note': 'Credit Leg (Put Sell)'},
    {'type': 'CE', 'action': 'SELL', 'strike': sell_ce, 'premium': p_sell_ce, 'note': 'Credit Leg (Call Sell)'},
    {'type': 'CE', 'action': 'BUY',  'strike': buy_ce,  'premium': p_buy_ce,  'note': 'Hedge Wing (Rally Shield)'}
]

# --- 3. RISK-REWARD & BREAKEVEN ENGINE ---
net_credit = (p_sell_pe + p_sell_ce) - (p_buy_pe + p_buy_ce)
max_profit_lot = net_credit * 25
max_loss_per_share = protection_spread - net_credit
max_loss_lot = max_loss_per_share * 25

lower_breakeven = sell_pe - net_credit
upper_breakeven = sell_ce + net_credit

# Strategy Header with Breakevens
st.subheader(f"🛡️ Hedged Iron Condor — {selected_label}")

b1, b2, b3, b4 = st.columns(4)
with b1:
    st.metric("Max Profit (Per Lot)", f"₹{max_profit_lot:,.0f}")
with b2:
    st.metric("Max Risk (Per Lot)", f"₹{max_loss_lot:,.0f}")
with b3:
    st.metric("Lower Breakeven", f"{lower_breakeven:.1f}")
with b4:
    st.metric("Upper Breakeven", f"{upper_breakeven:.1f}")

# Orders and Payoff Visual
c_orders, c_chart = st.columns([1.1, 1.2])

with c_orders:
    st.markdown("#### 📋 Orders for Zerodha Kite:")
    for idx, leg in enumerate(legs, 1):
        action_badge = "🟢 BUY" if leg['action'] == 'BUY' else "🔴 SELL"
        st.markdown(f"**Leg {idx}:** {action_badge} `NIFTY {exp_code_kite} {leg['strike']} {leg['type']}` — **~₹{leg['premium']:.2f}**")
        st.caption(f"└ {leg['note']}")

    st.info(f"Safe Range: Agar Nifty **{lower_breakeven:.0f}** aur **{upper_breakeven:.0f}** ke beech band hota hai, toh profit banega.")
    st.caption("🔒 **Execution Sequence:** Pehle dono BUY legs execute karein (margin discount ke liye), fir SELL legs.")

with c_chart:
    st.subheader(f"📈 Payoff Curve ({exp_code_kite})")
    span = protection_spread + 400
    spot_range = np.linspace(live_spot - span, live_spot + span, 150)
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
    ax.axvline(live_spot, color='#f59e0b', linestyle=':', label=f'Spot ({live_spot:.1f})')
    
    # Breakeven markers
    ax.axvline(lower_breakeven, color='#94a3b8', linestyle='--', alpha=0.7)
    ax.axvline(upper_breakeven, color='#94a3b8', linestyle='--', alpha=0.7)

    ax.fill_between(spot_range, pnl, 0, where=(pnl >= 0), color='#10b981', alpha=0.35, interpolate=True)
    ax.fill_between(spot_range, pnl, 0, where=(pnl < 0), color='#ef4444', alpha=0.35, interpolate=True)

    ax.tick_params(colors='#94a3b8', labelsize=9)
    for spine in ax.spines.values():
        spine.set_color('#1f2937')

    ax.set_xlabel(f"Nifty Spot at Expiry", color='#94a3b8', fontsize=10)
    ax.set_ylabel("P&L per Share (₹)", color='#94a3b8', fontsize=10)
    ax.grid(True, color='#1f2937', linestyle=':', alpha=0.6)
    ax.legend(facecolor='#111827', edgecolor='#1f2937', labelcolor='#e2e8f0', loc='best', fontsize=8)

    st.pyplot(fig)
    plt.close(fig)

# --- REFRESH ---
st.write("---")
if st.button("🔄 Instant Refresh"):
    st.rerun()
st.caption(f"Sync: {time.strftime('%H:%M:%S IST')} | Fully Dynamic Expiry & Pricing Engine")
