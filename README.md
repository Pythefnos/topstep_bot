# Topstep Trading Bot (Lean-Core Version)

This is a lean-core trading bot designed for Topstep accounts using the **TopstepX API** (ProjectX). It is structured for clarity and safety, emphasizing strict risk management and ease of maintenance.

## Features

- **Modular Design:** Separate modules for API communication, strategy logic, risk management, and utilities.
- **Configurable:** All key settings (API keys, account details, trading parameters, risk limits, trading hours) are in `config/config.yaml` for easy adjustment.
- **TopstepX API Integration:** Uses the TopstepX (ProjectX) API for market data and order execution (via REST calls).
- **Basic Strategy:** Includes a sample Moving Average Crossover strategy (`basic_strategy.py`) as a placeholder. This can be replaced or extended with more complex strategies.
- **Robust Risk Management:** Enforces Topstep risk rules (Daily Loss Limit, Max Drawdown) via the `risk_manager.py` module. The bot will automatically flatten positions and halt trading if rules are violated.
- **Logging:** Comprehensive logging to console and file (via `utils/logger.py`) for debugging and audit trails.
- **Graceful Handling:** The bot handles API errors with retries and will attempt to reconnect on disconnects, making it "hard to kill" due to technical errors. A placeholder for a YubiKey emergency kill-switch is included for future implementation.

## Project Structure

topstep_bot/
├── README.md
├── requirements.txt
├── config/
│ └── config.yaml
└── src/
├── main.py
├── broker/
│ └── topstep_api.py
├── strategy/
│ └── basic_strategy.py
├── risk/
│ └── risk_manager.py
└── utils/
└── logger.py
markdown
Copy
Edit

*(A `tests/` directory can be added for unit tests if needed.)*

## Installation

1. **Python Version:** Ensure you have Python 3.11 or above.
2. **Install Dependencies:**  
   ```bash
   pip install -r requirements.txt
This installs libraries like PyYAML for config parsing and requests for API calls.
Configuration
Open config/config.yaml and update the placeholders:
Account Credentials: Provide your Topstep username (usually your email) and TopstepX API key. You may generate an API key via the TopstepX (ProjectX) dashboard.
API Endpoint: The base URL for the TopstepX API. By default it's the demo endpoint; replace with live endpoint if applicable.
Account ID: Your Topstep account ID (needed for placing orders).
Trading Parameters: Set your target trading symbol (or contract) and order size. You can specify a root symbol (e.g. "ES") or a full contract code (e.g. "ESM25"); the bot will resolve it to the proper contract ID. Also set point_value (the profit/loss value per 1.0 price move for the instrument, e.g. 50 for ES, 20 for NQ, etc.) if not using automatic resolution.
Risk Limits: Define your Personal Daily Loss Limit (daily_loss_limit) and Max Drawdown (max_drawdown) in dollar terms according to your Topstep account rules.
Trading Hours: Specify the allowed trading window (start and end in HH:MM:SS, 24h format, Central Time). The bot will not initiate new trades outside these hours and will flatten any open positions after the cut-off time.
Logging: Adjust log level if needed (default INFO) and the log file path.
Usage
After configuring, run the bot:
bash
Copy
Edit
python3 src/main.py
The bot will authenticate with TopstepX, then begin retrieving market data and executing the strategy. It will print log output to console and also write logs to the file specified.
How It Works
main.py loads configuration, sets up logging, and initializes the TopstepAPI, BasicStrategy, and RiskManager classes.
The bot authenticates to the TopstepX API and, if necessary, resolves the chosen symbol to a specific contract ID.
It enters a loop during allowed trading hours:
Fetches the latest market price for the instrument.
Feeds the price to the strategy to get a recommended position (long, short, or flat).
Checks with the risk manager before executing any trade. If a trade would violate risk limits, it is skipped or the bot halts.
Places orders via the TopstepAPI module to enter or exit positions as needed to match the strategy's recommendation.
Continuously monitors risk (including unrealized P&L) and will flatten (close all positions) immediately if a risk limit is hit (e.g., hitting the daily loss limit or trailing drawdown).
The bot will automatically stop trading at the configured end time each day, closing any open positions. It can remain running and will resume trading the next session (with daily risk counters reset at the start of the new trading day).
The code includes a TODO stub for a YubiKey kill-switch: in the future, a YubiKey or other trigger could be integrated to immediately stop trading and flatten positions on user command.
Extensibility
Strategies: You can create more strategy modules under src/strategy and plug them into main.py. The strategy just needs to output desired position (long/short/flat) given market data.
Risk Rules: The risk manager can be extended to include additional rules (e.g., max position size, max trades per day, news event lockouts, etc.). Currently it focuses on daily loss and max drawdown.
API Integration: The TopstepAPI class uses REST calls for simplicity. For more real-time performance, you could integrate the WebSocket feeds provided by TopstepX for live market data and perhaps orders/trades updates.
Testing: A tests suite (not included by default) can be added to verify strategy logic and risk checks with simulated data.
Disclaimer: Use this bot responsibly and at your own risk. Always test with small size or in a simulated environment first. Ensure compliance with Topstep's Terms of Use (no VPS, no prohibited activity). Topstep will not undo trades made by custom tools, so safe coding and thorough testing are crucial.
shell
Copy
Edit

# File: requirements.txt
```text
PyYAML>=6.0
requests>=2.0
