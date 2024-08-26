import alpaca_trade_api as tradeapi
import pandas as pd
import time
import asyncio
from datetime import datetime, timedelta
import requests
from alpaca_trade_api.rest import REST, TimeFrame
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Alpaca API credentials
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
BASE_URL = os.getenv('BASE_URL')
print(API_KEY, API_SECRET, BASE_URL)
# Initialize Alpaca API
api = tradeapi.REST(API_KEY, API_SECRET, base_url=BASE_URL, api_version='v2')

# Trading parameters
symbol = os.getenv('SYMBOL')
timeframe = os.getenv('TIMEFRAME')
ema_fast = int(os.getenv('EMA_FAST'))
ema_slow = int(os.getenv('EMA_SLOW'))
profit_target = float(os.getenv('PROFIT_TARGET'))

# Webhook URL for daily stats
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

def get_historical_data():
    end = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) -
           timedelta(days=1)).strftime('%Y-%m-%d')
    start = (
        datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) -
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
        f"Date: {datetime.now().date()}\n"
        f"Total Trades: {stats['total_trades']}\n"
        f"Profitable Trades: {stats['profitable_trades']}\n"
        f"Total Profit: ${stats['total_profit']:.2f}\n"
        f"Win Rate: {stats['win_rate']:.2f}%"
    }
    requests.post(WEBHOOK_URL, json=payload)


def run_trading_algorithm():
    position = None
    entry_price = None
    daily_stats = {
        'total_trades': 0,
        'profitable_trades': 0,
        'total_profit': 0
    }

    while True:
        try:
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
                    print(f"Bought 2 share of {symbol} at ${current_price}")
                    entry_price = current_price
                    daily_stats['total_trades'] += 1
            else:
                if check_sell_condition(entry_price, current_price):
                    # Sell 1 share
                    api.submit_order(symbol=symbol,
                                     qty=2,
                                     side='sell',
                                     type='market',
                                     time_in_force='day')
                    profit = current_price - entry_price
                    print(
                        f"Sold 2 share of {symbol} at ${current_price}. Profit: ${profit:.2f}"
                    )
                    daily_stats['total_trades'] += 1
                    daily_stats['profitable_trades'] += 1
                    daily_stats['total_profit'] += profit
                    position = None
                    entry_price = None

            # Send daily report at the end of the trading day
            if datetime.now().time() >= datetime.strptime('16:00',
                                                          '%H:%M').time():
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

            time.sleep(60)  # Wait for 5 minutes before next iteration

        except Exception as e:
            print(f"An error occurred: {e}")
            time.sleep(60)  # Wait for 1 minute before retrying


if __name__ == "__main__":
    run_trading_algorithm()
