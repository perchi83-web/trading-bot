# ============================================================
# backtest.py — Prueba la estrategia con datos históricos
# ============================================================
#
# Responde la pregunta clave:
# "Si este bot hubiera corrido los últimos 6 meses,
#  ¿cuánto habría ganado o perdido?"
#
# Cómo usarlo:
#   python backtest.py
#
# ============================================================

import ccxt
import pandas as pd
import yfinance as yf
from datetime import datetime
import config


# ============================================================
# 1. OBTENER DATOS HISTÓRICOS
# ============================================================
def obtener_historico_cripto(simbolo, intervalo="1h", dias=180):
    """
    Descarga datos históricos de los últimos N días.
    180 días = 6 meses de historial para analizar.
    """
    exchange = ccxt.binance({
        "apiKey": config.BINANCE_API_KEY,
        "secret": config.BINANCE_SECRET,
    })

    # Binance permite máximo 1000 velas por petición
    # Para 6 meses en velas de 1h necesitamos ~4320 velas
    # Las descargamos en bloques
    limite = 1000
    todas_las_velas = []

    print(f"Descargando historial de {simbolo} ({dias} dias)...")

    datos = exchange.fetch_ohlcv(simbolo, intervalo, limit=limite)
    todas_las_velas.extend(datos)

    df = pd.DataFrame(todas_las_velas, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)

    print(f"  {len(df)} velas descargadas para {simbolo}")
    return df


def obtener_historico_stock(simbolo, intervalo="1h", dias=180):
    """
    Descarga datos históricos de una acción usando Yahoo Finance.
    """
    print(f"Descargando historial de {simbolo} ({dias} dias)...")
    ticker = yf.Ticker(simbolo)
    df = ticker.history(period="60d", interval=intervalo)
    df = df.reset_index()

    col_time = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={
        col_time: "timestamp",
        "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume"
    })
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    print(f"  {len(df)} velas descargadas para {simbolo}")
    return df


# ============================================================
# 2. CALCULAR INDICADORES
# ============================================================
def calcular_indicadores(df):
    # RSI
    delta    = df["close"].diff()
    ganancia = delta.clip(lower=0).rolling(config.RSI_PERIODO).mean()
    perdida  = (-delta.clip(upper=0)).rolling(config.RSI_PERIODO).mean()
    rs       = ganancia / perdida
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema_rapida       = df["close"].ewm(span=12, adjust=False).mean()
    ema_lenta        = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"]       = ema_rapida - ema_lenta
    df["MACD_senal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # MA20
    df["MA20"] = df["close"].rolling(20).mean()

    return df.dropna().reset_index(drop=True)


# ============================================================
# 3. SIMULAR OPERACIONES
# ============================================================
def simular_operaciones(df, simbolo, capital_inicial=100):
    """
    Recorre cada vela histórica y simula qué hubiera hecho el bot.

    Por cada señal de COMPRA:
      - "Compra" con el 10% del capital disponible
      - Aplica stop-loss (-2%) y take-profit (+4%)
      - Registra el resultado

    Al final muestra cuánto ganó o perdió la estrategia.
    """
    capital      = capital_inicial
    operaciones  = []
    en_operacion = False
    precio_entrada = 0
    stop_loss    = 0
    take_profit  = 0
    capital_en_uso = 0

    for i in range(1, len(df)):
        fila     = df.iloc[i]
        anterior = df.iloc[i - 1]

        precio = fila["close"]
        rsi    = fila["RSI"]
        macd   = fila["MACD"]
        macd_s = fila["MACD_senal"]
        ma20   = fila["MA20"]

        macd_cruce_alcista = (macd > macd_s and anterior["MACD"] <= anterior["MACD_senal"])
        macd_cruce_bajista = (macd < macd_s and anterior["MACD"] >= anterior["MACD_senal"])

        # --- Si estamos en una operación, verificar salida ---
        if en_operacion:
            resultado = None

            if precio <= stop_loss:
                resultado   = "STOP_LOSS"
                ganancia    = -(capital_en_uso * config.STOP_LOSS_PORCENTAJE)
                capital    += capital_en_uso + ganancia
                en_operacion = False

            elif precio >= take_profit:
                resultado   = "TAKE_PROFIT"
                ganancia    = capital_en_uso * config.TAKE_PROFIT_PORCENTAJE
                capital    += capital_en_uso + ganancia
                en_operacion = False

            if resultado:
                operaciones.append({
                    "fecha_salida": fila["timestamp"],
                    "precio_salida": round(precio, 4),
                    "resultado": resultado,
                    "ganancia_perdida": round(ganancia, 2),
                    "capital_acumulado": round(capital, 2),
                })

        # --- Si no estamos en operación, buscar entrada ---
        else:
            if capital > 10:
                # Para criptos — filtro estricto
                # Para acciones — filtro más flexible
                es_cripto = "/" in simbolo

                if es_cripto:
                    ultimas_3 = df.iloc[i-3:i]["close"]
                    tendencia_bajista = ultimas_3.is_monotonic_decreasing
                    condicion_entrada = (
                        rsi < config.RSI_SOBREVENDIDO and
                        macd_cruce_alcista and
                        precio < ma20 and
                        not tendencia_bajista
                    )
                else:
                        # Acciones — solo RSI extremo es suficiente
                    condicion_entrada = (
                    rsi < config.RSI_SOBREVENDIDO
                    )

                if condicion_entrada:
                    capital_en_uso  = capital * config.RIESGO_POR_OPERACION
                    capital        -= capital_en_uso
                    precio_entrada  = precio
                    stop_loss       = precio * (1 - config.STOP_LOSS_PORCENTAJE)
                    take_profit     = precio * (1 + config.TAKE_PROFIT_PORCENTAJE)
                    en_operacion    = True

                    operaciones.append({
                        "fecha_entrada": fila["timestamp"],
                        "precio_entrada": round(precio_entrada, 4),
                        "capital_en_uso": round(capital_en_uso, 2),
                        "stop_loss": round(stop_loss, 4),
                        "take_profit": round(take_profit, 4),
                        "resultado": "ABIERTA",
                        "ganancia_perdida": 0,
                        "capital_acumulado": round(capital, 2),
                    })

    return operaciones, capital


# ============================================================
# 4. MOSTRAR RESULTADOS
# ============================================================
def mostrar_resultados(operaciones, capital_inicial, capital_final, simbolo):
    """
    Muestra un resumen claro de qué tan bien funcionó la estrategia.
    """
    cerradas = [op for op in operaciones if op["resultado"] in ["STOP_LOSS", "TAKE_PROFIT"]]
    ganadoras = [op for op in cerradas if op["resultado"] == "TAKE_PROFIT"]
    perdedoras = [op for op in cerradas if op["resultado"] == "STOP_LOSS"]

    total_ops      = len(cerradas)
    total_ganadoras = len(ganadoras)
    total_perdedoras = len(perdedoras)
    tasa_exito     = (total_ganadoras / total_ops * 100) if total_ops > 0 else 0

    ganancia_total = sum(op["ganancia_perdida"] for op in cerradas)
    rentabilidad   = ((capital_final - capital_inicial) / capital_inicial) * 100

    print("\n" + "=" * 50)
    print(f"  RESULTADOS DEL BACKTEST — {simbolo}")
    print("=" * 50)
    print(f"  Periodo analizado:    Ultimas 1000 velas (1h)")
    print(f"  Capital inicial:      ${capital_inicial}")
    print(f"  Capital final:        ${round(capital_final, 2)}")
    print(f"  Ganancia/Perdida:     ${round(ganancia_total, 2)}")
    print(f"  Rentabilidad:         {round(rentabilidad, 2)}%")
    print(f"  Total operaciones:    {total_ops}")
    print(f"  Ganadoras:            {total_ganadoras}")
    print(f"  Perdedoras:           {total_perdedoras}")
    print(f"  Tasa de exito:        {round(tasa_exito, 1)}%")
    print("=" * 50)

    if rentabilidad > 0:
        print(f"  ESTRATEGIA RENTABLE en este periodo")
    else:
        print(f"  ESTRATEGIA NO RENTABLE en este periodo")
        print(f"  Ajustar parametros antes de usar dinero real")
    print("=" * 50)

    # Guardar detalle en CSV
    if cerradas:
        df_ops = pd.DataFrame(cerradas)
        nombre_archivo = f"backtest_{simbolo.replace('/', '_')}.csv"
        df_ops.to_csv(nombre_archivo, index=False)
        print(f"\n  Detalle guardado en: {nombre_archivo}")

    return rentabilidad


# ============================================================
# 5. EJECUTAR BACKTEST COMPLETO
# ============================================================
def ejecutar_backtest():
    print("\n" + "=" * 50)
    print("  INICIANDO BACKTEST")
    print(f"  Capital inicial: ${config.CAPITAL_TOTAL}")
    print(f"  Riesgo/op: {config.RIESGO_POR_OPERACION*100}%")
    print(f"  Stop-Loss: {config.STOP_LOSS_PORCENTAJE*100}%")
    print(f"  Take-Profit: {config.TAKE_PROFIT_PORCENTAJE*100}%")
    print("=" * 50)

    resultados = []

    # Backtest criptos
    for simbolo in config.SIMBOLOS:
        try:
            df = obtener_historico_cripto(simbolo)
            df = calcular_indicadores(df)
            operaciones, capital_final = simular_operaciones(
                df, simbolo, config.CAPITAL_TOTAL
            )
            rentabilidad = mostrar_resultados(
                operaciones, config.CAPITAL_TOTAL, capital_final, simbolo
            )
            resultados.append({"simbolo": simbolo, "rentabilidad": rentabilidad})
        except Exception as e:
            print(f"Error en backtest de {simbolo}: {e}")

    # Backtest acciones
    for simbolo in config.STOCKS:
        try:
            df = obtener_historico_stock(simbolo)
            df = calcular_indicadores(df)
            operaciones, capital_final = simular_operaciones(
                df, simbolo, config.CAPITAL_TOTAL
            )
            rentabilidad = mostrar_resultados(
                operaciones, config.CAPITAL_TOTAL, capital_final, simbolo
            )
            resultados.append({"simbolo": simbolo, "rentabilidad": rentabilidad})
        except Exception as e:
            print(f"Error en backtest de {simbolo}: {e}")

    # Resumen final
    print("\n" + "=" * 50)
    print("  RESUMEN FINAL")
    print("=" * 50)
    for r in resultados:
        estado = "RENTABLE" if r["rentabilidad"] > 0 else "NO RENTABLE"
        print(f"  {r['simbolo']:12} → {r['rentabilidad']:+.2f}%  ({estado})")
    print("=" * 50)


if __name__ == "__main__":
    ejecutar_backtest()