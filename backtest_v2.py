# ============================================================
# backtest_v2.py — Estrategia Trend Following + RSI
# ============================================================
#
# Lógica:
#   1. Detecta si el mercado es alcista o bajista
#      usando MA50 vs MA200
#   2. Solo compra en tendencia ALCISTA
#   3. Usa RSI para timing de entrada
#   4. Gestión de riesgo estricta
#
# ============================================================

import ccxt
import pandas as pd
import yfinance as yf
import config


# ============================================================
# 1. OBTENER DATOS HISTÓRICOS
# ============================================================
def obtener_historico_cripto(simbolo, intervalo="1h"):
    exchange = ccxt.binance({
        "apiKey": config.BINANCE_API_KEY,
        "secret": config.BINANCE_SECRET,
    })
    print(f"Descargando historial de {simbolo}...")
    datos = exchange.fetch_ohlcv(simbolo, intervalo, limit=1000)
    df = pd.DataFrame(datos, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    print(f"  {len(df)} velas descargadas")
    return df


def obtener_historico_stock(simbolo, intervalo="1h"):
    print(f"Descargando historial de {simbolo}...")
    ticker = yf.Ticker(simbolo)
    df = ticker.history(period="60d", interval=intervalo).reset_index()
    col_time = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={
        col_time: "timestamp",
        "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume"
    })
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    print(f"  {len(df)} velas descargadas")
    return df


# ============================================================
# 2. CALCULAR INDICADORES
# ============================================================
def calcular_indicadores(df):
    # RSI
    delta    = df["close"].diff()
    ganancia = delta.clip(lower=0).rolling(14).mean()
    perdida  = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + ganancia / perdida))

    # MACD
    ema12          = df["close"].ewm(span=12, adjust=False).mean()
    ema26          = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"]     = ema12 - ema26
    df["MACD_sig"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # Medias móviles de tendencia
    df["MA20"]  = df["close"].rolling(20).mean()
    df["MA50"]  = df["close"].rolling(50).mean()
    df["MA200"] = df["close"].rolling(200).mean()

    return df.dropna().reset_index(drop=True)


# ============================================================
# 3. DETECTAR TENDENCIA DEL MERCADO
# ============================================================
def detectar_tendencia(fila):
    """
    Determina si el mercado está en tendencia alcista o bajista.

    Golden Cross: MA50 > MA200 → mercado alcista → operar
    Death Cross:  MA50 < MA200 → mercado bajista → no operar
    """
    if fila["MA50"] > fila["MA200"]:
        return "ALCISTA"
    else:
        return "BAJISTA"


# ============================================================
# 4. SIMULAR OPERACIONES — TREND FOLLOWING
# ============================================================
def simular_operaciones(df, simbolo, capital_inicial=100):
    capital        = capital_inicial
    operaciones    = []
    en_operacion   = False
    precio_entrada = 0
    stop_loss      = 0
    take_profit    = 0
    capital_en_uso = 0

    # Parámetros de esta estrategia
    STOP    = 0.02   # 2% stop-loss
    TARGET  = 0.06   # 6% take-profit → ratio 1:3
    RIESGO  = 0.10   # 10% del capital por operación
    RSI_MIN = 35     # Entrada cuando RSI baja de 35
    RSI_MAX = 65     # Salida cuando RSI sube a 65

    for i in range(1, len(df)):
        fila     = df.iloc[i]
        anterior = df.iloc[i - 1]

        precio    = fila["close"]
        rsi       = fila["RSI"]
        tendencia = detectar_tendencia(fila)

        macd_alcista = (fila["MACD"] > fila["MACD_sig"] and
                        anterior["MACD"] <= anterior["MACD_sig"])

        # --- GESTIONAR OPERACIÓN ABIERTA ---
        if en_operacion:
            resultado = None

            # Salida por stop-loss
            if precio <= stop_loss:
                resultado  = "STOP_LOSS"
                ganancia   = -(capital_en_uso * STOP)
                capital   += capital_en_uso + ganancia
                en_operacion = False

            # Salida por take-profit
            elif precio >= take_profit:
                resultado  = "TAKE_PROFIT"
                ganancia   = capital_en_uso * TARGET
                capital   += capital_en_uso + ganancia
                en_operacion = False

            # Salida por RSI sobrecomprado (tomar ganancias)
            elif rsi > RSI_MAX:
                resultado  = "TAKE_PROFIT"
                ganancia   = (precio - precio_entrada) / precio_entrada * capital_en_uso
                capital   += capital_en_uso + ganancia
                en_operacion = False

            if resultado:
                operaciones.append({
                    "tipo":             "CIERRE",
                    "fecha":            str(fila["timestamp"]),
                    "precio":           round(precio, 4),
                    "resultado":        resultado,
                    "ganancia_perdida": round(ganancia, 2),
                    "capital":          round(capital, 2),
                    "tendencia":        tendencia,
                })

        # --- BUSCAR NUEVA ENTRADA ---
        else:
            # CONDICIÓN CLAVE: Solo operar en tendencia ALCISTA
            if tendencia == "ALCISTA" and capital > 10:
                if rsi < RSI_MIN and macd_alcista:
                    capital_en_uso  = capital * RIESGO
                    capital        -= capital_en_uso
                    precio_entrada  = precio
                    stop_loss       = precio * (1 - STOP)
                    take_profit     = precio * (1 + TARGET)
                    en_operacion    = True

                    operaciones.append({
                        "tipo":             "ENTRADA",
                        "fecha":            str(fila["timestamp"]),
                        "precio":           round(precio_entrada, 4),
                        "capital_usado":    round(capital_en_uso, 2),
                        "stop_loss":        round(stop_loss, 4),
                        "take_profit":      round(take_profit, 4),
                        "resultado":        "ABIERTA",
                        "ganancia_perdida": 0,
                        "capital":          round(capital, 2),
                        "tendencia":        tendencia,
                    })

    return operaciones, capital


# ============================================================
# 5. MOSTRAR RESULTADOS
# ============================================================
def mostrar_resultados(operaciones, capital_inicial, capital_final, simbolo):
    cierres   = [op for op in operaciones if op["tipo"] == "CIERRE"]
    ganadoras = [op for op in cierres if op["resultado"] == "TAKE_PROFIT"]
    perdedoras = [op for op in cierres if op["resultado"] == "STOP_LOSS"]

    total         = len(cierres)
    tasa_exito    = (len(ganadoras) / total * 100) if total > 0 else 0
    ganancia_neta = sum(op["ganancia_perdida"] for op in cierres)
    rentabilidad  = ((capital_final - capital_inicial) / capital_inicial) * 100

    # Contar cuántas velas estuvieron en tendencia alcista
    entradas = [op for op in operaciones if op["tipo"] == "ENTRADA"]
    ops_en_alcista = sum(1 for op in entradas if op.get("tendencia") == "ALCISTA")

    print("\n" + "=" * 50)
    print(f"  RESULTADOS — {simbolo}")
    print("=" * 50)
    print(f"  Capital inicial:    ${capital_inicial}")
    print(f"  Capital final:      ${round(capital_final, 2)}")
    print(f"  Ganancia/Perdida:   ${round(ganancia_neta, 2)}")
    print(f"  Rentabilidad:       {round(rentabilidad, 2)}%")
    print(f"  Total operaciones:  {total}")
    print(f"  Ganadoras:          {len(ganadoras)}")
    print(f"  Perdedoras:         {len(perdedoras)}")
    print(f"  Tasa de exito:      {round(tasa_exito, 1)}%")
    print(f"  Ops en alcista:     {ops_en_alcista}")
    print("=" * 50)

    if rentabilidad > 0:
        print(f"  ESTRATEGIA RENTABLE")
    elif rentabilidad > -5:
        print(f"  CERCA — Ajuste fino necesario")
    else:
        print(f"  NO RENTABLE — Revisar estrategia")
    print("=" * 50)

    # Guardar CSV
    if cierres:
        pd.DataFrame(cierres).to_csv(
            f"backtest_v2_{simbolo.replace('/', '_')}.csv",
            index=False
        )
        print(f"  Detalle: backtest_v2_{simbolo.replace('/', '_')}.csv")

    return rentabilidad


# ============================================================
# 6. EJECUTAR
# ============================================================
def ejecutar_backtest():
    print("\n" + "=" * 50)
    print("  BACKTEST V2 — TREND FOLLOWING + RSI")
    print("  Logica: Solo opera en tendencia alcista")
    print(f"  Capital: ${config.CAPITAL_TOTAL}")
    print("=" * 50)

    resultados = []

    for simbolo in config.SIMBOLOS:
        try:
            df = obtener_historico_cripto(simbolo)
            df = calcular_indicadores(df)
            ops, capital_final = simular_operaciones(df, simbolo, config.CAPITAL_TOTAL)
            rent = mostrar_resultados(ops, config.CAPITAL_TOTAL, capital_final, simbolo)
            resultados.append({"simbolo": simbolo, "rentabilidad": rent})
        except Exception as e:
            print(f"Error en {simbolo}: {e}")

    for simbolo in config.STOCKS:
        try:
            df = obtener_historico_stock(simbolo)
            df = calcular_indicadores(df)
            ops, capital_final = simular_operaciones(df, simbolo, config.CAPITAL_TOTAL)
            rent = mostrar_resultados(ops, config.CAPITAL_TOTAL, capital_final, simbolo)
            resultados.append({"simbolo": simbolo, "rentabilidad": rent})
        except Exception as e:
            print(f"Error en {simbolo}: {e}")

    print("\n" + "=" * 50)
    print("  RESUMEN FINAL")
    print("=" * 50)
    for r in resultados:
        estado = "RENTABLE" if r["rentabilidad"] > 0 else "NO RENTABLE"
        print(f"  {r['simbolo']:12} → {r['rentabilidad']:+.2f}%  ({estado})")
    print("=" * 50)


if __name__ == "__main__":
    ejecutar_backtest()