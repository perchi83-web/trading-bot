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
import ta
import yfinance as yf
import requests
import logging
import threading
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler

import config
import agente
import paper_trading

# Registro de última alerta enviada por activo (anti-spam 4 horas)
_ultima_alerta = {}  # { "BTC/USDT": datetime, ... }

# Señales pendientes de confirmación del usuario
_senales_pendientes = {}  # { "callback_data": senal_dict }


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
def conectar_exchange(reintentos=3, espera=5):
    for intento in range(1, reintentos + 1):
        try:
            exchange = ccxt.binance({
                "apiKey": config.BINANCE_API_KEY,
                "secret": config.BINANCE_SECRET,
            })
            log.info("Conectado al exchange correctamente")
            return exchange
        except Exception as e:
            log.warning(f"Intento {intento}/{reintentos} fallido al conectar exchange: {e}")
            if intento < reintentos:
                time.sleep(espera)
    raise ConnectionError("No se pudo conectar al exchange tras 3 intentos")


# ============================================================
# 3. OBTENER DATOS — CRIPTOS
# ============================================================
def obtener_velas(exchange, simbolo, intervalo, limite=250, reintentos=3, espera=5):
    """
    Descargamos 250 velas para tener suficientes datos
    para calcular MA200 correctamente.
    Incluye reintentos ante micro-cortes de conexión.
    """
    for intento in range(1, reintentos + 1):
        try:
            datos_crudos = exchange.fetch_ohlcv(simbolo, intervalo, limit=limite)
            df = pd.DataFrame(datos_crudos, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            log.info(f"{limite} velas obtenidas para {simbolo} ({intervalo})")
            return df
        except Exception as e:
            log.warning(f"Intento {intento}/{reintentos} fallido al obtener velas de {simbolo}: {e}")
            if intento < reintentos:
                time.sleep(espera)
    raise ConnectionError(f"No se pudieron obtener velas de {simbolo} tras {reintentos} intentos")


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

    # Bandas de Bollinger (20 periodos, 2 desviaciones)
    bb             = ta.volatility.BollingerBands(close=df["close"], window=20, window_dev=2)
    df["BB_lower"] = bb.bollinger_lband()
    df["BB_mid"]   = bb.bollinger_mavg()
    df["BB_upper"] = bb.bollinger_hband()

    # OBV — On-Balance Volume (valida si el volumen respalda el precio)
    df["OBV"] = ta.volume.OnBalanceVolumeIndicator(
        close=df["close"], volume=df["volume"]
    ).on_balance_volume()

    # ATR — Average True Range 14 periodos (mide volatilidad)
    df["ATR"] = ta.volatility.AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()

    log.info("Indicadores calculados: RSI + MACD + MA20/50/200 + BB + OBV + ATR")
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
def calcular_riesgo(precio_entrada, atr):
    """
    Gestión de riesgo dinámica basada en ATR — Ratio 1:3
    Stop-Loss:   Precio - (ATR * 1.8) → se adapta a la volatilidad actual
    Take-Profit: Precio + (distancia_stop * 3) → ratio 1:3 garantizado
    """
    capital_op     = config.CAPITAL_TOTAL * config.RIESGO_POR_OPERACION
    distancia_stop = atr * 1.8
    stop_loss      = precio_entrada - distancia_stop
    take_profit    = precio_entrada + (distancia_stop * 3)
    pct_stop       = distancia_stop / precio_entrada
    perdida_max    = round(capital_op * pct_stop, 2)
    ganancia_esp   = round(capital_op * pct_stop * 3, 2)

    return {
        "capital_a_usar":    round(capital_op, 2),
        "stop_loss":         round(stop_loss, 2),
        "take_profit":       round(take_profit, 2),
        "perdida_maxima":    perdida_max,
        "ganancia_esperada": ganancia_esp,
        "ratio":             "1:3"
    }


# ============================================================
# 7. EVALUAR SEÑAL
# ============================================================
def evaluar_senal(df_1h, df_4h, simbolo):
    ultima   = df_1h.iloc[-1]
    anterior = df_1h.iloc[-2]

    precio    = ultima["close"]
    rsi       = round(ultima["RSI"], 2)
    ma50      = round(ultima["MA50"], 2)
    ma200     = round(ultima["MA200"], 2)
    atr       = round(ultima["ATR"], 4)
    bb_lower  = round(ultima["BB_lower"], 2)
    bb_upper  = round(ultima["BB_upper"], 2)
    obv_sube  = ultima["OBV"] > anterior["OBV"]
    hora      = datetime.now().strftime("%Y-%m-%d %H:%M")

    tendencia_1h = detectar_tendencia(df_1h)

    # Filtro MTF: solo aplicar si df_4h tiene datos suficientes
    if len(df_4h) >= 50:
        tendencia_4h = detectar_tendencia(df_4h)
    else:
        tendencia_4h = tendencia_1h   # fallback: asumir igual que 1h → filtro MTF inactivo
        log.warning(f"{simbolo}: df_4h con {len(df_4h)} filas — filtro MTF ignorado, usando solo tendencia 1h")

    macd_alcista = (ultima["MACD"] > ultima["MACD_sig"] and
                    anterior["MACD"] <= anterior["MACD_sig"])

    macd_bajista = (ultima["MACD"] < ultima["MACD_sig"] and
                    anterior["MACD"] >= anterior["MACD_sig"])

    # Filtros de Bollinger — el precio debe estar cerca del extremo de la banda
    bb_cerca_inferior = precio <= bb_lower * 1.01
    bb_cerca_superior = precio >= bb_upper * 0.99

    # -------------------------------------------------------
    # LÓGICA PRINCIPAL — Trend Following + RSI + Bollinger (1h)
    # -------------------------------------------------------
    if tendencia_1h == "ALCISTA":

        if rsi < config.RSI_SOBREVENDIDO and macd_alcista and bb_cerca_inferior:
            tipo      = "COMPRA"
            confianza = "ALTA"
            razon     = f"1h ALCISTA + RSI {rsi} + cruce MACD alcista + precio en BB inferior"

        elif rsi < config.RSI_SOBREVENDIDO and bb_cerca_inferior:
            tipo      = "COMPRA"
            confianza = "MEDIA"
            razon     = f"1h ALCISTA + RSI {rsi} + precio en BB inferior"

        elif rsi > config.RSI_SOBRECOMPRADO and macd_bajista and bb_cerca_superior:
            tipo      = "VENTA"
            confianza = "ALTA"
            razon     = f"1h ALCISTA + RSI {rsi} + cruce MACD bajista + precio en BB superior"

        else:
            tipo      = "NEUTRAL"
            confianza = "-"
            razon     = f"1h ALCISTA pero sin confluencia BB+RSI ({rsi})"

    else:
        if rsi < 20 and bb_cerca_inferior:
            tipo      = "COMPRA"
            confianza = "BAJA"
            razon     = f"RSI extremo ({rsi}) + precio en BB inferior pese a 1h BAJISTA"
        else:
            tipo      = "ESPERAR"
            confianza = "-"
            razon     = f"1h BAJISTA (MA50 ${ma50} < MA200 ${ma200}) — capital protegido"

    # -------------------------------------------------------
    # FILTRO MAESTRO Multi-Timeframe (MTF)
    # Si 4h es BAJISTA nunca comprar, aunque 1h parezca alcista
    # -------------------------------------------------------
    if tipo == "COMPRA" and tendencia_4h == "BAJISTA":
        tipo      = "ESPERAR"
        confianza = "-"
        razon     = f"FILTRO MTF: 4h BAJISTA anula señal de COMPRA en 1h"

    # Calcular riesgo con ATR dinámico
    riesgo = calcular_riesgo(precio, atr) if tipo in ["COMPRA", "VENTA"] else None

    # Construir mensaje Telegram
    if tipo in ["COMPRA", "VENTA"] and riesgo:
        obv_texto = "OBV subiendo (volumen confirma)" if obv_sube else "OBV bajando"
        mensaje = (
            f"[{tipo}] ALERTA DE TRADING\n"
            f"{'='*32}\n"
            f"Activo:         {simbolo}\n"
            f"Precio:         ${precio:,.2f}\n"
            f"Tendencia 1h:   {tendencia_1h}\n"
            f"Confirmacion 4h:{tendencia_4h}\n"
            f"Señal:          {tipo}\n"
            f"Confianza:      {confianza}\n"
            f"Razon:          {razon}\n"
            f"{'='*32}\n"
            f"GESTION DE RIESGO (ATR dinamico)\n"
            f"Capital:      ${riesgo['capital_a_usar']}\n"
            f"Stop-Loss:    ${riesgo['stop_loss']:,.2f}\n"
            f"Take-Profit:  ${riesgo['take_profit']:,.2f}\n"
            f"Max perdida:  ${riesgo['perdida_maxima']}\n"
            f"Ganancia esp: ${riesgo['ganancia_esperada']}\n"
            f"Ratio:        {riesgo['ratio']}\n"
            f"{'='*32}\n"
            f"RSI:         {rsi}\n"
            f"Volatilidad ATR: ${atr}\n"
            f"BB inferior: ${bb_lower:,.2f}\n"
            f"BB superior: ${bb_upper:,.2f}\n"
            f"MA50:        ${ma50:,.2f}\n"
            f"MA200:       ${ma200:,.2f}\n"
            f"{obv_texto}\n"
            f"Hora:        {hora}\n"
            f"{'='*32}\n"
            f"PAPER TRADING - Solo educativo"
        )
    elif tipo == "ESPERAR":
        mensaje = (
            f"[ESPERAR] {simbolo}\n"
            f"Tendencia 1h: {tendencia_1h} | 4h: {tendencia_4h}\n"
            f"MA50 ${ma50:,.2f} < MA200 ${ma200:,.2f}\n"
            f"Capital protegido. Sin operaciones.\n"
            f"Hora: {hora}"
        )
    else:
        mensaje = None

    return {
        "tipo":         tipo,
        "precio":       precio,
        "rsi":          rsi,
        "tendencia":    tendencia_1h,
        "tendencia_4h": tendencia_4h,
        "confianza":    confianza,
        "simbolo":      simbolo,
        "mensaje":      mensaje,
        "riesgo":       riesgo
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


def enviar_alerta_con_botones(mensaje, senal):
    """
    Envía la alerta con botones inline [ ✅ OPERAR ] [ ❌ IGNORAR ].
    Guarda la señal en _senales_pendientes para responder al callback.
    """
    clave = f"{senal['simbolo']}_{int(datetime.now().timestamp())}"
    _senales_pendientes[f"operar_{clave}"] = senal
    _senales_pendientes[f"ignorar_{clave}"] = senal

    url     = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    config.TELEGRAM_CHAT_ID,
        "text":       mensaje,
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ OPERAR",  "callback_data": f"operar_{clave}"},
                {"text": "❌ IGNORAR", "callback_data": f"ignorar_{clave}"}
            ]]
        }
    }
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        log.info("Alerta con botones enviada a Telegram")
    else:
        log.error(f"Error enviando alerta con botones: {resp.text}")


def responder_callback(callback_query_id, chat_id, texto):
    """Responde a un toque de botón."""
    # Confirmar el callback para quitar el "cargando"
    requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id}
    )
    # Enviar el mensaje de respuesta
    requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": texto}
    )


def iniciar_polling_callbacks():
    """
    Corre en un hilo separado. Escucha los toques de botón del usuario
    y responde según si tocó OPERAR o IGNORAR.
    """
    offset = 0
    log.info("Polling de callbacks iniciado")

    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35
            )
            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

                callback = update.get("callback_query")
                if not callback:
                    continue

                data     = callback["data"]
                chat_id  = callback["message"]["chat"]["id"]
                cb_id    = callback["id"]

                senal = _senales_pendientes.pop(data, None)
                if senal is None:
                    continue

                if data.startswith("operar_"):
                    riesgo = senal.get("riesgo") or {}
                    stop   = riesgo.get("stop_loss", "N/A")
                    target = riesgo.get("take_profit", "N/A")
                    texto  = (
                        f"✅ Señal confirmada. Ve a Binance\n"
                        f"y compra $10 de {senal['simbolo']} a ${senal['precio']:,.2f}\n"
                        f"Stop-Loss:   ${stop:,.2f}\n"
                        f"Take-Profit: ${target:,.2f}"
                    )
                else:
                    texto = "❌ Señal ignorada. Seguimos monitoreando."

                responder_callback(cb_id, chat_id, texto)
                log.info(f"Callback procesado: {data}")

        except Exception as e:
            log.error(f"Error en polling callbacks: {e}")


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
# 9b. RESAMPLEAR 1H → 4H (para stocks — evita segunda llamada a la API)
# ============================================================
def resamplear_4h(df_1h):
    df = df_1h.copy().set_index("timestamp")
    df_4h = df.resample("4h").agg({
        "open": "first", "high": "max",
        "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    if len(df_4h) < 50:
        log.warning(f"resamplear_4h: solo {len(df_4h)} velas 4h — insuficiente para indicadores completos")
    return df_4h


# ============================================================
# 10. CICLO PRINCIPAL
# ============================================================
def ejecutar_ciclo():
    log.info("=" * 50)
    log.info("Iniciando ciclo de analisis...")

    exchange = conectar_exchange()

    for simbolo in config.SIMBOLOS:
        try:
            df_1h = obtener_velas(exchange, simbolo, config.INTERVALO)
            df_4h = obtener_velas(exchange, simbolo, "4h")
            df_1h = calcular_indicadores(df_1h)
            df_4h = calcular_indicadores(df_4h)
            senal = evaluar_senal(df_1h, df_4h, simbolo)
            log.info(
                f"{simbolo} | {senal['tipo']} | "
                f"${senal['precio']:,.2f} | "
                f"RSI: {senal['rsi']} | "
                f"Tendencia 1h: {senal['tendencia']} | "
                f"Tendencia 4h: {senal['tendencia_4h']}"
            )
            if senal["tipo"] in ["COMPRA", "VENTA"]:
                # Verificar cooldown de 4 horas por activo
                ultima = _ultima_alerta.get(simbolo)
                en_cooldown = ultima and (datetime.now() - ultima) < timedelta(hours=4)

                if en_cooldown:
                    log.info(f"{simbolo} en cooldown — alerta omitida (última hace {int((datetime.now()-ultima).seconds/60)} min)")
                else:
                    # Claude razona la señal antes de alertar
                    analisis = agente.obtener_analisis(senal, df_1h)

                    if analisis["decision"] in ["COMPRA", "VENTA"]:
                        paper_trading.abrir_operacion(
                            senal["simbolo"],
                            senal["precio"],
                            analisis["decision"],
                            analisis
                        )
                        mensaje_final = agente.construir_mensaje_claude(
                            senal, analisis, senal["riesgo"]
                        )
                        enviar_alerta_con_botones(mensaje_final, senal)
                        _ultima_alerta[simbolo] = datetime.now()
                    else:
                        log.info(f"Claude descartó la señal: {analisis['razon']}")

            # Verificar si hay operaciones abiertas que cerrar
            precios  = {senal["simbolo"]: senal["precio"]}
            cerradas = paper_trading.verificar_operaciones_abiertas(precios)
            for op in (cerradas or []):
                if op["resultado"] == "TAKE_PROFIT":
                    msg_cierre = (
                        f"🟢 TAKE-PROFIT alcanzado — {op['simbolo']}\n"
                        f"Salida a ${op['precio_salida']:,.2f}\n"
                        f"Ganancia: +${op['ganancia']:,.2f} ({op['variacion_pct']:+.2f}%)"
                    )
                else:
                    msg_cierre = (
                        f"🔴 STOP-LOSS alcanzado — {op['simbolo']}\n"
                        f"Salida a ${op['precio_salida']:,.2f}\n"
                        f"Pérdida: ${op['ganancia']:,.2f} ({op['variacion_pct']:+.2f}%)"
                    )
                enviar_telegram(msg_cierre)
                log.info(f"Notificación de cierre enviada: {op['resultado']} {op['simbolo']}")
            guardar_registro(senal)
        except Exception as error:
            log.error(f"Error analizando {simbolo}: {error}")

    for simbolo in config.STOCKS:
        try:
            df_1h = obtener_velas_stock(simbolo, config.INTERVALO)
            df_4h = resamplear_4h(df_1h)          # resampleo local, sin llamada extra a la API
            df_1h = calcular_indicadores(df_1h)
            df_4h = calcular_indicadores(df_4h)
            senal = evaluar_senal(df_1h, df_4h, simbolo)
            log.info(
                f"{simbolo} | {senal['tipo']} | "
                f"${senal['precio']:,.2f} | "
                f"RSI: {senal['rsi']} | "
                f"Tendencia 1h: {senal['tendencia']} | "
                f"Tendencia 4h: {senal['tendencia_4h']}"
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

    # Iniciar polling de botones en hilo separado (no bloquea el scheduler)
    hilo_polling = threading.Thread(target=iniciar_polling_callbacks, daemon=True)
    hilo_polling.start()

    ejecutar_ciclo()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        ejecutar_ciclo,
        "interval",
        minutes=config.FRECUENCIA_MINUTOS
    )
    scheduler.start()