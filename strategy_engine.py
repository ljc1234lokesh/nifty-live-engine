import json
import os
import datetime
import base64
import requests
import numpy as np
from scipy.stats import norm
import matplotlib.pyplot as plt
import streamlit as st

STORAGE_FILE = "saved_strategies.json"

def get_github_repo_credentials():
    try:
        token = st.secrets.get("GITHUB_TOKEN", "")
        repo = st.secrets.get("GITHUB_REPO", "")
        user = st.secrets.get("GITHUB_USER", "")
        if token and repo and user:
            return token, repo, user
    except Exception:
        pass
    return None, None, None

def load_saved_strategies():
    token, repo, user = get_github_repo_credentials()
    if token and repo and user:
        try:
            url = f"https://api.github.com/repos/{user}/{repo}/contents/{STORAGE_FILE}"
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                file_data = r.json()
                decoded_content = base64.b64decode(file_data["content"]).decode("utf-8")
                strat_list = json.loads(decoded_content)
                with open(STORAGE_FILE, "w") as f:
                    json.dump(strat_list, f, indent=2)
                return strat_list
        except Exception:
            pass

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

    token, repo, user = get_github_repo_credentials()
    if token and repo and user:
        try:
            url = f"https://api.github.com/repos/{user}/{repo}/contents/{STORAGE_FILE}"
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
            
            sha = None
            r_get = requests.get(url, headers=headers, timeout=5)
            if r_get.status_code == 200:
                sha = r_get.json().get("sha")

            json_str = json.dumps(strat_list, indent=2)
            content_encoded = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

            payload = {
                "message": "Auto-sync saved strategies via Quant Terminal",
                "content": content_encoded,
                "branch": "main"
            }
            if sha:
                payload["sha"] = sha

            result = requests.put(url, headers=headers, json=payload, timeout=8)
            if not result.ok:
                st.warning(f"GitHub backup failed (HTTP {result.status_code}). Check repo permissions and branch.")
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

def compute_strategy_greeks(display_legs, live_spot, live_vix, dte_days, lot_size):
    T = max(dte_days, 0.5) / 365.0
    sigma = max(live_vix / 100.0, 0.10)
    r = 0.065
    
    net_delta = 0.0
    net_theta_daily = 0.0
    
    for leg in display_legs:
        K = leg["strike"]
        opt_type = leg["type"]
        action = leg["action"]
        mult = 1.0 if action == "BUY" else -1.0
        
        if T <= 0:
            continue
            
        d1 = (np.log(live_spot / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        if opt_type == "CE":
            delta = norm.cdf(d1)
            theta_annual = - (live_spot * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)
        else:
            delta = norm.cdf(d1) - 1.0
            theta_annual = - (live_spot * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)
            
        theta_daily = theta_annual / 365.0
        net_delta += delta * mult * lot_size
        net_theta_daily += theta_daily * mult * lot_size
        
    return round(net_delta, 1), round(net_theta_daily, 0)

def estimate_margin_requirement(display_legs, lot_size, live_spot):
    short_legs = [l for l in display_legs if l["action"] == "SELL"]
    long_legs = [l for l in display_legs if l["action"] == "BUY"]
    
    if len(short_legs) == 0:
        total_debit = sum(l["premium"] for l in long_legs) * lot_size
        return {
            "span_margin": 0.0,
            "exposure_margin": 0.0,
            "total_margin": total_debit,
            "margin_type": "Buy-Only (Debit)"
        }
    
    if len(short_legs) == 2 and len(long_legs) == 2:
        ce_shorts = sorted([l["strike"] for l in short_legs if l["type"] == "CE"])
        pe_shorts = sorted([l["strike"] for l in short_legs if l["type"] == "PE"])
        ce_longs = sorted([l["strike"] for l in long_legs if l["type"] == "CE"])
        pe_longs = sorted([l["strike"] for l in long_legs if l["type"] == "PE"])
        
        spread_width = 200
        if ce_shorts and ce_longs:
            spread_width = max(spread_width, abs(ce_longs[-1] - ce_shorts[0]))
        if pe_shorts and pe_longs:
            spread_width = max(spread_width, abs(pe_shorts[0] - pe_longs[0]))
            
        est_margin = (spread_width * lot_size) + 15000
        return {
            "span_margin": round(est_margin * 0.75),
            "exposure_margin": round(est_margin * 0.25),
            "total_margin": round(est_margin),
            "margin_type": "Hedged Spread / Condor (Low Risk)"
        }
    elif len(short_legs) == 1 and len(long_legs) == 1:
        spread_width = 200
        est_margin = (spread_width * lot_size) + 10000
        return {
            "span_margin": round(est_margin * 0.70),
            "exposure_margin": round(est_margin * 0.30),
            "total_margin": round(est_margin),
            "margin_type": "Single Credit Spread (Hedged)"
        }
    else:
        est_margin = len(short_legs) * 115000.0
        return {
            "span_margin": round(est_margin * 0.75),
            "exposure_margin": round(est_margin * 0.25),
            "total_margin": round(est_margin),
            "margin_type": "Naked / Unhedged (High Margin)"
        }

def _bs_option_price(S, K, T, r, sigma, opt_type):
    if T <= 0:
        return np.maximum(0.0, S - K) if opt_type == "CE" else np.maximum(0.0, K - S)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if opt_type == "CE":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def compute_payoff_and_chart(display_legs, live_spot, live_vix, dte_days, lot_size, display_exp, sim_vix_shift=0.0, sim_dte_override=None):
    if not display_legs or lot_size <= 0:
        raise ValueError("Valid legs and lot size are required")
    strikes = sorted(set(float(lg["strike"]) for lg in display_legs))
    # Exact expiration payoff for same-expiry vanilla European index options:
    # piecewise linear, extrema occur at strikes or either boundary.
    spot_range = np.unique(np.concatenate((
        np.linspace(max(0.0, min([live_spot] + strikes) - 800),
                    max([live_spot] + strikes) + 800, 400), strikes, [0.0]
    )))
    net_credit = 0.0
    for leg in display_legs:
        net_credit += float(leg["premium"]) * (1 if leg["action"] == "SELL" else -1)

    def payoff_at(prices):
        prices = np.asarray(prices, dtype=float)
        result = np.zeros_like(prices)
        for leg in display_legs:
            intrinsic = (np.maximum(0, prices - float(leg["strike"]))
                         if leg["type"] == "CE" else
                         np.maximum(0, float(leg["strike"]) - prices))
            result += (intrinsic - float(leg["premium"])) * (1 if leg["action"] == "BUY" else -1)
        return result

    expiry_check = payoff_at([0.0] + strikes + [max(strikes) + 1.0]) * lot_size
    # For S beyond the largest strike, the payoff slope is the net call exposure.
    call_slope = sum((1 if leg["action"] == "BUY" else -1)
                     for leg in display_legs if leg["type"] == "CE")
    max_profit_lot = float('inf') if call_slope > 0 else float(np.max(expiry_check))
    max_loss_lot = float('inf') if call_slope < 0 else max(0.0, -float(np.min(expiry_check)))

    eff_vix = max(5.0, live_vix + sim_vix_shift)
    eff_dte = sim_dte_override if sim_dte_override is not None else dte_days
    T_years = max(eff_dte, 0.5) / 365.0
    sigma = eff_vix / 100.0
    r = 0.065
    if sim_dte_override is not None and sim_dte_override < dte_days:
        pnl_expiry = np.zeros_like(spot_range)
        for leg in display_legs:
            price = _bs_option_price(spot_range, leg["strike"], T_years, r, sigma, leg["type"])
            pnl_expiry += (price - leg["premium"]) * (1 if leg["action"] == "BUY" else -1)
    else:
        pnl_expiry = payoff_at(spot_range)
    pnl_exp_lot = pnl_expiry * lot_size

    # Compute exact break-even intersections at expiration strike intervals.
    be_points = [0.0] + strikes + [max(strikes) + max(1000., live_spot)]
    be_values = payoff_at(be_points)
    break_evens = []
    for left, right, yl, yr in zip(be_points, be_points[1:], be_values, be_values[1:]):
        if yl == 0:
            break_evens.append(left)
        if (yl < 0 < yr) or (yr < 0 < yl):
            break_evens.append(left - yl * (right - left) / (yr - yl))
    if be_values[-1] == 0:
        break_evens.append(be_points[-1])
    break_evens = sorted(set(round(x, 6) for x in break_evens))
    lower_be = break_evens[0] if break_evens else live_spot
    upper_be = break_evens[-1] if break_evens else live_spot

    stdev = live_spot * sigma * np.sqrt(T_years)
    # Normal-approximation, not a calibrated win probability.
    pop_percent = float((norm.cdf((upper_be - live_spot) / stdev) - norm.cdf((lower_be - live_spot) / stdev)) * 100)
    rr_ratio = max_loss_lot / max(max_profit_lot, 1)

    fig, ax = plt.subplots(figsize=(7, 3.2), facecolor="#111827")
    ax.set_facecolor("#111827")

    ax.fill_between(spot_range, pnl_exp_lot, 0, where=(pnl_exp_lot >= 0), facecolor="#10b981", alpha=0.3)
    ax.fill_between(spot_range, pnl_exp_lot, 0, where=(pnl_exp_lot < 0), facecolor="#ef4444", alpha=0.3)

    line_color = "#10b981" if max_profit_lot > 0 else "#ef4444"
    title_suffix = f" (Sim VIX: {eff_vix:.1f}, DTE: {eff_dte}d)" if (sim_vix_shift != 0 or sim_dte_override is not None) else ""
    ax.plot(spot_range, pnl_exp_lot, color=line_color, linewidth=2)
    
    ax.axhline(0, color="#475569", linestyle="--", linewidth=1.5)
    ax.axvline(live_spot, color="#38bdf8", linestyle=":", linewidth=2, label=f"Spot: {live_spot:.0f}")

    ax.set_title(f"Payoff{title_suffix} | BE: {lower_be:.0f} - {upper_be:.0f}", color="#f8fafc", fontsize=10, pad=8)
    ax.set_xlabel("NIFTY Spot Price", color="#94a3b8", fontsize=8)
    ax.set_ylabel(f"P&L (₹ / {lot_size} Qty)", color="#94a3b8", fontsize=8)

    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#1f2937")

    fig.tight_layout(pad=0.5)

    net_delta, net_theta = compute_strategy_greeks(display_legs, live_spot, eff_vix, eff_dte, lot_size)
    margin_info = estimate_margin_requirement(display_legs, lot_size, live_spot)

    return {
        "net_credit": net_credit,
        "max_profit": max_profit_lot,
        "max_loss": max_loss_lot,
        "pop": pop_percent,
        "rr": rr_ratio,
        "net_delta": net_delta,
        "net_theta": net_theta,
        "margin_info": margin_info,
        "fig": fig
    }
