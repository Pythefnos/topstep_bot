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
    base_order_size = int(trading_cfg.get('order_size', 1))
    point_value = trading_cfg.get('point_value')  # may be None (TopstepAPI will set if None)

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
    # Ensure short_window < long_window for a valid crossover strategy
    if strategy.short_window >= strategy.long_window:
        logger.warning("Strategy short_window is not less than long_window. Adjusting windows for validity.")
        strategy.long_window = strategy.short_window + 1

    # Connect to API (authenticate and resolve symbol)
    try:
        api.connect()
    except Exception as e:
        logger.error(f"Failed to connect to Topstep API: {e}")
        return  # Abort if cannot connect (no trading possible)

    # Initialize risk manager with starting balance and risk limits
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
        logger.error(f"Invalid time format in config: {e}. Using full-day trading window.")
        start_time = datetime.min.time()
        end_time = datetime.max.time()

    # Main trading loop
    current_position = 0  # net position (positive = long, negative = short, 0 = flat)
    entry_price = None    # price at which current_position was entered (for unrealized P/L calc)
    last_trade_time = None

    logger.info("Entering main trading loop.")
    try:
        while True:
            now = datetime.now()
            # Daily reset at end of day (assuming risk reset at session start)
            if last_trade_time and now.date() != last_trade_time.date():
                risk_manager.reset_day()
                logger.info("New trading day. Daily risk counters reset.")
                last_trade_time = now

            # Before trading window: sleep until start_time
            if now.time() < start_time:
                sleep_seconds = (datetime.combine(now.date(), start_time) - now).total_seconds()
                if sleep_seconds > 0:
                    logger.info(f"Waiting for trading start time at {start_time_str}...")
                    time.sleep(min(sleep_seconds, 60))
                continue

            # After trading hours: flatten positions and pause until next session
            if now.time() >= end_time:
                if current_position != 0:
                    logger.info("Trading cutoff reached. Flattening open position.")
                    try:
                        api.flatten_position(symbol=api.symbol_id, size=abs(current_position),
                                             side=("sell" if current_position > 0 else "buy"))
                        logger.info(f"Position flattened at end of day (position was {current_position}).")
                        current_position = 0
                        entry_price = None
                    except Exception as e:
                        logger.error(f"Error flattening position at cutoff: {e}")
                # Sleep until next day's start time (in 1-minute intervals for interruptibility)
                next_start = datetime.combine(now + timedelta(days=1), start_time)
                sleep_seconds = (next_start - now).total_seconds()
                logger.info("Outside trading hours. Pausing until next trading session.")
                time.sleep(min(sleep_seconds, 60))
                if sleep_seconds > 60:
                    continue
                else:
                    continue  # re-check loop when less than 60 sec to start

            # Within trading hours: fetch market data and make trading decisions
            price = None
            try:
                price = api.get_latest_price()
            except Exception as e:
                logger.error(f"Failed to fetch latest price: {e}")
                # Attempt reconnect and continue
                try:
                    api.connect()
                    logger.info("Reconnected to API after data fetch failure.")
                except Exception as e2:
                    logger.error(f"Reconnection failed: {e2}. Retrying in 5 seconds...")
                    time.sleep(5)
                continue
            if price is None:
                time.sleep(1)
                continue

            # Get recommended position from strategy (+1 long, -1 short, 0 flat)
            recommended_pos = strategy.recommend_position(price)
            # Emergency kill-switch check
            if risk_manager.check_kill_switch():
                logger.warning("Emergency kill-switch activated! Flattening all positions and stopping trading.")
                if current_position != 0:
                    try:
                        api.flatten_position(symbol=api.symbol_id, size=abs(current_position),
                                             side=("sell" if current_position > 0 else "buy"))
                    except Exception as e:
                        logger.error(f"Failed to flatten positions on kill-switch: {e}")
                break

            # Act on strategy recommendation if it differs from current position
            if recommended_pos is None:
                # Not enough data or no signal change
                pass
            elif recommended_pos == 0 and current_position != 0:
                # Strategy recommends closing any open position (going flat)
                logger.info(f"Strategy recommends closing position (current_position={current_position}).")
                try:
                    api.place_order(symbol=api.symbol_id, side=("sell" if current_position > 0 else "buy"),
                                    size=abs(current_position))
                    logger.info("Position closed as per strategy signal.")
                except Exception as e:
                    logger.error(f"Order placement failed when closing position: {e}")
                # Calculate realized P&L from the trade
                if entry_price is not None:
                    pl = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                    size=current_position, point_value=api.point_value)
                    risk_manager.update_after_trade(pl)
                    logger.info(f"Trade closed. P&L={pl:.2f}, current_balance={risk_manager.current_balance:.2f}")
                current_position = 0
                entry_price = None
                last_trade_time = now
                if risk_manager.trading_disabled:
                    logger.error("Risk limits exceeded (realized losses). Halting trading for the day.")
                    break
            elif recommended_pos == 1 and current_position <= 0:
                # Strategy wants to be long, and we are not currently long (either flat or short)
                old_position = current_position
                trade_size = abs(old_position) + base_order_size if old_position < 0 else base_order_size
                # If short, trade_size covers closing the short and opening new long; if flat, it's just base_order_size.
                if not risk_manager.allow_new_trade():
                    logger.warning("New trade blocked by risk manager (daily loss or drawdown limit reached).")
                else:
                    try:
                        api.place_order(symbol=api.symbol_id, side="buy", size=trade_size)
                        logger.info(f"Entered LONG position (size={trade_size}).")
                        if old_position < 0:
                            # Realized P&L from closing the short position
                            pl_close = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                                  size=old_position, point_value=api.point_value)
                            risk_manager.update_after_trade(pl_close)
                            logger.info(f"Trade closed. P&L={pl_close:.2f}, current_balance={risk_manager.current_balance:.2f}")
                            if risk_manager.trading_disabled:
                                logger.error("Risk limits exceeded (realized losses). Flattening new position and halting trading.")
                                try:
                                    api.flatten_position(symbol=api.symbol_id, size=base_order_size, side="sell")
                                    logger.info("New LONG position flattened due to risk limit.")
                                except Exception as e:
                                    logger.error(f"Failed to flatten new position: {e}")
                                current_position = 0
                                entry_price = None
                                break
                        current_position = old_position + trade_size  # new net position (long)
                        entry_price = price
                        last_trade_time = now
                    except Exception as e:
                        logger.error(f"Order placement failed (going long): {e}")
                        # If order failed, no position change
            elif recommended_pos == -1 and current_position >= 0:
                # Strategy wants to be short, and we are not currently short (either flat or long)
                old_position = current_position
                trade_size = old_position + base_order_size if old_position > 0 else base_order_size
                if not risk_manager.allow_new_trade():
                    logger.warning("New trade blocked by risk manager (daily loss or drawdown limit reached).")
                else:
                    try:
                        api.place_order(symbol=api.symbol_id, side="sell", size=trade_size)
                        logger.info(f"Entered SHORT position (size={trade_size}).")
                        if old_position > 0:
                            pl_close = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                                  size=old_position, point_value=api.point_value)
                            risk_manager.update_after_trade(pl_close)
                            logger.info(f"Trade closed. P&L={pl_close:.2f}, current_balance={risk_manager.current_balance:.2f}")
                            if risk_manager.trading_disabled:
                                logger.error("Risk limits exceeded (realized losses). Flattening new position and halting trading.")
                                try:
                                    api.flatten_position(symbol=api.symbol_id, size=base_order_size, side="buy")
                                    logger.info("New SHORT position flattened due to risk limit.")
                                except Exception as e:
                                    logger.error(f"Failed to flatten new position: {e}")
                                current_position = 0
                                entry_price = None
                                break
                        current_position = old_position - trade_size  # new net position (short)
                        entry_price = price
                        last_trade_time = now
                    except Exception as e:
                        logger.error(f"Order placement failed (going short): {e}")
                        # If order failed, no position change

            # Update risk manager for unrealized P&L of open position
            if current_position != 0 and entry_price is not None:
                unrealized_pl = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                           size=current_position, point_value=api.point_value)
                if risk_manager.check_real_time_risk(unrealized_pl):
                    logger.error("Risk limits exceeded (including unrealized losses). Flattening position and halting trading for the day.")
                    try:
                        api.flatten_position(symbol=api.symbol_id, size=abs(current_position),
                                             side=("sell" if current_position > 0 else "buy"))
                    except Exception as e:
                        logger.error(f"Error flattening position on risk violation: {e}")
                    current_position = 0
                    entry_price = None
                    break

            # Polling delay to avoid busy-wait
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user (KeyboardInterrupt).")
    except Exception as e:
        logger.exception(f"Unexpected error in main loop: {e}")
    finally:
        # On exit, ensure any open position is flattened for safety
        if current_position != 0:
            try:
                api.flatten_position(symbol=api.symbol_id, size=abs(current_position),
                                     side=("sell" if current_position > 0 else "buy"))
                logger.info("Flattened any open position before exit.")
            except Exception as e:
                logger.error(f"Failed to flatten position on exit: {e}")
        logger.info("Trading bot has stopped.")

if __name__ == "__main__":
    main()
