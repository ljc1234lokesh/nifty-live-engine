# Test Strategy Cleanup Patch — 2026-11-14

- The known demonstration Strategy 1 is preserved in `backups/test_strategy_1_original_2026-11-14.json`.
- Bundled `saved_strategies.json` starts as `[]` for clean installs. **Deploying the ZIP alone will not necessarily remove existing GitHub-backed tracker records.**
- For existing installs: Open **Saved Live Tracker**, download the test backup, confirm it is not a broker position, and press **Remove ONLY confirmed test strategy**.
- The cleanup button matches a precise test-record fingerprint and leaves all other strategies unchanged. It saves remotely to GitHub and reports failure if the remote update fails. GitHub history also preserves the prior version.
- The original mapping validation continues to block any other invalid legacy strategy.
- Payoff chart no longer stretches its display back to NIFTY=0; calculation still examines S=0 for theoretical risk.
- DTE scenario slider is reset when a different expiry is selected.
- The app does not place broker orders.

## Not verified in this offline environment
Angel One login, GitHub write permissions, and Streamlit deployment. Test with a known demo record before relying on it.
