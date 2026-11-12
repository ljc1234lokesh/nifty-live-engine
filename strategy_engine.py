import json
import os
import datetime
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm

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

def get_ist_clock_status():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
    ist_time_str = ist_now.strftime("%H:%M:%S IST")
    mins_now = ist_now.hour * 60 + ist_now.minute
    weekday = ist_now.weekday()

    if weekday >= 5 or mins_now < (9 * 60 + 15) or mins_now > (15 * 60 + 30):
        return ist_now, ist_time_str, "⚪ MARKET CLOSED", "Best Entry: 09:45 AM – 11:30 AM IST", "#94a3b8"
    elif mins_now < (9 * 60 + 45):
        return ist_now, ist_time_str, "🔴 WAIT (OPENING NOISE)", "09:15–09:45 AM Volatility! Wait till 09:45", "#ef4444"
    elif mins_now <= (11 * 60 + 30):
        return ist_now, ist_time_str, "🟢 PRIME ENTRY WINDOW", "09:45–11:30 AM Institutional Settlement Time", "#10b981"
    elif mins_now <= (13 * 60 + 30):
        return ist_now, ist_time_str, "🟡 SAFE THETA ZONE", "11:30–01:30 PM Sideways Decay Window", "#eab308"
    elif mins_now <= (14 * 60 + 45):
        return ist_now, ist_time_str, "🟢 2ND PRIME WINDOW", "01:30–02:45 PM Afternoon Trend Window", "#10b981"
    else:
        return ist_now, ist_time_str, "🟠 AVOID FRESH ENTRY", "Closing Gamma Move! Avoid New Positions", "#f97316"

def get_kite_symbol(exp_date, strike, opt_type, all_exp_dates):
    yy = exp_date.strftime("%y")
    same_month_exps = [d for d in all_exp_dates if d.year == exp_date.year and d.month == exp_date.month]
    if exp_date == max(same_month_exps):
        return f"NIFTY{yy}{exp_date.strftime('%b').upper()}{strike}{opt_type}"
    month_codes = {1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'O', 11: 'N', 12: 'D'}
    return f"NIFTY{yy}{month_codes.get(exp_date.month, 'N')}{exp_date.strftime('%d')}{strike}{opt_type}"

def build_strategy_specs(strat_mode_choice, live_spot, atm_strike, live_vix, oi_data):
    live_pcr = oi_data["pcr"]
    live_max_pain = oi_data["max_pain"]
    call_wall = oi_data["call_wall"]
    put_wall = oi_data["put_wall"]

    if "AI Auto-Select" in strat_mode_choice:
        if live_spot >= call_wall - 35 or live_pcr <= 0.72:
            active_key = "BEAR_CALL"
        elif live_spot <= put_wall + 35 or live_pcr >= 1.25:
            active_key = "BULL_PUT"
        elif live_vix >= 15.5 and abs(live_spot - live_max_pain) <= 50:
            active_key = "IRON_FLY"
        else:
            active_key = "IRON_CONDOR"
    elif "Iron Condor" in strat_mode_choice:
        active_key = "IRON_CONDOR"
    elif "Iron Butterfly" in strat_mode_choice:
        active_key = "IRON_FLY"
    elif "Bear Call" in strat_mode_choice:
        active_key = "BEAR_CALL"
    else:
        active_key = "BULL_PUT"

    if active_key == "BEAR_CALL":
        return "Bear Call Credit Spread", f"Live Call OI Wall at {call_wall} (PCR: {live_pcr:.2f}). Defending upside resistance.", [
            {"type": "CE", "action": "SELL", "strike": call_wall,       "note": f"Live Call Wall ({call_wall} OI)"},
            {"type": "CE", "action": "BUY",  "strike": call_wall + 200, "note": "Upside Protection Wing"}
        ]
    elif active_key == "BULL_PUT":
        return "Bull Put Credit Spread", f"Live Put OI Wall at {put_wall} (PCR: {live_pcr:.2f}). Defending downside support.", [
            {"type": "PE", "action": "SELL", "strike": put_wall,       "note": f"Live Put Wall ({put_wall} OI)"},
            {"type": "PE", "action": "BUY",  "strike": put_wall - 200, "note": "Downside Protection Wing"}
        ]
    elif active_key == "IRON_FLY":
        return "Short Iron Butterfly (ATM Pinning)", f"High VIX ({live_vix:.2f}) & Max Pain at {live_max_pain}. Capturing ATM theta decay.", [
            {"type": "PE", "action": "BUY",  "strike": atm_strike - 200, "note": "Downside Hedge Wing"},
            {"type": "PE", "action": "SELL", "strike": atm_strike,       "note": f"ATM Put Sell ({atm_strike} Pin)"},
            {"type": "CE", "action": "SELL", "strike": atm_strike,       "note": f"ATM Call Sell ({atm_strike} Pin)"},
            {"type": "CE", "action": "BUY",  "strike": atm_strike + 200, "note": "Upside Hedge Wing"}
        ]
    else:
        safe_put = min(put_wall, atm_strike - 100)
        safe_call = max(call_wall, atm_strike + 100)
        return "Short Iron Condor (Live OI-Synced)", f"Max Pain at {live_max_pain} & PCR {live_pcr:.2f}. Inside {safe_put} - {safe_call} OI walls.", [
            {"type": "PE", "action": "BUY",  "strike": safe_put - 200,  "note": "Put Wall Protection Wing"},
            {"type": "PE", "action": "SELL", "strike": safe_put,        "note": f"Put Credit ({safe_put} OI Support)"},
            {"type": "CE", "action": "SELL", "strike": safe_call,       "note": f"Call Credit ({safe_call} OI Resistance)"},
            {"type": "CE", "action": "BUY",  "strike": safe_call + 200, "note": "Call Wall Protection Wing"}
        ]

def compute_payoff_and_chart(display_legs, live_spot, live_vix, dte_days, lot_size, display_exp):
    spot_range = np.linspace(live_spot - 800, live_spot + 800, 300)
    pnl = np.zeros_like(spot_range)
    net_credit = 0.0

    for leg in display_legs:
        k, prem = leg["strike"], leg["premium"]
        net_credit += prem if leg["action"] == "SELL" else -prem
        intrinsic = np.maximum(0, spot_range - k) if leg["type"] == "CE" else np.maximum(0, k - spot_range)
        pnl += (intrinsic - prem) if leg["action"] == "BUY" else (prem - intrinsic)

    max_profit_lot = np.max(pnl) * lot_size
    max_loss_lot = abs(np.min(pnl)) * lot_size

    profitable_spots = spot_range[pnl >= 0]
    lower_be = profitable_spots[0] if len(profitable_spots) > 0 else live_spot - 250
    upper_be = profitable_spots[-1] if len(profitable_spots) > 0 else live_spot + 250

    T_years = dte_days / 365.0
    sigma = max(live_vix / 100.0, 0.10)
    stdev = live_spot * sigma * np.sqrt(T_years)
    pop_percent = (norm.cdf((upper_be - live_spot) / stdev) - norm.cdf((lower_be - live_spot) / stdev)) * 100
    rr_ratio = max_loss_lot / max(max_profit_lot, 1)

    fig, ax = plt.subplots(figsize=(6.8, 3.65), facecolor="#0b0f19")
    ax.set_facecolor("#111827")
    ax.plot(spot_range, pnl * lot_size, color="#38bdf8", linewidth=2.2, label="Total P&L (₹)")
    ax.axhline(0, color="#64748b", linestyle="--", linewidth=0.9)
    ax.axvline(live_spot, color="#f59e0b", linestyle=":", label=f"Spot ({live_spot:.0f})")
    ax.axvline(lower_be, color="#94a3b8", linestyle="--", alpha=0.7)
    ax.axvline(upper_be, color="#94a3b8", linestyle="--", alpha=0.7)

    ax.fill_between(spot_range, pnl * lot_size, 0, where=(pnl >= 0), color="#10b981", alpha=0.35, interpolate=True)
    ax.fill_between(spot_range, pnl * lot_size, 0, where=(pnl < 0), color="#ef4444", alpha=0.35, interpolate=True)

    ax.tick_params(colors="#94a3b8", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#1f2937")

    ax.set_title(f"Payoff Curve ({display_exp}) | BE: {lower_be:.0f} — {upper_be:.0f}", color="#e2e8f0", fontsize=9.5, pad=8)
    ax.set_ylabel(f"P&L (₹ / {lot_size} Qty)", color="#94a3b8", fontsize=8.5)
    ax.grid(True, color="#1f2937", linestyle=":", alpha=0.6)
    ax.legend(facecolor="#111827", edgecolor="#1f2937", labelcolor="#e2e8f0", loc="upper right", fontsize=8)
    plt.tight_layout(pad=0.6)

    return {
        "net_credit": net_credit,
        "max_profit": max_profit_lot,
        "max_loss": max_loss_lot,
        "pop": pop_percent,
        "rr": rr_ratio,
        "fig": fig
    }
