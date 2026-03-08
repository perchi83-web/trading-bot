# ============================================================
# bot.py — Agente de trading v3 — Trend Following + RSI
# ============================================================
#
# ESTRATEGIA:
#   1. Detecta tendencia con MA50 vs MA200
#   2. Solo opera en tendencia ALCISTA
#   3. Usa RSI + MACD para timing de entrada
#   4. Gestión de riesgo estricta por operación
#
# FLUJO:
#   Cada hora:
#     ¿Tendencia alcista? → busca entrada RSI + MACD
#     ¿Tendencia bajista? → protege capital, no opera
#     Si hay señal → alerta Telegram con gestión de riesgo
#     Siempre → guarda en CSV
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
def obtener_velas(exchange, simbolo, intervalo, limite=250):
    """
    Descargamos 250 velas para tener suficientes datos
    para calcular MA200 correctamente.
    """
    datos_crudos = exchange.fetch_ohlcv(simbolo, intervalo, limit=limite)
    df = pd.DataFrame(datos_crudos, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    log.info(f"{limite} velas obtenidas para {simbolo} ({intervalo})")
    return df


# ============================================================
# 3b. OBTENER DATOS — ACCIONES
# ============================================================
def obtener_velas_stock(simbolo, intervalo="1h"):
    ticker = yf.Ticker(simbolo)
    df = ticker.history(period="60d", interval=intervalo).reset_index()
    col_time = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={
        col_time: "timestamp",
        "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume"
    })
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    log.info(f"{len(df)} velas obtenidas para {simbolo}")
    return df


# ============================================================
# 4. CALCULAR INDICADORES
# ============================================================
def calcular_indicadores(df):
    # RSI
    delta    = df["close"].diff()
    ganancia = delta.clip(lower=0).rolling(config.RSI_PERIODO).mean()
    perdida  = (-delta.clip(upper=0)).rolling(config.RSI_PERIODO).mean()
    rs       = ganancia / perdida
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema12          = df["close"].ewm(span=12, adjust=False).mean()
    ema26          = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"]     = ema12 - ema26
    df["MACD_sig"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # Medias móviles
    df["MA20"]  = df["close"].rolling(20).mean()
    df["MA50"]  = df["close"].rolling(50).mean()
    df["MA200"] = df["close"].rolling(200).mean()

    log.info("Indicadores calculados: RSI + MACD + MA20 + MA50 + MA200")
    return df.dropna().reset_index(drop=True)


# ============================================================
# 5. DETECTAR TENDENCIA
# ============================================================
def detectar_tendencia(df):
    """
    Golden Cross: MA50 > MA200 → tendencia ALCISTA → operar
    Death Cross:  MA50 < MA200 → tendencia BAJISTA → no operar
    """
    ultima = df.iloc[-1]
    if ultima["MA50"] > ultima["MA200"]:
        return "ALCISTA"
    else:
        return "BAJISTA"


# ============================================================
# 6. CALCULAR GESTIÓN DE RIESGO
# ============================================================
def calcular_riesgo(precio_entrada):
    """
    Ratio 1:3 — por cada $1 arriesgado, buscamos ganar $3
    Stop-Loss:   2% → pérdida máxima controlada
    Take-Profit: 6% → ganancia objetivo
    """
    capital_op      = config.CAPITAL_TOTAL * config.RIESGO_POR_OPERACION
    stop_loss       = precio_entrada * (1 - config.STOP_LOSS_PORCENTAJE)
    take_profit     = precio_entrada * (1 + config.TAKE_PROFIT_PORCENTAJE)
    perdida_max     = capital_op * config.STOP_LOSS_PORCENTAJE
    ganancia_esp    = capital_op * config.TAKE_PROFIT_PORCENTAJE

    return {
        "capital_a_usar":    round(capital_op, 2),
        "stop_loss":         round(stop_loss, 2),
        "take_profit":       round(take_profit, 2),
        "perdida_maxima":    round(perdida_max, 2),
        "ganancia_esperada": round(ganancia_esp, 2),
        "ratio":             f"1:{int(config.TAKE_PROFIT_PORCENTAJE / config.STOP_LOSS_PORCENTAJE)}"
    }


# ============================================================
# 7. EVALUAR SEÑAL
# ============================================================
def evaluar_senal(df, simbolo):
    ultima   = df.iloc[-1]
    anterior = df.iloc[-2]

    precio    = ultima["close"]
    rsi       = round(ultima["RSI"], 2)
    ma50      = round(ultima["MA50"], 2)
    ma200     = round(ultima["MA200"], 2)
    hora      = datetime.now().strftime("%Y-%m-%d %H:%M")

    tendencia = detectar_tendencia(df)

    macd_alcista = (ultima["MACD"] > ultima["MACD_sig"] and
                    anterior["MACD"] <= anterior["MACD_sig"])

    macd_bajista = (ultima["MACD"] < ultima["MACD_sig"] and
                    anterior["MACD"] >= anterior["MACD_sig"])

    # -------------------------------------------------------
    # LÓGICA PRINCIPAL — Trend Following + RSI
    # -------------------------------------------------------
    if tendencia == "ALCISTA":

        if rsi < config.RSI_SOBREVENDIDO and macd_alcista:
            tipo      = "COMPRA"
            confianza = "ALTA"
            razon     = f"Tendencia ALCISTA + RSI sobrevendido ({rsi}) + cruce MACD alcista"

        elif rsi < config.RSI_SOBREVENDIDO:
            tipo      = "COMPRA"
            confianza = "MEDIA"
            razon     = f"Tendencia ALCISTA + RSI sobrevendido ({rsi})"

        elif rsi > config.RSI_SOBRECOMPRADO and macd_bajista:
            tipo      = "VENTA"
            confianza = "ALTA"
            razon     = f"Tendencia ALCISTA + RSI sobrecomprado ({rsi}) + cruce MACD bajista"

        else:
            tipo      = "NEUTRAL"
            confianza = "-"
            razon     = f"Tendencia ALCISTA pero RSI neutral ({rsi})"

    else:
        # Tendencia BAJISTA — proteger capital
        tipo      = "ESPERAR"
        confianza = "-"
        razon     = f"Tendencia BAJISTA (MA50 ${ma50} < MA200 ${ma200}) — capital protegido"

    # Calcular riesgo solo si hay señal accionable
    riesgo = calcular_riesgo(precio) if tipo in ["COMPRA", "VENTA"] else None

    # Construir mensaje Telegram
    if tipo in ["COMPRA", "VENTA"] and riesgo:
        estado_tendencia = "ALCISTA" if tendencia == "ALCISTA" else "BAJISTA"
        mensaje = (
            f"[{tipo}] ALERTA DE TRADING\n"
            f"{'='*32}\n"
            f"Activo:       {simbolo}\n"
            f"Precio:       ${precio:,.2f}\n"
            f"Tendencia:    {estado_tendencia}\n"
            f"Señal:        {tipo}\n"
            f"Confianza:    {confianza}\n"
            f"Razon:        {razon}\n"
            f"{'='*32}\n"
            f"GESTION DE RIESGO\n"
            f"Capital:      ${riesgo['capital_a_usar']}\n"
            f"Stop-Loss:    ${riesgo['stop_loss']:,.2f}\n"
            f"Take-Profit:  ${riesgo['take_profit']:,.2f}\n"
            f"Max perdida:  ${riesgo['perdida_maxima']}\n"
            f"Ganancia esp: ${riesgo['ganancia_esperada']}\n"
            f"Ratio:        {riesgo['ratio']}\n"
            f"{'='*32}\n"
            f"RSI:   {rsi}\n"
            f"MA50:  ${ma50:,.2f}\n"
            f"MA200: ${ma200:,.2f}\n"
            f"Hora:  {hora}\n"
            f"{'='*32}\n"
            f"PAPER TRADING - Solo educativo"
        )
    elif tipo == "ESPERAR":
        mensaje = (
            f"[ESPERAR] {simbolo}\n"
            f"Tendencia BAJISTA detectada\n"
            f"MA50 ${ma50:,.2f} < MA200 ${ma200:,.2f}\n"
            f"Capital protegido. Sin operaciones.\n"
            f"Hora: {hora}"
        )
    else:
        mensaje = None

    return {
        "tipo":      tipo,
        "precio":    precio,
        "rsi":       rsi,
        "tendencia": tendencia,
        "confianza": confianza,
        "simbolo":   simbolo,
        "mensaje":   mensaje,
        "riesgo":    riesgo
    }


# ============================================================
# 8. ENVIAR ALERTA A TELEGRAM
# ============================================================
def enviar_telegram(mensaje):
    url     = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": mensaje}
    resp    = requests.post(url, json=payload)
    if resp.status_code == 200:
        log.info("Alerta enviada a Telegram correctamente")
    else:
        log.error(f"Error enviando a Telegram: {resp.text}")


# ============================================================
# 9. GUARDAR REGISTRO
# ============================================================
def guardar_registro(senal):
    registro = {
        "fecha":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "simbolo":   senal["simbolo"],
        "precio":    senal["precio"],
        "rsi":       senal["rsi"],
        "tendencia": senal["tendencia"],
        "senal":     senal["tipo"],
        "confianza": senal["confianza"],
        "capital_usado":  senal["riesgo"]["capital_a_usar"] if senal["riesgo"] else 0,
        "stop_loss":      senal["riesgo"]["stop_loss"]      if senal["riesgo"] else 0,
        "take_profit":    senal["riesgo"]["take_profit"]    if senal["riesgo"] else 0,
    }
    df_r = pd.DataFrame([registro])
    df_r.to_csv(
        "historial_senales.csv",
        mode="a",
        header=not pd.io.common.file_exists("historial_senales.csv"),
        index=False
    )
    log.info("Señal guardada en historial_senales.csv")


# ============================================================
# 10. CICLO PRINCIPAL
# ============================================================
def ejecutar_ciclo():
    log.info("=" * 50)
    log.info("Iniciando ciclo de analisis...")

    exchange = conectar_exchange()

    for simbolo in config.SIMBOLOS:
        try:
            df    = obtener_velas(exchange, simbolo, config.INTERVALO)
            df    = calcular_indicadores(df)
            senal = evaluar_senal(df, simbolo)
            log.info(
                f"{simbolo} | {senal['tipo']} | "
                f"${senal['precio']:,.2f} | "
                f"RSI: {senal['rsi']} | "
                f"Tendencia: {senal['tendencia']}"
            )
            if senal["mensaje"]:
                # Solo envía a Telegram si hay señal accionable
                # ESPERAR solo se notifica una vez al día para no spamear
                if senal["tipo"] in ["COMPRA", "VENTA"]:
                    enviar_telegram(senal["mensaje"])
            guardar_registro(senal)
        except Exception as error:
            log.error(f"Error analizando {simbolo}: {error}")

    for simbolo in config.STOCKS:
        try:
            df    = obtener_velas_stock(simbolo, config.INTERVALO)
            df    = calcular_indicadores(df)
            senal = evaluar_senal(df, simbolo)
            log.info(
                f"{simbolo} | {senal['tipo']} | "
                f"${senal['precio']:,.2f} | "
                f"RSI: {senal['rsi']} | "
                f"Tendencia: {senal['tendencia']}"
            )
            if senal["tipo"] in ["COMPRA", "VENTA"] and senal["mensaje"]:
                enviar_telegram(senal["mensaje"])
            guardar_registro(senal)
        except Exception as error:
            log.error(f"Error analizando {simbolo}: {error}")

    log.info("Ciclo completado. Proxima revision en 1 hora.")


# ============================================================
# 11. ARRANCAR EL BOT
# ============================================================
if __name__ == "__main__":
    log.info("Bot de trading v3 iniciado — Trend Following + RSI")
    log.info(f"Criptos:    {', '.join(config.SIMBOLOS)}")
    log.info(f"Acciones:   {', '.join(config.STOCKS)}")
    log.info(f"Intervalo:  {config.INTERVALO}")
    log.info(f"Capital:    ${config.CAPITAL_TOTAL}")
    log.info(f"Riesgo/op:  {config.RIESGO_POR_OPERACION*100}%")
    log.info(f"Stop-Loss:  {config.STOP_LOSS_PORCENTAJE*100}%")
    log.info(f"Take-Profit:{config.TAKE_PROFIT_PORCENTAJE*100}%")
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