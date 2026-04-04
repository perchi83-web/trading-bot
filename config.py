# ============================================================
# config.py — Configuración con variables de entorno
# ============================================================
import os
from dotenv import load_dotenv
load_dotenv()

# --- TELEGRAM ---
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- EXCHANGE (Binance) ---
BINANCE_API_KEY = os.getenv("pkM6DXgRuTLFYrpMNofGJQ9wKw6YqAZb1B3w3EMI2czGFFgOFnR7Xa3X43cP0nRD", "")
BINANCE_SECRET  = os.getenv("rSJSpPkpKdGZHpsbjysxkjGw0W1NqTdJDm6DAVK2eqLxIJBevpRxc0TfFhcwxdK6", "")

# --- CLAUDE API ---
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

# --- QUÉ MONITOREAR ---
SIMBOLOS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "DOGE/USDT", "AVAX/USDT"]
STOCKS   = ["NVDA", "AAPL", "MSFT", "TSLA", "GLD", "USO", "TQQQ"]

# --- TEMPORALIDAD ---
INTERVALO          = "1h"
FRECUENCIA_MINUTOS = 60

# --- INDICADORES TÉCNICOS ---
RSI_PERIODO            = 14
RSI_SOBREVENDIDO       = 32
RSI_SOBRECOMPRADO      = 72

# --- GESTIÓN DE RIESGO ---
CAPITAL_TOTAL              = 100
RIESGO_POR_OPERACION       = 0.10
STOP_LOSS_PORCENTAJE       = 0.03
TAKE_PROFIT_PORCENTAJE     = 0.08

# --- MODO SEGURO ---
MODO_PAPER_TRADING = True

# --- MERCADO DE FUTUROS ---
MODO_MERCADO = 'future'
LEVERAGE     = 5

# LLAVE SECRETA DE MI AGENTE IA (GEMINI)
GEMINI_API_KEY = "AIzaSyA7hIHy9pBla4NdaCwmSqE76V7hl8H8_bE"