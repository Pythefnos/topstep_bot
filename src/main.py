import sys
import time
import logging
from datetime import datetime, timedelta

# Import modules from the package
sys.path.append('.')  # ensure current directory is in path (if running from project root)
from broker.topstep_api import TopstepAPI
from strategy.basic_strategy import BasicStrategy
from risk.risk_manager import RiskManager
from utils import logger as logger_utils

# Load configuration
import yaml
with open("config/config.yaml", "r") as cfg_file:
    config = yaml.safe_load(cfg_file)

# Initialize logger as per config
log_level = config.get('logging', {}).get('level', 'INFO')
log_file = config.get('logging', {}).get('file', None)
logger = logger_utils.init_logger(log_file=log_file, level=log_level)
logger.info("Starting Topstep Trading Bot...")

def main():
    """Main function to run the trading bot."""
    # Extract configuration sections
    account_cfg = config.get('account', {})
    trading_cfg = config.get('trading', {})
    risk_cfg = config.get('risk', {})
    strat_cfg = config.get('strategy', {})

    symbol = trading_cfg.get('symbol')
    order_size = int(trading_cfg.get('order_size', 1))
    point_value = trading_cfg.get('point_value')  # may be None if we plan to auto-set from API

    # Setup API, Strategy, and Risk Manager
    api = TopstepAPI(
        username=account_cfg.get('username'),
        api_key=account_cfg.get('api_key'),
        base_url=account_cfg.get('api_endpoint'),
        account_id=account_cfg.get('account_id'),
        symbol=symbol,
        point_value=point_value  # allow API class to determine point value if None
    )
    strategy = BasicStrategy(short_window=int(strat_cfg.get('short_window', 10)),
                             long_window=int(strat_cfg.get('long_window', 30)))
    # If short_window >= long_window, adjust (to ensure a valid crossover strategy)
    if strategy.short_window >= strategy.long_window:
        logger.warning("Strategy short_window is not less than long_window. Adjusting windows for validity.")
        if strategy.short_window >= strategy.long_window:
            strategy.long_window = strategy.short_window + 1

    # Connect to API (authenticate and resolve symbol)
    try:
        api.connect()
    except Exception as e:
        logger.error(f"Failed to connect to Topstep API: {e}")
        return  # Abort if cannot connect (no trading possible)

    # Initialize risk manager with starting balance and risk limits
    # If available, get account starting balance (for combine, use initial balance; otherwise we could fetch via API)
    starting_balance = api.get_starting_balance() or 0.0
    daily_loss_limit = float(risk_cfg.get('daily_loss_limit', 0))
    max_drawdown = float(risk_cfg.get('max_drawdown', 0))
    risk_manager = RiskManager(starting_balance=starting_balance,
                               daily_loss_limit=daily_loss_limit,
                               max_drawdown=max_drawdown)

    # Determine trading hours cutoff times
    trading_hours = risk_cfg.get('trading_hours', {})
    start_time_str = trading_hours.get('start', "00:00:00")
    end_time_str = trading_hours.get('end', "23:59:59")
    try:
        today = datetime.now()
        start_time = datetime.strptime(start_time_str, "%H:%M:%S").time()
        end_time = datetime.strptime(end_time_str, "%H:%M:%S").time()
    except Exception as e:
        logger.error(f"Invalid time format in config: {e}. Using full day trading window.")
        start_time = datetime.min.time()
        end_time = datetime.max.time()

    # Main trading loop
    current_position = 0  # current net position (positive = long, negative = short, 0 = flat)
    entry_price = None    # price at which current_position was entered (for unrealized P/L)
    last_trade_time = None

    logger.info("Entering main trading loop.")
    try:
        while True:
            now = datetime.now()
            # Handle daily reset of risk at end of trading day (assuming reset at 5:00 PM CT or end_time)
            # If we've passed the trading end_time and not yet reset for the day:
            if last_trade_time and now.date() != last_trade_time.date():
                # New day: reset daily P/L tracking
                risk_manager.reset_day()
                logger.info("New trading day. Daily risk counters reset.")
                last_trade_time = now  # update to today

            # Check trading session hours
            if now.time() < start_time:
                # Before trading window: sleep until start_time
                sleep_seconds = (datetime.combine(now.date(), start_time) - now).total_seconds()
                if sleep_seconds > 0:
                    logger.info(f"Waiting for trading start time at {start_time_str}...")
                    time.sleep(min(sleep_seconds, 60))  # sleep in chunks (or until start)
                continue  # re-check after waking
            if now.time() >= end_time:
                # After trading hours: flatten any open positions and break or sleep till next day
                if current_position != 0:
                    logger.info("Trading cutoff reached. Flattening open position.")
                    try:
                        api.flatten_position(symbol=api.symbol_id, size=abs(current_position), side=("sell" if current_position > 0 else "buy"))
                        logger.info(f"Position flattened at end of day (position was {current_position}).")
                        current_position = 0
                        entry_price = None
                    except Exception as e:
                        logger.error(f"Error flattening position at cutoff: {e}")
                # Calculate sleep duration until next trading start (assume next day)
                # Add one day to now's date for next trading window
                next_start_dt = datetime.combine(now + timedelta(days=1), start_time)
                sleep_seconds = (next_start_dt - now).total_seconds()
                logger.info("Outside trading hours. Pausing trading until next session.")
                time.sleep(min(sleep_seconds, 60))  # sleep in shorter intervals (1 min) to allow graceful interrupt
                if sleep_seconds > 60:
                    continue  # continue loop (will loop until time reaches next start)
                else:
                    # If less than a minute to next session (rare case), just break to re-evaluate immediately
                    continue

            # Within trading hours: get market data and make trading decisions
            price = None
            try:
                price = api.get_latest_price()
            except Exception as e:
                logger.error(f"Failed to fetch latest price: {e}")
                # Attempt to reconnect and continue
                try:
                    api.connect()
                    logger.info("Reconnected to API after data fetch failure.")
                except Exception as e2:
                    logger.error(f"Reconnection failed: {e2}. Retrying in 5 seconds...")
                    time.sleep(5)
                continue  # skip this iteration if price not obtained

            if price is None:
                # No price data, skip iteration
                time.sleep(1)
                continue

            # Feed price to strategy to get recommended position (+1 long, -1 short, 0 flat)
            recommended_pos = strategy.recommend_position(price)
            # Check if kill-switch (emergency stop) triggered (YubiKey integration stub)
            if risk_manager.check_kill_switch():
                logger.warning("Emergency kill-switch activated! Flattening all positions and stopping trading.")
                if current_position != 0:
                    try:
                        api.flatten_position(symbol=api.symbol_id, size=abs(current_position), side=("sell" if current_position > 0 else "buy"))
                    except Exception as e:
                        logger.error(f"Failed to flatten positions on kill-switch: {e}")
                break  # exit the trading loop immediately

            # Only trade if strategy recommends a position different from current
            if recommended_pos is None:
                # Strategy not ready (e.g. not enough data) or no change
                pass
            elif recommended_pos == 0 and current_position != 0:
                # Strategy says go flat (close any open position)
                logger.info(f"Strategy recommends closing position (current_position={current_position}).")
                try:
                    api.place_order(symbol=api.symbol_id, side=("sell" if current_position > 0 else "buy"), size=abs(current_position))
                    logger.info("Position closed as per strategy signal.")
                except Exception as e:
                    logger.error(f"Order placement failed when closing position: {e}")
                # Calculate realized P&L from the trade
                if entry_price is not None:
                    pl = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price, size=current_position, point_value=api.point_value)
                    risk_manager.update_after_trade(pl)
                    logger.info(f"Trade closed. P&L={pl:.2f}, current_balance={risk_manager.current_balance:.2f}")
                current_position = 0
                entry_price = None
                last_trade_time = now
            elif recommended_pos == 1 and current_position <= 0:
                # Strategy wants to be long and we are not long (either flat or short)
                order_side = "buy"
                order_size = abs(current_position) + order_size if current_position < 0 else order_size
                # If short, order_size = (abs(short_position) + order_size) to flip; if flat, it's just order_size.
                # Risk check: ensure taking this trade won't immediately violate daily or drawdown (e.g., if already near limits)
                if not risk_manager.allow_new_trade():
                    logger.warning("New trade blocked by risk manager (daily loss or drawdown limit reached).")
                else:
                    try:
                        api.place_order(symbol=api.symbol_id, side=order_side, size=order_size)
                        logger.info(f"Entered LONG position (size={order_size}).")
                        # If we were short, that order closes short and opens long net; if flat, it's a fresh long.
                        # Determine new current position:
                        current_position = current_position + order_size  # if was negative, this effectively subtracts that negative leaving positive
                        entry_price = price  # set entry price for new position
                        last_trade_time = now
                    except Exception as e:
                        logger.error(f"Order placement failed (going long): {e}")
                        # If order failed, do not change position
            elif recommended_pos == -1 and current_position >= 0:
                # Strategy wants to be short and we are not short (either flat or long)
                order_side = "sell"
                order_size = abs(current_position) + order_size if current_position > 0 else order_size
                if not risk_manager.allow_new_trade():
                    logger.warning("New trade blocked by risk manager (daily loss or drawdown limit reached).")
                else:
                    try:
                        api.place_order(symbol=api.symbol_id, side=order_side, size=order_size)
                        logger.info(f"Entered SHORT position (size={order_size}).")
                        current_position = current_position - order_size  # e.g., if was long, subtracting larger number makes negative; if flat, becomes -order_size
                        entry_price = price
                        last_trade_time = now
                    except Exception as e:
                        logger.error(f"Order placement failed (going short): {e}")
                        # If failed, do not change position

            # Update risk manager for unrealized P&L and check for violations
            if current_position != 0 and entry_price is not None:
                unrealized_pl = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price, size=current_position, point_value=api.point_value)
                if risk_manager.check_real_time_risk(unrealized_pl):
                    # Risk violation occurred (e.g. hit daily loss limit with current drawdown)
                    logger.error("Risk limits exceeded (including unrealized losses). Flattening position and halting trading for the day.")
                    try:
                        api.flatten_position(symbol=api.symbol_id, size=abs(current_position), side=("sell" if current_position > 0 else "buy"))
                    except Exception as e:
                        logger.error(f"Error flattening position on risk violation: {e}")
                    current_position = 0
                    entry_price = None
                    break  # exit loop - trading stopped due to risk violation

            # Small delay to avoid tight looping (polling interval for market data)
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user (KeyboardInterrupt).")
    except Exception as e:
        logger.exception(f"Unexpected error in main loop: {e}")
    finally:
        # Ensure any open position is closed on exit for safety
        if current_position != 0:
            try:
                api.flatten_position(symbol=api.symbol_id, size=abs(current_position), side=("sell" if current_position > 0 else "buy"))
                logger.info("Flattened any open position before exit.")
            except Exception as e:
                logger.error(f"Failed to flatten position on exit: {e}")
        logger.info("Trading bot has stopped.")

if __name__ == "__main__":
    main()
