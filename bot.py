# ============================================================
# bot.py — El cerebro principal del agente de alertas
# ============================================================
#
# FLUJO COMPLETO:
#
#   1. Cada X minutos se activa el bot
#   2. Descarga las últimas velas del mercado (OHLCV)
#   3. Calcula el indicador RSI
#   4. Evalúa si hay una señal (compra / venta / neutral)
#   5. Si hay señal → envía alerta a Telegram
#   6. Registra todo en un archivo de log
#
# ============================================================

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import ccxt                     # Conecta con exchanges (Binance, etc.)
import pandas as pd             # Maneja tablas de datos
import yfinance as yf           # Datos de acciones (NVDA, AAPL, etc.)
import requests                 # Envía mensajes a Telegram
import logging                  # Guarda registros del bot
from datetime import datetime   # Fecha y hora
from apscheduler.schedulers.blocking import BlockingScheduler  # Tareas programadas

import config                   # Nuestro archivo de configuración


# ============================================================
# 1. CONFIGURAR EL REGISTRO (LOG)
# ============================================================
# Guarda en pantalla Y en archivo lo que hace el bot
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),                        # Muestra en consola
        logging.FileHandler("registro_bot.log")         # Guarda en archivo
    ]
)
log = logging.getLogger(__name__)


# ============================================================
# 2. CONECTAR CON EL EXCHANGE
# ============================================================
def conectar_exchange():
    """
    Crea la conexión con Binance usando las credenciales del config.
    Retorna el objeto exchange listo para consultar precios.
    """
    exchange = ccxt.binance({
        "apiKey": config.BINANCE_API_KEY,
        "secret": config.BINANCE_SECRET,
    })
    log.info("✅ Conectado al exchange correctamente")
    return exchange


# ============================================================
# 3. OBTENER DATOS DEL MERCADO
# ============================================================
def obtener_velas(exchange, simbolo, intervalo, limite=100):
    """
    Descarga las últimas N velas (candlesticks) del mercado.

    Cada vela contiene:
        - timestamp : cuándo ocurrió
        - open      : precio de apertura
        - high      : precio máximo
        - low       : precio mínimo
        - close     : precio de cierre  ← el más importante
        - volume    : volumen negociado

    Retorna un DataFrame (tabla) de pandas.
    """
    datos_crudos = exchange.fetch_ohlcv(simbolo, intervalo, limit=limite)

    df = pd.DataFrame(datos_crudos, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

    log.info(f"📊 {limite} velas obtenidas para {simbolo} ({intervalo})")
    return df


# ============================================================
# 3b. OBTENER DATOS DE ACCIONES (NVDA, AAPL, etc.)
# ============================================================
def obtener_velas_stock(simbolo, intervalo="15m", limite=100):
    """
    Descarga datos históricos de una acción usando Yahoo Finance.
    No requiere API Key — es completamente gratuito.
    """
    ticker = yf.Ticker(simbolo)
    df = ticker.history(period="5d", interval=intervalo)
    df = df.tail(limite).reset_index()

    # Normalizar nombres de columnas igual que crypto
    col_time = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={
        col_time: "timestamp",
        "Open": "open", "High": "high",
        "Low": "low",  "Close": "close", "Volume": "volume"
    })
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]

    log.info(f"📊 {len(df)} velas obtenidas para {simbolo} ({intervalo})")
    return df


# ============================================================
# 4. CALCULAR INDICADORES TÉCNICOS
# ============================================================
def calcular_indicadores(df):
    """
    Añade columnas de indicadores técnicos al DataFrame.

    RSI (Relative Strength Index):
        - Mide la velocidad y magnitud de los movimientos de precio
        - Rango: 0 a 100
        - < 30 = sobrevendido (precio muy bajo, posible rebote ↑)
        - > 70 = sobrecomprado (precio muy alto, posible caída ↓)
    """
    # RSI
    delta = df["close"].diff()
    ganancia = delta.clip(lower=0).rolling(config.RSI_PERIODO).mean()
    perdida  = (-delta.clip(upper=0)).rolling(config.RSI_PERIODO).mean()
    rs = ganancia / perdida
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD (Media Móvil de Convergencia/Divergencia)
    # Detecta cambios de tendencia comparando dos medias exponenciales
    ema_rapida      = df["close"].ewm(span=12, adjust=False).mean()
    ema_lenta       = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"]      = ema_rapida - ema_lenta
    df["MACD_senal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    log.info("📐 Indicadores calculados correctamente")
    return df


# ============================================================
# 5. EVALUAR LA SEÑAL
# ============================================================
def evaluar_senal(df, simbolo):
    """
    Analiza los indicadores y decide qué señal emitir.

    Retorna un diccionario con:
        - tipo    : "COMPRA", "VENTA" o "NEUTRAL"
        - precio  : precio actual
        - rsi     : valor RSI actual
        - mensaje : texto para enviar a Telegram
    """
    ultima_vela = df.iloc[-1]       # La vela más reciente
    precio_actual = ultima_vela["close"]
    rsi_actual    = round(ultima_vela["RSI"], 2)
    macd_actual   = round(ultima_vela["MACD"], 4)
    macd_senal    = round(ultima_vela["MACD_senal"], 4)
    hora_actual   = datetime.now().strftime("%Y-%m-%d %H:%M")

    tendencia_macd = "alcista ↑" if macd_actual > macd_senal else "bajista ↓"

    # --- Lógica de decisión ---
    if rsi_actual < config.RSI_SOBREVENDIDO:
        tipo = "COMPRA"
        emoji = "🟢"
        razon = f"RSI en {rsi_actual} — sobrevendido, posible rebote al alza"

    elif rsi_actual > config.RSI_SOBRECOMPRADO:
        tipo = "VENTA"
        emoji = "🔴"
        razon = f"RSI en {rsi_actual} — sobrecomprado, posible corrección"

    else:
        tipo = "NEUTRAL"
        emoji = "⚪"
        razon = f"RSI en {rsi_actual} — mercado en zona neutral"

    # --- Construir el mensaje ---
    mensaje = (
        f"{emoji} *ALERTA DE TRADING*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 Par: `{simbolo}`\n"
        f"💰 Precio: `${precio_actual:,.2f}`\n"
        f"📊 RSI ({config.RSI_PERIODO}): `{rsi_actual}`\n"
        f"📈 MACD: `{macd_actual}` — {tendencia_macd}\n"
        f"🎯 Señal: *{tipo}*\n"
        f"📝 Razón: {razon}\n"
        f"🕐 Hora: {hora_actual}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ _Esto es educativo, no consejo financiero_"
    )

    return {
        "tipo": tipo,
        "precio": precio_actual,
        "rsi": rsi_actual,
        "simbolo": simbolo,
        "mensaje": mensaje
    }


# ============================================================
# 6. ENVIAR ALERTA A TELEGRAM
# ============================================================
def enviar_telegram(mensaje):
    """
    Envía el mensaje de alerta al chat de Telegram configurado.

    Usa la API HTTP de Telegram (no necesita librería especial).
    """
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"    # Permite texto en negrita, código, etc.
    }

    respuesta = requests.post(url, json=payload)

    if respuesta.status_code == 200:
        log.info("📱 Alerta enviada a Telegram ✅")
    else:
        log.error(f"❌ Error enviando a Telegram: {respuesta.text}")


# ============================================================
# 7. GUARDAR EN REGISTRO LOCAL
# ============================================================
def guardar_registro(senal):
    """
    Guarda cada señal en un archivo CSV para analizar después
    qué tan buenas fueron las predicciones del bot.

    Esto es clave para "entrenar" y mejorar la estrategia.
    """
    registro = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "simbolo": senal["simbolo"],
        "precio": senal["precio"],
        "rsi": senal["rsi"],
        "senal": senal["tipo"]
    }

    df_registro = pd.DataFrame([registro])

    # Añade al archivo si ya existe, crea uno nuevo si no
    df_registro.to_csv(
        "historial_senales.csv",
        mode="a",
        header=not pd.io.common.file_exists("historial_senales.csv"),
        index=False
    )
    log.info(f"💾 Señal guardada en historial_senales.csv")


# ============================================================
# 8. CICLO PRINCIPAL — El corazón del bot
# ============================================================
def ejecutar_ciclo():
    """
    Esta función se ejecuta cada X minutos automáticamente.
    Orquesta todos los pasos anteriores en orden.
    """
    log.info("=" * 50)
    log.info("🤖 Iniciando ciclo de análisis...")

    exchange = conectar_exchange()

    # --- Criptomonedas ---
    for simbolo in config.SIMBOLOS:
        try:
            df    = obtener_velas(exchange, simbolo, config.INTERVALO)
            df    = calcular_indicadores(df)
            senal = evaluar_senal(df, simbolo)
            log.info(f"🎯 {simbolo} | Señal: {senal['tipo']} | Precio: ${senal['precio']:,.2f} | RSI: {senal['rsi']}")
            if senal["tipo"] != "NEUTRAL":
                if config.MODO_PAPER_TRADING:
                    log.info("📄 MODO PAPER: solo alertas, sin órdenes reales")
                enviar_telegram(senal["mensaje"])
            guardar_registro(senal)
        except Exception as error:
            log.error(f"💥 Error analizando {simbolo}: {error}")

    # --- Acciones (NVDA, AAPL, etc.) ---
    for simbolo in config.STOCKS:
        try:
            df    = obtener_velas_stock(simbolo, config.INTERVALO)
            df    = calcular_indicadores(df)
            senal = evaluar_senal(df, simbolo)
            log.info(f"🎯 {simbolo} | Señal: {senal['tipo']} | Precio: ${senal['precio']:,.2f} | RSI: {senal['rsi']}")
            if senal["tipo"] != "NEUTRAL":
                if config.MODO_PAPER_TRADING:
                    log.info("📄 MODO PAPER: solo alertas, sin órdenes reales")
                enviar_telegram(senal["mensaje"])
            guardar_registro(senal)
        except Exception as error:
            log.error(f"💥 Error analizando {simbolo}: {error}")


# ============================================================
# 9. ARRANCAR EL BOT
# ============================================================
if __name__ == "__main__":
    log.info("🚀 Bot de alertas de trading iniciado")
    log.info(f"   Criptos: {', '.join(config.SIMBOLOS)}")
    log.info(f"   Acciones: {', '.join(config.STOCKS)}")
    log.info(f"   Intervalo de velas: {config.INTERVALO}")
    log.info(f"   Revisión cada: {config.FRECUENCIA_MINUTOS} minutos")
    log.info(f"   Modo Paper Trading: {config.MODO_PAPER_TRADING}")
    log.info("=" * 50)

    # Ejecuta una vez inmediatamente al arrancar
    ejecutar_ciclo()

    # Luego programa ejecuciones automáticas cada X minutos
    scheduler = BlockingScheduler()
    scheduler.add_job(
        ejecutar_ciclo,
        "interval",
        minutes=config.FRECUENCIA_MINUTOS
    )
    scheduler.start()