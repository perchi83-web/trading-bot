# ============================================================
# paper_trading.py — Registro formal de paper trading
# ============================================================
#
# Simula operaciones reales con dinero virtual.
# Registra cada entrada y salida con métricas precisas.
#
# Responde preguntas como:
#   - ¿Cuánto gané/perdí en papel este mes?
#   - ¿Qué porcentaje de señales fueron correctas?
#   - ¿Vale la pena pasar a dinero real?
#
# ============================================================

import pandas as pd
import json
import os
from datetime import datetime
import config


# ============================================================
# ARCHIVO DE ESTADO
# Guarda el estado actual del portafolio virtual
# ============================================================
ARCHIVO_ESTADO    = "paper_estado.json"
ARCHIVO_HISTORIAL = "paper_historial.csv"


# ============================================================
# 1. CARGAR O CREAR ESTADO INICIAL
# ============================================================
def cargar_estado():
    """
    Carga el estado actual del portafolio virtual.
    Si no existe, crea uno nuevo con el capital inicial.
    """
    if os.path.exists(ARCHIVO_ESTADO):
        with open(ARCHIVO_ESTADO, "r") as f:
            return json.load(f)
    else:
        estado_inicial = {
            "capital_disponible":  config.CAPITAL_TOTAL,
            "capital_inicial":     config.CAPITAL_TOTAL,
            "operaciones_abiertas": {},
            "total_operaciones":   0,
            "operaciones_ganadoras": 0,
            "operaciones_perdedoras": 0,
            "ganancia_total":      0.0,
            "fecha_inicio":        datetime.now().strftime("%Y-%m-%d"),
        }
        guardar_estado(estado_inicial)
        return estado_inicial


# ============================================================
# 2. GUARDAR ESTADO
# ============================================================
def guardar_estado(estado):
    with open(ARCHIVO_ESTADO, "w") as f:
        json.dump(estado, f, indent=2)


# ============================================================
# 3. ABRIR OPERACIÓN VIRTUAL
# ============================================================
def abrir_operacion(simbolo, precio_entrada, tipo, analisis_claude):
    """
    Registra una nueva operación virtual de paper trading.

    Es como si realmente compraras/vendieras,
    pero con dinero virtual.
    """
    estado = cargar_estado()

    # Verificar que no hay operación abierta en este activo
    if simbolo in estado["operaciones_abiertas"]:
        return None, "Ya hay una operación abierta en este activo"

    # Calcular capital a usar
    capital_op  = estado["capital_disponible"] * config.RIESGO_POR_OPERACION
    stop_loss   = precio_entrada * (1 - config.STOP_LOSS_PORCENTAJE)
    take_profit = precio_entrada * (1 + config.TAKE_PROFIT_PORCENTAJE)

    if capital_op < 5:
        return None, "Capital insuficiente para operar"

    # Registrar operación
    operacion = {
        "simbolo":         simbolo,
        "tipo":            tipo,
        "precio_entrada":  round(precio_entrada, 4),
        "capital_usado":   round(capital_op, 2),
        "stop_loss":       round(stop_loss, 4),
        "take_profit":     round(take_profit, 4),
        "fecha_entrada":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "decision_claude": analisis_claude.get("decision", ""),
        "confianza":       analisis_claude.get("confianza", ""),
        "razon_claude":    analisis_claude.get("razon", ""),
    }

    # Descontar capital
    estado["capital_disponible"]         -= capital_op
    estado["operaciones_abiertas"][simbolo] = operacion
    estado["total_operaciones"]          += 1

    guardar_estado(estado)

    print(f"[PAPER] Operacion abierta: {simbolo} {tipo} @ ${precio_entrada:,.2f}")
    print(f"        Capital usado: ${capital_op:.2f}")
    print(f"        Stop-Loss:     ${stop_loss:,.2f}")
    print(f"        Take-Profit:   ${take_profit:,.2f}")

    return operacion, "OK"


# ============================================================
# 4. CERRAR OPERACIÓN VIRTUAL
# ============================================================
def cerrar_operacion(simbolo, precio_actual):
    """
    Cierra una operación abierta y calcula el resultado.
    Se llama cuando el precio alcanza stop-loss o take-profit.
    """
    estado = cargar_estado()

    if simbolo not in estado["operaciones_abiertas"]:
        return None

    op = estado["operaciones_abiertas"][simbolo]

    # Calcular ganancia o pérdida
    variacion   = (precio_actual - op["precio_entrada"]) / op["precio_entrada"]
    ganancia    = op["capital_usado"] * variacion
    capital_ret = op["capital_usado"] + ganancia

    if ganancia > 0:
        resultado = "TAKE_PROFIT"
        estado["operaciones_ganadoras"] += 1
    else:
        resultado = "STOP_LOSS"
        estado["operaciones_perdedoras"] += 1

    # Actualizar capital
    estado["capital_disponible"] += capital_ret
    estado["ganancia_total"]     += ganancia

    # Guardar en historial
    registro = {
        "fecha_entrada":   op["fecha_entrada"],
        "fecha_salida":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "simbolo":         simbolo,
        "tipo":            op["tipo"],
        "precio_entrada":  op["precio_entrada"],
        "precio_salida":   round(precio_actual, 4),
        "capital_usado":   op["capital_usado"],
        "ganancia":        round(ganancia, 2),
        "resultado":       resultado,
        "variacion_pct":   round(variacion * 100, 2),
        "decision_claude": op["decision_claude"],
        "confianza":       op["confianza"],
        "capital_total":   round(estado["capital_disponible"], 2),
    }

    df = pd.DataFrame([registro])
    df.to_csv(
        ARCHIVO_HISTORIAL,
        mode="a",
        header=not os.path.exists(ARCHIVO_HISTORIAL),
        index=False
    )

    # Eliminar operación abierta
    del estado["operaciones_abiertas"][simbolo]
    guardar_estado(estado)

    print(f"[PAPER] Operacion cerrada: {simbolo} @ ${precio_actual:,.2f}")
    print(f"        Resultado:  {resultado}")
    print(f"        Ganancia:   ${ganancia:.2f} ({variacion*100:.2f}%)")

    return registro


# ============================================================
# 5. VERIFICAR OPERACIONES ABIERTAS
# ============================================================
def verificar_operaciones_abiertas(precios_actuales):
    """
    Revisa si alguna operación abierta alcanzó
    su stop-loss o take-profit.

    precios_actuales = {"BTC/USDT": 67000, "ETH/USDT": 1950}
    """
    estado = cargar_estado()
    cerradas = []

    for simbolo, op in list(estado["operaciones_abiertas"].items()):
        if simbolo not in precios_actuales:
            continue

        precio = precios_actuales[simbolo]

        if precio <= op["stop_loss"]:
            registro = cerrar_operacion(simbolo, precio)
            cerradas.append(registro)
        elif precio >= op["take_profit"]:
            registro = cerrar_operacion(simbolo, precio)
            cerradas.append(registro)

    return cerradas


# ============================================================
# 6. REPORTE DE RENDIMIENTO
# ============================================================
def generar_reporte():
    """
    Genera un reporte completo del paper trading.
    Muestra si la estrategia es rentable o no.
    """
    estado = cargar_estado()

    capital_actual  = estado["capital_disponible"]
    capital_inicial = estado["capital_inicial"]
    rentabilidad    = ((capital_actual - capital_inicial) / capital_inicial) * 100

    total    = estado["total_operaciones"]
    ganadoras = estado["operaciones_ganadoras"]
    perdedoras = estado["operaciones_perdedoras"]
    tasa     = (ganadoras / total * 100) if total > 0 else 0

    abiertas = len(estado["operaciones_abiertas"])

    reporte = (
        f"\n{'='*45}\n"
        f"  REPORTE PAPER TRADING\n"
        f"  Desde: {estado['fecha_inicio']}\n"
        f"{'='*45}\n"
        f"  Capital inicial:    ${capital_inicial:.2f}\n"
        f"  Capital actual:     ${capital_actual:.2f}\n"
        f"  Ganancia/Perdida:   ${estado['ganancia_total']:.2f}\n"
        f"  Rentabilidad:       {rentabilidad:.2f}%\n"
        f"{'='*45}\n"
        f"  Total operaciones:  {total}\n"
        f"  Ganadoras:          {ganadoras}\n"
        f"  Perdedoras:         {perdedoras}\n"
        f"  Tasa de exito:      {tasa:.1f}%\n"
        f"  Abiertas ahora:     {abiertas}\n"
        f"{'='*45}\n"
    )

    if rentabilidad > 5:
        reporte += "  ESTRATEGIA RENTABLE — considera dinero real\n"
    elif rentabilidad > 0:
        reporte += "  CERCA — sigue observando\n"
    else:
        reporte += "  NO RENTABLE aun — sigue en paper trading\n"

    reporte += f"{'='*45}\n"

    print(reporte)
    return estado


# ============================================================
# 7. VER ESTADO ACTUAL
# ============================================================
if __name__ == "__main__":
    print("\nEstado actual del paper trading:")
    estado = generar_reporte()

    if estado["operaciones_abiertas"]:
        print("Operaciones abiertas:")
        for simbolo, op in estado["operaciones_abiertas"].items():
            print(f"  {simbolo}: {op['tipo']} @ ${op['precio_entrada']:,.2f}")
            print(f"    Stop:   ${op['stop_loss']:,.2f}")
            print(f"    Target: ${op['take_profit']:,.2f}")
    else:
        print("No hay operaciones abiertas actualmente.")