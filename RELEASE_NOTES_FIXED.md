# NIFTY Live Engine — safety patch 2026-11-14

## Included repairs
- Removed hard-coded fallback NIFTY / BANKNIFTY / SENSEX / VIX quotes and synthetic option premiums.
- Pauses if Angel session, NIFTY/VIX quote, instrument master, option OI, or strategy-leg LTP is unavailable.
- Uses exact Angel instrument-master symbol and token for **new** strategy legs; no reconstructed symbol names.
- Rejects saved tracker records with mismatched token, symbol, strike or expiry rather than reporting fabricated live P&L. Original saved_strategies.json is preserved unchanged.
- Resolves tokens/symbols again for edited strikes (once the existing record is valid).
- Computes expiration payoff bounds using strike breakpoints rather than just a spot ±800 scan. Simulation remains model-based.
- Alerts on Telegram API `ok` failures and retries failed stop-loss notification on the next refresh; no automatic broker exit.
- Shows a warning on non-success GitHub backup responses.

## Important limitations
- This is **an analysis and alert-only dashboard**, not a broker order executor. Exit Trade removes tracker entry; it does not place an exit order.
- Telegram alerts depend on the app running and successfully refreshing. They are not broker-side stop orders.
- Margin displayed remains an **unverified rough estimate**; do not use it to size orders. Check official broker margin.
- POP and Greeks are theoretical estimates, not assured probabilities or exchange-calculated live Greeks.
- Fees, taxes and slippage are not yet included in P&L.
- Older saved strategy has inconsistent symbols/tokens. Its data has deliberately **not** been silently changed. Repair it only against current Angel instrument master; if expired, archive outside the live tracker.
- Broker login, live feeds, Telegram, and GitHub sync were **not** tested in this offline environment. Python source compilation and isolated payoff tests were performed.

## Install
1. Backup GitHub repo and `.streamlit/secrets.toml` separately.
2. Replace project files from this ZIP; keep your own secrets outside source control.
3. Install `pip install -r requirements.txt`, then run `streamlit run app.py`.
4. Test **without live orders** first. Confirm symbol/strike/expiry and live LTP with broker terminal, then test alerts.
5. Check that any older mismatched tracker data is resolved before relying on the tracker.
