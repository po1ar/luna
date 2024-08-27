import alpaca_trade_api as tradeapi
import pandas as pd
import time
import asyncio
from datetime import datetime, timedelta
import requests
from alpaca_trade_api.rest import REST, TimeFrame
from dotenv import load_dotenv
import os
import pytz

# Load environment variables from .env file
load_dotenv()

# Alpaca API credentials
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
BASE_URL = os.getenv('BASE_URL')

# Initialize Alpaca API
api = tradeapi.REST(API_KEY, API_SECRET, base_url=BASE_URL, api_version='v2')

# Trading parameters
symbol = os.getenv('SYMBOL')
timeframe = os.getenv('TIMEFRAME')
ema_fast = int(os.getenv('EMA_FAST'))
ema_slow = int(os.getenv('EMA_SLOW'))
profit_target = float(os.getenv('PROFIT_TARGET'))

# Webhook URL for daily stats and heartbeat
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = 300  # 5 minutes

# Time zone for EST
est = pytz.timezone('US/Eastern')

def get_historical_data():
    end = (datetime.now(est).replace(hour=0, minute=0, second=0, microsecond=0) -
           timedelta(days=1)).strftime('%Y-%m-%d')
    start = (
        datetime.now(est).replace(hour=0, minute=0, second=0, microsecond=0) -
        timedelta(days=31)).strftime('%Y-%m-%d')
    timeframe = TimeFrame.Minute
    bars = api.get_bars(symbol, timeframe, start=start, end=end,
                        limit=10000).df
    return bars

def calculate_ema(data, period):
    return data['close'].ewm(span=period, adjust=False).mean()

def check_buy_condition(fast_ema, slow_ema):
    return fast_ema.iloc[-1] > slow_ema.iloc[-1]

def check_sell_condition(entry_price, current_price):
    return (current_price - entry_price) >= profit_target

def send_daily_report(stats):
    payload = {
        'content':
        f"Daily Trading Report for {symbol}\n"
        f"Date: {datetime.now(est).date()}\n"
        f"Total Trades: {stats['total_trades']}\n"
        f"Profitable Trades: {stats['profitable_trades']}\n"
        f"Total Profit: ${stats['total_profit']:.2f}\n"
        f"Win Rate: {stats['win_rate']:.2f}%"
    }
    requests.post(WEBHOOK_URL, json=payload)

def send_webhook_message(message):
    payload = {
        'content': message
    }
    requests.post(WEBHOOK_URL, json=payload)

def heartbeat():
    send_webhook_message(f"Heartbeat: {datetime.now(est)} - Script is running")

def run_trading_algorithm():
    position = None
    entry_price = None
    daily_stats = {
        'total_trades': 0,
        'profitable_trades': 0,
        'total_profit': 0
    }
    last_heartbeat = time.time()
    report_sent = False
    test_trade_done = False

    while True:
        try:
            # Get current time in EST
            current_time = datetime.now(est).time()

            # Check if current time is within trading hours (9:30 AM to 4:30 PM EST)
            if current_time < datetime.strptime('09:30', '%H:%M').time() or current_time > datetime.strptime('16:30', '%H:%M').time():
                send_webhook_message(f"Outside trading hours: {current_time}. Sleeping...")
                time.sleep(60)  # Sleep for 1 minute before checking again
                continue

            # Perform test buy/sell operation once
            if not test_trade_done:
                test_symbol = 'T'  # Test ticker symbol
                # Test buy
                api.submit_order(symbol=test_symbol,
                                 qty=1,
                                 side='buy',
                                 type='market',
                                 time_in_force='day')
                test_buy_price = float(api.get_latest_trade(test_symbol).price)
                send_webhook_message(f"Test Buy: Bought 1 share of {test_symbol} at ${test_buy_price}")

                time.sleep(60)
                # Test sell
                api.submit_order(symbol=test_symbol,
                                 qty=1,
                                 side='sell',
                                 type='market',
                                 time_in_force='day')
                test_sell_price = float(api.get_latest_trade(test_symbol).price)
                send_webhook_message(f"Test Sell: Sold 1 share of {test_symbol} at ${test_sell_price}")

                test_trade_done = True

            # Get latest data and calculate EMAs
            df = get_historical_data()
            fast_ema = calculate_ema(df, ema_fast)
            slow_ema = calculate_ema(df, ema_slow)

            # Get the latest price using get_latest_trade
            current_price = float(api.get_latest_trade(symbol).price)

            # Check if we have an open position
            try:
                position = api.get_position(symbol)
                entry_price = float(position.avg_entry_price)
            except tradeapi.rest.APIError as e:
                if e.status_code == 404:
                    # No position found, set position and entry_price to None
                    position = None
                    entry_price = None
                else:
                    # If it's not a 404 error, re-raise the exception
                    raise

            if not position:
                if check_buy_condition(fast_ema, slow_ema):
                    # Buy 1 share
                    api.submit_order(symbol=symbol,
                                     qty=2,
                                     side='buy',
                                     type='market',
                                     time_in_force='day')
                    send_webhook_message(f"Bought 2 shares of {symbol} at ${current_price}")
                    entry_price = current_price
                    daily_stats['total_trades'] += 1
            else:
                # Debug logging for sell condition
                send_webhook_message(f"Checking sell condition: entry_price={entry_price}, current_price={current_price}, profit_target={profit_target}")
                if check_sell_condition(entry_price, current_price):
                    # Sell 1 share
                    api.submit_order(symbol=symbol,
                                     qty=2,
                                     side='sell',
                                     type='market',
                                     time_in_force='day')
                    profit = current_price - entry_price
                    send_webhook_message(f"Sold 2 shares of {symbol} at ${current_price}. Profit: ${profit:.2f}")
                    daily_stats['total_trades'] += 1
                    daily_stats['profitable_trades'] += 1
                    daily_stats['total_profit'] += profit
                    position = None
                    entry_price = None

            # Send daily report at the end of the trading day
            if current_time >= datetime.strptime('16:00', '%H:%M').time() and not report_sent:
                daily_stats['win_rate'] = (
                    daily_stats['profitable_trades'] /
                    daily_stats['total_trades']
                ) * 100 if daily_stats['total_trades'] > 0 else 0
                send_daily_report(daily_stats)
                daily_stats = {
                    'total_trades': 0,
                    'profitable_trades': 0,
                    'total_profit': 0
                }
                report_sent = True

            # Reset report_sent flag at the start of a new day
            if current_time < datetime.strptime('16:00', '%H:%M').time():
                report_sent = False

            # Heartbeat check
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
                heartbeat()
                last_heartbeat = time.time()

            time.sleep(60)  # Wait for 1 minute before next iteration

        except Exception as e:
            send_webhook_message(f"An error occurred: {e}")
            time.sleep(60)  # Wait for 1 minute before retrying

if __name__ == "__main__":
    run_trading_algorithm()
