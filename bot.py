# ============================================================
# bot.py — Agente de alertas con gestión de riesgo
# ============================================================
#
# FLUJO COMPLETO:
#
#   1. Cada hora se activa el bot
#   2. Descarga las últimas velas del mercado
#   3. Calcula RSI + MACD
#   4. Evalúa la señal con gestión de riesgo
#   5. Calcula exactamente cuánto arriesgar
#   6. Si hay señal → envía alerta detallada a Telegram
#   7. Registra todo en CSV para análisis posterior
#
# ============================================================

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import ccxt
import pandas as pd
import yfinance as yf
import requests
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

import config


# ============================================================
# 1. CONFIGURAR REGISTRO
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("registro_bot.log", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)


# ============================================================
# 2. CONECTAR CON EXCHANGE
# ============================================================
def conectar_exchange():
    exchange = ccxt.binance({
        "apiKey": config.BINANCE_API_KEY,
        "secret": config.BINANCE_SECRET,
    })
    log.info("Conectado al exchange correctamente")
    return exchange


# ============================================================
# 3. OBTENER DATOS — CRIPTOS
# ============================================================
def obtener_velas(exchange, simbolo, intervalo, limite=100):
    datos_crudos = exchange.fetch_ohlcv(simbolo, intervalo, limit=limite)
    df = pd.DataFrame(datos_crudos, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    log.info(f"{limite} velas obtenidas para {simbolo} ({intervalo})")
    return df


# ============================================================
# 3b. OBTENER DATOS — ACCIONES
# ============================================================
def obtener_velas_stock(simbolo, intervalo="1h", limite=100):
    ticker = yf.Ticker(simbolo)
    df = ticker.history(period="5d", interval=intervalo)
    df = df.tail(limite).reset_index()

    col_time = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={
        col_time: "timestamp",
        "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume"
    })
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    log.info(f"{len(df)} velas obtenidas para {simbolo} ({intervalo})")
    return df


# ============================================================
# 4. CALCULAR INDICADORES TÉCNICOS
# ============================================================
def calcular_indicadores(df):
    # RSI
    delta   = df["close"].diff()
    ganancia = delta.clip(lower=0).rolling(config.RSI_PERIODO).mean()
    perdida  = (-delta.clip(upper=0)).rolling(config.RSI_PERIODO).mean()
    rs       = ganancia / perdida
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema_rapida       = df["close"].ewm(span=12, adjust=False).mean()
    ema_lenta        = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"]       = ema_rapida - ema_lenta
    df["MACD_senal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # Media móvil 20 periodos (tendencia general)
    df["MA20"] = df["close"].rolling(20).mean()

    log.info("Indicadores calculados: RSI + MACD + MA20")
    return df


# ============================================================
# 5. GESTIÓN DE RIESGO
# ============================================================
def calcular_riesgo(precio_entrada, tipo_senal):
    """
    Calcula cuánto capital arriesgar y los niveles de
    stop-loss y take-profit para cada operación.

    Regla de oro: nunca arriesgues más del 10% del capital
    por operación. Si pierdes, pierdes poco. Si ganas, ganas doble.
    """
    capital_por_operacion = config.CAPITAL_TOTAL * config.RIESGO_POR_OPERACION

    if tipo_senal == "COMPRA":
        stop_loss   = precio_entrada * (1 - config.STOP_LOSS_PORCENTAJE)
        take_profit = precio_entrada * (1 + config.TAKE_PROFIT_PORCENTAJE)
    elif tipo_senal == "VENTA":
        stop_loss   = precio_entrada * (1 + config.STOP_LOSS_PORCENTAJE)
        take_profit = precio_entrada * (1 - config.TAKE_PROFIT_PORCENTAJE)
    else:
        return None

    perdida_maxima = capital_por_operacion * config.STOP_LOSS_PORCENTAJE
    ganancia_esperada = capital_por_operacion * config.TAKE_PROFIT_PORCENTAJE

    return {
        "capital_a_usar":    round(capital_por_operacion, 2),
        "stop_loss":         round(stop_loss, 4),
        "take_profit":       round(take_profit, 4),
        "perdida_maxima":    round(perdida_maxima, 2),
        "ganancia_esperada": round(ganancia_esperada, 2),
        "ratio":             f"1:{config.TAKE_PROFIT_PORCENTAJE / config.STOP_LOSS_PORCENTAJE:.0f}"
    }


# ============================================================
# 6. EVALUAR LA SEÑAL
# ============================================================
def evaluar_senal(df, simbolo):
    ultima    = df.iloc[-1]
    anterior  = df.iloc[-2]

    precio    = ultima["close"]
    rsi       = round(ultima["RSI"], 2)
    macd      = round(ultima["MACD"], 4)
    macd_sig  = round(ultima["MACD_senal"], 4)
    ma20      = round(ultima["MA20"], 4)
    hora      = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Tendencia del MACD
    macd_cruce_alcista = (ultima["MACD"] > ultima["MACD_senal"] and
                          anterior["MACD"] <= anterior["MACD_senal"])
    macd_cruce_bajista = (ultima["MACD"] < ultima["MACD_senal"] and
                          anterior["MACD"] >= anterior["MACD_senal"])

    # Precio respecto a MA20
    sobre_ma20 = precio > ma20
    bajo_ma20  = precio < ma20

    # -------------------------------------------------------
    # LÓGICA DE SEÑAL MEJORADA
    # Ahora necesita confirmación de 2 indicadores
    # -------------------------------------------------------
    if rsi < config.RSI_SOBREVENDIDO and (macd_cruce_alcista or bajo_ma20):
        tipo       = "COMPRA"
        emoji      = "COMPRA"
        confianza  = "ALTA" if macd_cruce_alcista else "MEDIA"
        razon      = f"RSI sobrevendido ({rsi}) + {'cruce MACD alcista' if macd_cruce_alcista else 'precio bajo MA20'}"

    elif rsi > config.RSI_SOBRECOMPRADO and (macd_cruce_bajista or sobre_ma20):
        tipo       = "VENTA"
        emoji      = "VENTA"
        confianza  = "ALTA" if macd_cruce_bajista else "MEDIA"
        razon      = f"RSI sobrecomprado ({rsi}) + {'cruce MACD bajista' if macd_cruce_bajista else 'precio sobre MA20'}"

    else:
        tipo      = "NEUTRAL"
        emoji     = "NEUTRAL"
        confianza = "—"
        razon     = f"RSI en zona neutral ({rsi}), sin confirmacion de señal"

    # Calcular gestión de riesgo
    riesgo = calcular_riesgo(precio, tipo)

    # Construir mensaje para Telegram
    if tipo != "NEUTRAL" and riesgo:
        mensaje = (
            f"[{emoji}] ALERTA DE TRADING\n"
            f"{'='*30}\n"
            f"Activo:      {simbolo}\n"
            f"Precio:      ${precio:,.4f}\n"
            f"Señal:       {tipo}\n"
            f"Confianza:   {confianza}\n"
            f"Razon:       {razon}\n"
            f"{'='*30}\n"
            f"GESTION DE RIESGO\n"
            f"Capital a usar:   ${riesgo['capital_a_usar']}\n"
            f"Stop-Loss:        ${riesgo['stop_loss']:,.4f}\n"
            f"Take-Profit:      ${riesgo['take_profit']:,.4f}\n"
            f"Max. perdida:     ${riesgo['perdida_maxima']}\n"
            f"Ganancia esperada:${riesgo['ganancia_esperada']}\n"
            f"Ratio:            {riesgo['ratio']}\n"
            f"{'='*30}\n"
            f"RSI:    {rsi}\n"
            f"MACD:   {macd}\n"
            f"MA20:   {ma20}\n"
            f"Hora:   {hora}\n"
            f"{'='*30}\n"
            f"MODO PAPER TRADING - Solo educativo"
        )
    else:
        mensaje = None

    return {
        "tipo":      tipo,
        "precio":    precio,
        "rsi":       rsi,
        "confianza": confianza,
        "simbolo":   simbolo,
        "mensaje":   mensaje,
        "riesgo":    riesgo
    }


# ============================================================
# 7. ENVIAR ALERTA A TELEGRAM
# ============================================================
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text":    mensaje,
    }
    respuesta = requests.post(url, json=payload)
    if respuesta.status_code == 200:
        log.info("Alerta enviada a Telegram correctamente")
    else:
        log.error(f"Error enviando a Telegram: {respuesta.text}")


# ============================================================
# 8. GUARDAR REGISTRO
# ============================================================
def guardar_registro(senal):
    registro = {
        "fecha":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "simbolo":   senal["simbolo"],
        "precio":    senal["precio"],
        "rsi":       senal["rsi"],
        "senal":     senal["tipo"],
        "confianza": senal["confianza"],
        "capital_usado":   senal["riesgo"]["capital_a_usar"] if senal["riesgo"] else 0,
        "stop_loss":       senal["riesgo"]["stop_loss"]      if senal["riesgo"] else 0,
        "take_profit":     senal["riesgo"]["take_profit"]    if senal["riesgo"] else 0,
    }
    df_registro = pd.DataFrame([registro])
    df_registro.to_csv(
        "historial_senales.csv",
        mode="a",
        header=not pd.io.common.file_exists("historial_senales.csv"),
        index=False
    )
    log.info("Señal guardada en historial_senales.csv")


# ============================================================
# 9. CICLO PRINCIPAL
# ============================================================
def ejecutar_ciclo():
    log.info("=" * 50)
    log.info("Iniciando ciclo de analisis...")

    exchange = conectar_exchange()

    # Criptos
    for simbolo in config.SIMBOLOS:
        try:
            df    = obtener_velas(exchange, simbolo, config.INTERVALO)
            df    = calcular_indicadores(df)
            senal = evaluar_senal(df, simbolo)
            log.info(f"{simbolo} | {senal['tipo']} | ${senal['precio']:,.4f} | RSI: {senal['rsi']} | Confianza: {senal['confianza']}")

            if senal["tipo"] != "NEUTRAL" and senal["mensaje"]:
                enviar_telegram(senal["mensaje"])
            guardar_registro(senal)

        except Exception as error:
            log.error(f"Error analizando {simbolo}: {error}")

    # Acciones
    for simbolo in config.STOCKS:
        try:
            df    = obtener_velas_stock(simbolo, config.INTERVALO)
            df    = calcular_indicadores(df)
            senal = evaluar_senal(df, simbolo)
            log.info(f"{simbolo} | {senal['tipo']} | ${senal['precio']:,.4f} | RSI: {senal['rsi']} | Confianza: {senal['confianza']}")

            if senal["tipo"] != "NEUTRAL" and senal["mensaje"]:
                enviar_telegram(senal["mensaje"])
            guardar_registro(senal)

        except Exception as error:
            log.error(f"Error analizando {simbolo}: {error}")

    log.info("Ciclo completado. Proxima revision en 1 hora.")


# ============================================================
# 10. ARRANCAR EL BOT
# ============================================================
if __name__ == "__main__":
    log.info("Bot de alertas de trading iniciado")
    log.info(f"Criptos:    {', '.join(config.SIMBOLOS)}")
    log.info(f"Acciones:   {', '.join(config.STOCKS)}")
    log.info(f"Intervalo:  {config.INTERVALO}")
    log.info(f"Capital:    ${config.CAPITAL_TOTAL}")
    log.info(f"Riesgo/op:  {config.RIESGO_POR_OPERACION*100}%")
    log.info(f"Paper Mode: {config.MODO_PAPER_TRADING}")
    log.info("=" * 50)

    ejecutar_ciclo()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        ejecutar_ciclo,
        "interval",
        minutes=config.FRECUENCIA_MINUTOS
    )
    scheduler.start()