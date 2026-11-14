import streamlit as st
from streamlit_autorefresh import st_autorefresh
import datetime
import os

from api_service import (
    send_telegram_alert,
    get_angel_session,
    load_angel_master_data,
    get_comprehensive_indices,
    get_live_option_chain_oi,
    fetch_batch_ltps
)
from strategy_engine import (
    load_saved_strategies,
    save_strategies_to_disk,
    get_ist_clock_status,
    get_kite_symbol,
    build_strategy_specs,
    compute_payoff_and_chart
)

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="NIFTY Institutional Quant Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- LOAD EXTERNAL BASE CSS ---
if os.path.exists("style.css"):
    with open("style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "saved_strategies" not in st.session_state:
    st.session_state.saved_strategies = load_saved_strategies()
if "alerted_ids" not in st.session_state:
    st.session_state.alerted_ids = set()

# --- API AUTHENTICATION & MASTER DATA ---
API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_CODE = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

smart_api = get_angel_session(API_KEY, CLIENT_CODE, PASSWORD, TOTP_SECRET)
nfo_df, idx_tokens = load_angel_master_data()
market_data = get_comprehensive_indices(smart_api, idx_tokens)

live_spot = market_data["nifty"]["ltp"]
live_vix = market_data["vix"]
atm_strike = int(round(live_spot / 50.0) * 50)

ist_now, ist_time_str, market_badge, timing_advice, badge_color = get_ist_clock_status()
active_count = len(st.session_state.saved_strategies)
api_badge_cls = "col-green" if smart_api else "col-amber"
api_status_badge = "🟢 LIVE NFO API" if smart_api else "🟡 SIMULATED MODE"

# ==============================================================================
# FROZEN TOP COMMAND HEADER (DOES NOT SCROLL)
# ==============================================================================
with st.container():
    st.markdown('<div class="sticky-marker" style="display:none;"></div>', unsafe_allow_html=True)

    # 1. Main Title Header
    st.markdown(
        f'<div class="top-bar" style="border:1px solid; border-radius:8px; padding:10px 14px; margin-bottom:6px;">'
        f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">'
        f'<div>'
        f'<div class="txt-main" style="font-size:1.05rem; font-weight:800; letter-spacing:0.4px;">📊 NIFTY INSTITUTIONAL QUANT TERMINAL</div>'
        f'<div class="col-blue" style="font-size:0.72rem; font-weight:600;">Advanced Delta & OI-Synced Options Analytics & Live Tracker</div>'
        f'</div>'
        f'<div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">'
        f'<span class="txt-main" style="background:rgba(100,116,139,0.18); padding:3px 8px; border-radius:5px; font-size:0.72rem; font-weight:600;">🕒 {ist_time_str} | Active: {active_count}</span>'
        f'<span class="{api_badge_cls}" style="background:rgba(100,116,139,0.18); padding:3px 8px; border-radius:5px; font-size:0.72rem;">{api_status_badge}</span>'
        f'</div></div></div>',
        unsafe_allow_html=True
    )

    # 2. Index Ticker Bar (NIFTY 50, BANKNIFTY, SENSEX)
    t1, t2, t3 = st.columns(3)
    for col, name, key in [(t1, "NIFTY 50", "nifty"), (t2, "BANKNIFTY", "banknifty"), (t3, "SENSEX", "sensex")]:
        with col:
            d = market_data[key]
            ltp = d["ltp"]
            close = d["close"] if d["close"] > 0 else ltp
            diff = ltp - close
            pct = (diff / close) * 100 if close > 0 else 0.0
            css_class = "ticker-ltp-green" if diff >= 0 else "ticker-ltp-red"
            sign_str = "+" if diff >= 0 else ""

            st.markdown(
                f'<div class="index-ticker" style="border:1px solid; border-radius:6px; padding:6px 8px; text-align:center; margin-bottom:4px;">'
                f'<div class="txt-main" style="font-weight:700; font-size:0.85rem;">'
                f'{name}: <span class="{css_class}">₹{ltp:,.2f}</span> '
                f'<span class="ticker-change">{sign_str}{diff:,.2f} ({sign_str}{pct:.2f}%)</span>'
                f'</div>'
                f'<div class="txt-muted" style="font-size:0.65rem; margin-top:2px;">O: {d["open"]:,.1f} | H: {d["high"]:,.1f} | L: {d["low"]:,.1f} | C: {close:,.1f}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    # 3. Navigation, Light Mode & 7s Sync Toggles
    nav_col1, nav_col2, nav_col3 = st.columns([2.4, 0.8, 0.8])
    with nav_col1:
        nav_mode = st.radio(
            "Workspace",
            ["⚡ Quant Terminal", "🛡️ Saved Live Tracker"],
            horizontal=True,
            label_visibility="collapsed",
            key="main_nav_mode"
        )
    with nav_col2:
        light_mode = st.toggle("☀️ Light", value=False, key="top_theme_toggle")
    with nav_col3:
        auto_refresh_on = st.toggle("Sync (7s)", value=True, key="top_sync_toggle")

# --- LIGHT MODE VARIABLE OVERRIDE (PRESERVES ALL SEMANTIC COLORS) ---
if light_mode:
    st.markdown("""
    <style>
        :root {
            --bg-app: #f1f5f9;
            --bg-card: #ffffff;
            --border-card: #cbd5e1;
            --text-primary: #0f172a;
            --text-muted: #475569;
        }
        .metric-card, .index-ticker, .top-bar, .leg-card, .tracker-card, .timing-banner {
            box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
        }
        .col-green, .ticker-ltp-green { color: #059669 !important; }
        .col-red, .ticker-ltp-red { color: #dc2626 !important; }
        .col-blue { color: #0284c7 !important; }
        .col-purple { color: #7e22ce !important; }
        .col-amber { color: #d97706 !important; }
    </style>
    """, unsafe_allow_html=True)

if auto_refresh_on:
    st_autorefresh(interval=7 * 1000, key="terminal_fixed_sync_v13")

# ==============================================================================
# WORKSPACE 1: QUANT TERMINAL (STRATEGY BUILDER & ANALYTICS)
# ==============================================================================
if "Quant Terminal" in nav_mode:
    today_dt = ist_now.date()
    valid_exps = sorted([d for d in nfo_df["expiry_dt"].dropna().unique() if d >= today_dt])[:4]
    if not valid_exps:
        valid_exps = [today_dt + datetime.timedelta(days=7)]

    exp_labels = {d: f"{d.strftime('%d-%b')} ({(d - today_dt).days}d)" for d in valid_exps}
    sel_exp_label = st.radio(
        "Expiry Selection",
        list(exp_labels.values()),
        horizontal=True,
        label_visibility="collapsed",
        key="exp_selector"
    )
    selected_exp_dt = [d for d, lbl in exp_labels.items() if lbl == sel_exp_label][0]
    dte_days = max((selected_exp_dt - today_dt).days, 1)
    display_exp = selected_exp_dt.strftime("%d-%b")

    strat_mode_choice = st.selectbox(
        "Strategy Engine",
        [
            "🤖 AI Auto-Select (OI-Synced)",
            "🦅 Short Iron Condor (Range Bound)",
            "🦋 Short Iron Butterfly (ATM Pinning)",
            "🐻 Bear Call Credit Spread (Resistance)",
            "🐂 Bull Put Credit Spread (Support)"
        ],
        label_visibility="collapsed",
        key="strat_mode_select"
    )

    oi_data = get_live_option_chain_oi(smart_api, nfo_df, selected_exp_dt.isoformat(), atm_strike)
    live_pcr = oi_data["pcr"]
    live_max_pain = oi_data["max_pain"]
    call_wall = oi_data["call_wall"]
    put_wall = oi_data["put_wall"]

    pcr_sentiment = "Bullish Support" if live_pcr >= 1.15 else ("Bearish Pressure" if live_pcr <= 0.78 else "Neutral / Range")
    pcr_cls = "col-green" if live_pcr >= 1.0 else "col-amber"

    # --- 5 INSTITUTIONAL METRIC CARDS ---
    m1, m2, m3, m4, m5 = st.columns(5)
    metrics_info = [
        (m1, "INDIA VIX", f"{live_vix:.2f}", "Volatility", "col-blue"),
        (m2, "LIVE PCR (🟢)", f"{live_pcr:.2f}", pcr_sentiment, pcr_cls),
        (m3, "MAX PAIN", f"₹{live_max_pain}", "Expiry Magnet", "col-purple"),
        (m4, "PUT SUPPORT", f"₹{put_wall}", f"OI: {oi_data['put_wall_oi']:,}", "col-green"),
        (m5, "CALL RESISTANCE", f"₹{call_wall}", f"OI: {oi_data['call_wall_oi']:,}", "col-red"),
    ]
    for col, title, val, sub, cls_name in metrics_info:
        with col:
            st.markdown(
                f'<div class="metric-card" style="border:1px solid; border-radius:8px; padding:10px 12px; margin-bottom:6px;">'
                f'<div class="txt-muted" style="font-size:0.68rem; font-weight:700; letter-spacing:0.5px;">{title}</div>'
                f'<div class="txt-main" style="font-size:1.3rem; font-weight:800; margin:2px 0;">{val}</div>'
                f'<div class="{cls_name}" style="font-size:0.72rem;">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    # --- MARKET TIMING BANNER ---
    st.markdown(
        f'<div class="timing-banner" style="border-left:4px solid {badge_color}; border-top:1px solid; border-right:1px solid; border-bottom:1px solid; border-radius:6px; padding:8px 12px; margin:6px 0 10px 0;">'
        f'<span style="font-weight:800; font-size:0.82rem; color:{badge_color} !important;">{market_badge}</span>'
        f'<span class="txt-muted" style="font-size:0.78rem; margin-left:8px;">— {timing_advice}</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    # --- STRATEGY GENERATION & LIVE LEG PREMIUMS ---
    strat_title, strat_desc, raw_legs = build_strategy_specs(strat_mode_choice, live_spot, atm_strike, live_vix, oi_data)

    exp_nfo = nfo_df[nfo_df["expiry_dt"] == selected_exp_dt]
    lot_size = int(exp_nfo["lotsize_int"].iloc[0]) if not exp_nfo.empty else 65

    leg_tokens = []
    leg_token_map = {}
    for idx, lg in enumerate(raw_legs):
        match_row = exp_nfo[(exp_nfo["strike_int"] == lg["strike"]) & (exp_nfo["opt_type"] == lg["type"])]
        if not match_row.empty:
            tok = str(match_row["token"].iloc[0])
            leg_tokens.append(tok)
            leg_token_map[idx] = tok

    live_ltps = fetch_batch_ltps(smart_api, leg_tokens)

    display_legs = []
    for idx, lg in enumerate(raw_legs):
        tok = leg_token_map.get(idx, "")
        prem = live_ltps.get(tok, 0.0)
        if prem <= 0:
            dist = abs(live_spot - lg["strike"])
            prem = round(max(12.0, 165.0 * (0.994 ** dist)), 2)
        kite_sym = get_kite_symbol(selected_exp_dt, lg["strike"], lg["type"], valid_exps)
        display_legs.append({
            "type": lg["type"],
            "action": lg["action"],
            "strike": lg["strike"],
            "premium": prem,
            "note": lg["note"],
            "token": tok,
            "symbol": kite_sym
        })

    # --- COMPUTE PAYOFF & INTERACTIVE PLOTLY GRAPH ---
    payoff_res = compute_payoff_and_chart(
        display_legs, live_spot, live_vix, dte_days, lot_size, display_exp, light_mode=light_mode
    )

    st.markdown(
        f'<div class="metric-card" style="border:1px solid; border-radius:8px; padding:12px; margin-bottom:8px;">'
        f'<div class="col-blue" style="font-size:1.05rem; font-weight:800;">🎯 {strat_title}</div>'
        f'<div class="txt-muted" style="font-size:0.78rem; margin-top:2px;">{strat_desc}</div>'
        f'<div style="display:flex; gap:16px; flex-wrap:wrap; margin-top:10px; font-size:0.82rem;">'
        f'<span class="col-green">Max Profit: ₹{payoff_res["max_profit"]:,.0f}</span>'
        f'<span class="col-red">Max Risk: ₹{payoff_res["max_loss"]:,.0f}</span>'
        f'<span class="col-purple">Win Prob (POP): {payoff_res["pop"]:.1f}%</span>'
        f'<span class="col-amber">Lot Size: {lot_size}</span>'
        f'</div></div>',
        unsafe_allow_html=True
    )

    # --- RENDER INTERACTIVE TOUCH/HOVER PLOTLY CHART ---
    st.plotly_chart(
        payoff_res["fig"],
        use_container_width=True,
        config={"displayModeBar": False, "scrollZoom": True}
    )

    # --- EXECUTION LEGS TABLE ---
    st.markdown("#### 📋 Strategy Execution Legs")
    for i, lg in enumerate(display_legs, 1):
        act_cls = "col-green" if lg["action"] == "BUY" else "col-red"
        border_col = "#10b981" if lg["action"] == "BUY" else "#ef4444"
        st.markdown(
            f'<div class="leg-card" style="border-left:4px solid {border_col}; border-top:1px solid; border-right:1px solid; border-bottom:1px solid; border-radius:6px; padding:8px 12px; margin-bottom:6px;">'
            f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">'
            f'<div>'
            f'<span class="{act_cls}" style="font-weight:800;">Leg {i}: {lg["action"]}</span> '
            f'<span class="txt-main" style="font-weight:700;">NIFTY {display_exp} {lg["strike"]} {lg["type"]}</span> '
            f'<span class="txt-muted" style="font-size:0.72rem; margin-left:6px;">({lg["note"]})</span>'
            f'</div>'
            f'<div class="txt-main" style="font-weight:800; font-size:0.9rem;">LTP: ₹{lg["premium"]:.2f}</div>'
            f'</div></div>',
            unsafe_allow_html=True
        )

    # --- SAVE TO LIVE TRACKER BUTTON ---
    if st.button("🚀 Deploy & Save to Live P&L Tracker", use_container_width=True, type="primary"):
        new_entry = {
            "id": int(datetime.datetime.now().timestamp()),
            "name": strat_title,
            "expiry": display_exp,
            "saved_time": ist_time_str,
            "entry_spot": live_spot,
            "lot_size": lot_size,
            "max_profit": round(payoff_res["max_profit"]),
            "max_loss": round(payoff_res["max_loss"]),
            "legs": [
                {
                    "action": l["action"],
                    "type": l["type"],
                    "strike": l["strike"],
                    "entry_price": l["premium"],
                    "token": l["token"],
                    "symbol": l["symbol"]
                }
                for l in display_legs
            ]
        }
        st.session_state.saved_strategies.append(new_entry)
        save_strategies_to_disk(st.session_state.saved_strategies)
        send_telegram_alert(f"🚀 <b>NEW STRATEGY DEPLOYED</b>\n<b>{strat_title}</b> ({display_exp})\nSpot: ₹{live_spot:,.2f} | Max Profit: ₹{payoff_res['max_profit']:,.0f}")
        st.success("✅ Strategy saved to GitHub & Live Tracker!")
        st.rerun()

# ==============================================================================
# WORKSPACE 2: SAVED LIVE TRACKER & P&L DESK
# ==============================================================================
else:
    st.markdown(f"### 🛡️ Live Trade Tracker & P&L Desk ({len(st.session_state.saved_strategies)} Active)")

    if st.button("🔔 Send Test Alert", use_container_width=True):
        ok = send_telegram_alert(f"🔔 <b>Quant Terminal Test Alert</b>\nNifty Spot: ₹{live_spot:,.2f}\nTime: {ist_time_str}")
        if ok:
            st.success("✅ Telegram Alert Sent!")
        else:
            st.warning("⚠️ Check TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID in Secrets.")

    if not st.session_state.saved_strategies:
        st.info("Abhi koi active strategy nahi hai. '⚡ Quant Terminal' tab se koi strategy deploy karein.")
    else:
        all_tokens = [lg.get("token", "") for s in st.session_state.saved_strategies for lg in s.get("legs", []) if lg.get("token")]
        tracker_ltps = fetch_batch_ltps(smart_api, all_tokens)

        for idx, strat in enumerate(st.session_state.saved_strategies):
            lot_q = strat.get("lot_size", strat.get("lot", 65))
            ent_spot = strat.get("entry_spot", live_spot)
            spot_drift = live_spot - ent_spot
            total_pnl_pts = 0.0

            legs_html = ""
            for l_i, lg in enumerate(strat.get("legs", []), 1):
                tok = lg.get("token", "")
                ent_price = float(lg.get("entry_price", lg.get("entry", lg.get("premium", 0.0))))
                
                cur_p = tracker_ltps.get(tok, ent_price)
                if cur_p <= 0:
                    cur_p = ent_price

                diff_p = (cur_p - ent_price) if lg["action"] == "BUY" else (ent_price - cur_p)
                total_pnl_pts += diff_p
                leg_pnl_rs = diff_p * lot_q
                pnl_cls = "col-green" if leg_pnl_rs >= 0 else "col-red"
                act_cls = "col-green" if lg["action"] == "BUY" else "col-red"
                border_c = "#10b981" if lg["action"] == "BUY" else "#ef4444"
                sign_p = "+" if leg_pnl_rs >= 0 else ""

                legs_html += (
                    f'<div class="leg-card" style="border-left:4px solid {border_c}; border-top:1px solid; border-right:1px solid; border-bottom:1px solid; border-radius:6px; padding:8px 10px; margin-bottom:6px;">'
                    f'<div class="txt-main" style="font-size:0.8rem; font-weight:700;">Leg {l_i}: <span class="{act_cls}">{lg["action"]}</span> NIFTY {strat.get("expiry", "")} {lg["strike"]} {lg["type"]}</div>'
                    f'<div class="txt-muted" style="font-size:0.78rem; margin-top:2px;">Entry: ₹{ent_price:.2f} → Live: <b class="txt-main">₹{cur_p:.2f}</b> | <span class="{pnl_cls}" style="font-weight:800;">{sign_p}₹{leg_pnl_rs:,.0f}</span></div>'
                    f'</div>'
                )

            net_pnl_rs = total_pnl_pts * lot_q
            net_cls = "col-green" if net_pnl_rs >= 0 else "col-red"
            net_sign = "+" if net_pnl_rs >= 0 else ""

            if abs(spot_drift) >= 100:
                status_txt = f"🟡 STATUS: MONITOR CLOSELY — Spot Drift: {spot_drift:+.1f} pts."
                status_bg = "rgba(234, 179, 8, 0.16)"
                status_cls = "col-amber"
            else:
                status_txt = f"🟢 STATUS: SAFE ZONE — Spot Drift: {spot_drift:+.1f} pts."
                status_bg = "rgba(16, 185, 129, 0.16)"
                status_cls = "col-green"

            max_p_clean = round(float(strat.get("max_profit", 0)))
            max_l_clean = round(float(strat.get("max_loss", 0)))

            card_html = (
                f'<div class="tracker-card" style="border:1px solid; border-radius:10px; padding:12px; margin-top:10px;">'
                f'<div class="txt-main" style="font-size:0.95rem; font-weight:800;">#{idx+1} • {strat.get("name", "Strategy")} <span class="col-blue">({strat.get("expiry", "")})</span></div>'
                f'<div class="txt-muted" style="font-size:0.72rem; margin-bottom:6px;">Saved: {strat.get("saved_time", "")} | Entry Spot: ₹{ent_spot:,.2f} | Live Spot: ₹{live_spot:,.2f} ({spot_drift:+.1f})</div>'
                f'<div style="display:flex; gap:14px; flex-wrap:wrap; font-size:0.78rem; margin-bottom:6px;">'
                f'<span class="col-green">Max Profit: ₹{max_p_clean:,}</span>'
                f'<span class="col-red">Max Risk: ₹{max_l_clean:,}</span>'
                f'<span class="txt-main" style="font-weight:700;">Lot Qty: {lot_q}</span>'
                f'</div>'
                f'<div class="txt-main" style="font-size:1.05rem; font-weight:800; margin-bottom:10px;">Running P&L: <span class="{net_cls}">{net_sign}₹{net_pnl_rs:,.0f} ({total_pnl_pts:+.2f} pts)</span></div>'
                f'{legs_html}'
                f'<div class="{status_cls}" style="background:{status_bg}; padding:8px 10px; border-radius:6px; font-size:0.78rem; margin-top:8px;">{status_txt}</div>'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

            with st.expander(f"✏️ Edit Strikes & Entry Prices (#{idx+1})"):
                updated = False
                for l_i, lg in enumerate(strat.get("legs", [])):
                    cur_ent_val = float(lg.get("entry_price", lg.get("entry", lg.get("premium", 0.0))))
                    c1, c2 = st.columns(2)
                    with c1:
                        new_st = st.number_input(f"Leg {l_i+1} Strike", value=int(lg["strike"]), step=50, key=f"st_{strat.get('id', idx)}_{l_i}")
                    with c2:
                        new_pr = st.number_input(f"Leg {l_i+1} Entry ₹", value=cur_ent_val, step=0.5, key=f"pr_{strat.get('id', idx)}_{l_i}")
                    if new_st != lg["strike"] or new_pr != cur_ent_val:
                        lg["strike"] = new_st
                        lg["entry_price"] = new_pr
                        updated = True
                if updated:
                    save_strategies_to_disk(st.session_state.saved_strategies)
                    st.rerun()

            if st.button(f"🚪 Exit Trade (#{idx+1})", key=f"exit_{strat.get('id', idx)}", use_container_width=True):
                st.session_state.saved_strategies.pop(idx)
                save_strategies_to_disk(st.session_state.saved_strategies)
                st.rerun()
