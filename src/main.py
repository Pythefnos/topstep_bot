import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
import importlib

# Import modules from the package
sys.path.append('.')  # ensure project root is in path (for running from project root)
from broker.topstep_api import TopstepAPI
from strategy.basic_strategy import BasicStrategy
from risk.risk_manager import RiskManager
from utils import logger as logger_utils

# Load configuration
import yaml
config_path = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
try:
    with open(config_path, "r") as cfg_file:
        config = yaml.safe_load(cfg_file)
except Exception as e:
    print(f"Error loading config file at {config_path}: {e}", file=sys.stderr)
    sys.exit(1)

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
    strat_cfg = config.get('strategy', {}).copy()

    # Validate required config values
    username = account_cfg.get('username')
    api_key = account_cfg.get('api_key')
    base_url = account_cfg.get('api_endpoint')
    account_id = account_cfg.get('account_id')
    symbol = trading_cfg.get('symbol')
    if not username or not api_key or account_id is None:
        logger.error("Missing account credentials or account_id in config. Please update config.yaml.")
        return
    if not symbol:
        logger.error("No trading symbol specified in config. Please update config.yaml.")
        return

    base_order_size = int(trading_cfg.get('order_size', 1))
    point_value = trading_cfg.get('point_value')  # may be None (TopstepAPI will set if None)

    # Initialize API
    try:
        account_id = int(account_id)
    except Exception as e:
        logger.error(f"Invalid account_id in config: {e}")
        return
    api = TopstepAPI(username=username,
                     api_key=api_key,
                     base_url=base_url,
                     account_id=account_id,
                     symbol=symbol,
                     point_value=point_value)

    # Initialize Strategy (allow dynamic strategy selection via config)
    strategy_name = strat_cfg.pop('name', None) or "BasicStrategy"
    try:
        if strategy_name.lower() in ("basicstrategy", "basic_strategy"):
            StrategyClass = BasicStrategy
        else:
            module_name = f"strategy.{strategy_name.lower()}"
            mod = importlib.import_module(module_name)
            StrategyClass = getattr(mod, strategy_name)
        strategy = StrategyClass(**strat_cfg)
    except Exception as e:
        logger.error(f"Failed to initialize strategy '{strategy_name}': {e}. Reverting to BasicStrategy with default parameters.")
        strategy = BasicStrategy(short_window=10, long_window=30)

    # Ensure moving average strategy parameters are valid (short_window < long_window)
    if hasattr(strategy, "short_window") and hasattr(strategy, "long_window"):
        if strategy.short_window >= strategy.long_window:
            logger.warning("Configured short_window >= long_window; adjusting long_window to short_window+1 for validity.")
            try:
                strategy.long_window = strategy.short_window + 1
            except Exception:
                logger.warning("Unable to adjust strategy windows; proceeding with given values.")

    # Connect to API (authenticate and resolve trading symbol)
    try:
        api.connect()
    except Exception as e:
        logger.error(f"Failed to connect to Topstep API: {e}")
        return  # Abort if cannot authenticate or resolve symbol

    # Initialize RiskManager with starting balance and risk limits
    starting_balance = risk_cfg.get('starting_balance')
    if starting_balance is not None:
        try:
            starting_balance = float(starting_balance)
        except Exception as e:
            logger.error(f"Invalid starting_balance in config: {e}. Defaulting to 0.")
            starting_balance = 0.0
    else:
        starting_balance = api.get_starting_balance() or 0.0
    if starting_balance == 0.0:
        logger.warning("Starting balance is 0. Using 0 as initial balance; trailing drawdown calculations may be inaccurate.")
    daily_loss_limit = float(risk_cfg.get('daily_loss_limit', 0.0))
    max_drawdown = float(risk_cfg.get('max_drawdown', 0.0))
    if daily_loss_limit <= 0 or max_drawdown <= 0:
        logger.error("Risk limits must be positive values. Please configure daily_loss_limit and max_drawdown in config.yaml.")
        return
    risk_manager = RiskManager(starting_balance=starting_balance,
                               daily_loss_limit=daily_loss_limit,
                               max_drawdown=max_drawdown)

    # Determine trading hours
    trading_hours = risk_cfg.get('trading_hours', {})
    start_time_str = trading_hours.get('start', "00:00:00")
    end_time_str = trading_hours.get('end', "23:59:59")
    try:
        start_time = datetime.strptime(start_time_str, "%H:%M:%S").time()
        end_time = datetime.strptime(end_time_str, "%H:%M:%S").time()
    except Exception as e:
        logger.error(f"Invalid time format in config: {e}. Defaulting to full-day trading window.")
        start_time = datetime.min.time()
        end_time = datetime.max.time()

    # Main trading loop
    current_position = 0   # net position (positive = long, negative = short, 0 = flat)
    entry_price = None     # price at which current_position was entered (for unrealized P/L)
    last_trade_time = None

    logger.info("Entering main trading loop.")
    try:
        while True:
            now = datetime.now()
            # Reset daily counters if a new day has started
            if last_trade_time and now.date() != last_trade_time.date():
                risk_manager.reset_day()
                logger.info("New trading day detected. Daily risk counters reset.")
                last_trade_time = now

            # Before trading window: sleep until trading start
            if now.time() < start_time:
                sleep_seconds = (datetime.combine(now.date(), start_time) - now).total_seconds()
                if sleep_seconds > 0:
                    logger.info(f"Waiting for trading start time at {start_time_str}...")
                    time.sleep(min(sleep_seconds, 60))
                continue

            # After trading hours: flatten any open position and wait for next session
            if now.time() >= end_time:
                if current_position != 0:
                    logger.info("Trading cutoff reached. Flattening open position.")
                    exit_price = None
                    try:
                        exit_price = api.get_latest_price()
                    except Exception as e:
                        logger.warning(f"Could not fetch price for end-of-day P&L calculation: {e}")
                    try:
                        api.flatten_position(symbol=api.symbol_id,
                                             size=abs(current_position),
                                             side=("sell" if current_position > 0 else "buy"))
                        logger.info(f"Position flattened at end of day (position was {current_position}).")
                        if entry_price is not None and exit_price is not None:
                            pl = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=exit_price,
                                                            size=current_position, point_value=api.point_value)
                            risk_manager.update_after_trade(pl)
                            logger.info(f"End-of-day flatten P&L = {pl:.2f}, current_balance = {risk_manager.current_balance:.2f}")
                        current_position = 0
                        entry_price = None
                        if risk_manager.trading_disabled:
                            logger.error("Risk limit breached by end-of-day flatten. Halting trading.")
                            break
                    except Exception as e:
                        logger.error(f"Error flattening position at cutoff: {e}")
                # Sleep in 1-minute intervals until next day's start time
                next_start = datetime.combine(now + timedelta(days=1), start_time)
                sleep_seconds = (next_start - now).total_seconds()
                logger.info("Outside trading hours. Pausing until next trading session.")
                time.sleep(min(sleep_seconds, 60))
                continue

            # Within trading hours: fetch market data and make trading decisions
            price = None
            try:
                price = api.get_latest_price()
            except Exception as e:
                logger.error(f"Failed to fetch latest price: {e}")
                # Try to reconnect and continue
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

            # Get recommended position from strategy (+1 = long, -1 = short, 0 = flat)
            recommended_pos = strategy.recommend_position(price)

            # Emergency kill-switch check (stop trading immediately if activated)
            if risk_manager.check_kill_switch():
                logger.warning("Emergency kill-switch activated! Flattening positions and stopping trading.")
                if current_position != 0:
                    try:
                        api.flatten_position(symbol=api.symbol_id,
                                             size=abs(current_position),
                                             side=("sell" if current_position > 0 else "buy"))
                    except Exception as e:
                        logger.error(f"Failed to flatten position on kill-switch: {e}")
                break

            # Execute strategy recommendation
            if recommended_pos is None:
                # No signal yet or no change in desired position
                pass
            elif recommended_pos == 0 and current_position != 0:
                # Strategy indicates to close any open position (go flat)
                logger.info(f"Strategy recommends closing current position (current_position={current_position}).")
                try:
                    api.place_order(symbol=api.symbol_id,
                                    side=("sell" if current_position > 0 else "buy"),
                                    size=abs(current_position))
                    logger.info("Position closed per strategy signal.")
                except Exception as e:
                    logger.error(f"Order placement failed while closing position: {e}")
                # Calculate and record realized P&L
                if entry_price is not None:
                    pl = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                    size=current_position, point_value=api.point_value)
                    risk_manager.update_after_trade(pl)
                    logger.info(f"Trade closed. P&L = {pl:.2f}, current_balance = {risk_manager.current_balance:.2f}")
                current_position = 0
                entry_price = None
                last_trade_time = now
                if risk_manager.trading_disabled:
                    logger.error("Risk limit exceeded (realized losses). Halting trading for the day.")
                    break

            elif recommended_pos == 1 and current_position <= 0:
                # Strategy wants to be long; we are flat or short
                old_position = current_position
                trade_size = (abs(old_position) if old_position < 0 else 0) + base_order_size
                if not risk_manager.allow_new_trade():
                    logger.warning("New trade blocked by risk manager (risk limits reached).")
                else:
                    try:
                        api.place_order(symbol=api.symbol_id, side="buy", size=trade_size)
                        logger.info(f"Entered LONG position (size={trade_size}).")
                        if old_position < 0:
                            # Closed a short position and went long
                            pl_close = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                                  size=old_position, point_value=api.point_value)
                            risk_manager.update_after_trade(pl_close)
                            logger.info(f"Trade closed. P&L = {pl_close:.2f}, current_balance = {risk_manager.current_balance:.2f}")
                            if risk_manager.trading_disabled:
                                logger.error("Risk limit exceeded (realized losses). Flattening new long position and halting trading.")
                                try:
                                    api.flatten_position(symbol=api.symbol_id, size=base_order_size, side="sell")
                                    logger.info("New LONG position flattened due to risk limit.")
                                except Exception as e:
                                    logger.error(f"Failed to flatten new position: {e}")
                                current_position = 0
                                entry_price = None
                                break
                        current_position = old_position + trade_size  # update net position
                        entry_price = price
                        last_trade_time = now
                    except Exception as e:
                        logger.error(f"Order placement failed (going long): {e}")
                        # No position change on failure

            elif recommended_pos == -1 and current_position >= 0:
                # Strategy wants to be short; we are flat or long
                old_position = current_position
                trade_size = (old_position if old_position > 0 else 0) + base_order_size
                if not risk_manager.allow_new_trade():
                    logger.warning("New trade blocked by risk manager (risk limits reached).")
                else:
                    try:
                        api.place_order(symbol=api.symbol_id, side="sell", size=trade_size)
                        logger.info(f"Entered SHORT position (size={trade_size}).")
                        if old_position > 0:
                            # Closed a long position and went short
                            pl_close = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                                  size=old_position, point_value=api.point_value)
                            risk_manager.update_after_trade(pl_close)
                            logger.info(f"Trade closed. P&L = {pl_close:.2f}, current_balance = {risk_manager.current_balance:.2f}")
                            if risk_manager.trading_disabled:
                                logger.error("Risk limit exceeded (realized losses). Flattening new short position and halting trading.")
                                try:
                                    api.flatten_position(symbol=api.symbol_id, size=base_order_size, side="buy")
                                    logger.info("New SHORT position flattened due to risk limit.")
                                except Exception as e:
                                    logger.error(f"Failed to flatten new position: {e}")
                                current_position = 0
                                entry_price = None
                                break
                        current_position = old_position - trade_size  # update net position
                        entry_price = price
                        last_trade_time = now
                    except Exception as e:
                        logger.error(f"Order placement failed (going short): {e}")
                        # No position change on failure

            # Update risk manager with unrealized P&L of any open position
            if current_position != 0 and entry_price is not None:
                unrealized_pl = risk_manager.calculate_pnl(entry_price=entry_price, exit_price=price,
                                                           size=current_position, point_value=api.point_value)
                if risk_manager.check_real_time_risk(unrealized_pl):
                    logger.error("Risk limit exceeded (including unrealized losses). Flattening position and halting trading for the day.")
                    try:
                        api.flatten_position(symbol=api.symbol_id,
                                             size=abs(current_position),
                                             side=("sell" if current_position > 0 else "buy"))
                    except Exception as e:
                        logger.error(f"Error flattening position on risk violation: {e}")
                    current_position = 0
                    entry_price = None
                    break

            # Small delay to avoid busy-waiting
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user (KeyboardInterrupt).")
    except Exception as e:
        logger.exception(f"Unexpected error in main loop: {e}")
    finally:
        # On exit, ensure any open position is flattened for safety
        if current_position != 0:
            try:
                api.flatten_position(symbol=api.symbol_id,
                                     size=abs(current_position),
                                     side=("sell" if current_position > 0 else "buy"))
                logger.info("Flattened any remaining open position before exit.")
            except Exception as e:
                logger.error(f"Failed to flatten position on exit: {e}")
        logger.info("Trading bot has stopped.")

if __name__ == "__main__":
    main()
