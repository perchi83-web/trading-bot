# ============================================================
# agente.py — Claude como cerebro del bot de trading
# ============================================================
#
# Este archivo conecta el bot con Claude para que RAZONE
# cada señal antes de enviarte la alerta.
#
# En lugar de solo decir "RSI bajo = COMPRA",
# Claude analiza el contexto completo y dice:
#
#   "RSI en 27 + MACD cruzando + tendencia alcista +
#    precio cerca de soporte MA20 = alta probabilidad
#    de rebote. Recomiendo entrada con stop ajustado."
#
# ============================================================

import anthropic
import config


# ============================================================
# 1. CONECTAR CON CLAUDE
# ============================================================
def crear_cliente():
    """
    Crea la conexión con la API de Claude.
    Usamos claude-3-haiku — el más rápido y económico,
    ideal para análisis frecuentes cada hora.
    """
    return anthropic.Anthropic(api_key=config.CLAUDE_API_KEY)


# ============================================================
# 2. ANALIZAR SEÑAL CON CLAUDE
# ============================================================
def analizar_con_claude(datos_mercado):
    """
    Envía los datos del mercado a Claude y recibe
    un análisis razonado como trader profesional.

    datos_mercado es un diccionario con:
        - simbolo:   el activo (BTC/USDT, ETH, NVDA)
        - precio:    precio actual
        - rsi:       valor RSI
        - macd:      valor MACD
        - macd_sig:  línea de señal MACD
        - ma20:      media móvil 20
        - ma50:      media móvil 50
        - ma200:     media móvil 200
        - tendencia: ALCISTA o BAJISTA
        - senal_bot: lo que detectó el bot (COMPRA/VENTA/NEUTRAL/ESPERAR)
    """
    cliente = crear_cliente()

    # Construimos el prompt con todos los datos
    prompt = f"""Eres un trader profesional con 15 años de experiencia.
Analiza estos datos de mercado y dame tu opinión experta.

DATOS DEL MERCADO:
- Activo: {datos_mercado['simbolo']}
- Precio actual: ${datos_mercado['precio']:,.2f}
- Tendencia (MA50 vs MA200): {datos_mercado['tendencia']}
- RSI (14): {datos_mercado['rsi']}
- MACD: {datos_mercado['macd']}
- Señal MACD: {datos_mercado['macd_sig']}
- MA20: ${datos_mercado['ma20']:,.2f}
- MA50: ${datos_mercado['ma50']:,.2f}
- MA200: ${datos_mercado['ma200']:,.2f}
- Señal detectada por el bot: {datos_mercado['senal_bot']}

Responde en este formato EXACTO (no agregues nada más):

DECISION: [COMPRA / VENTA / ESPERAR]
CONFIANZA: [ALTA / MEDIA / BAJA]
RAZON: [Una sola oración explicando por qué]
RIESGO: [ALTO / MEDIO / BAJO]
CONSEJO: [Un consejo práctico de máximo 15 palabras]"""

    respuesta = cliente.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return respuesta.content[0].text


# ============================================================
# 3. PARSEAR RESPUESTA DE CLAUDE
# ============================================================
def parsear_respuesta(texto_claude):
    """
    Convierte la respuesta de texto de Claude
    en un diccionario estructurado para usar en el bot.
    """
    resultado = {
        "decision":  "ESPERAR",
        "confianza": "BAJA",
        "razon":     "Sin análisis disponible",
        "riesgo":    "ALTO",
        "consejo":   "Esperar mejor momento"
    }

    try:
        lineas = texto_claude.strip().split("\n")
        for linea in lineas:
            if linea.startswith("DECISION:"):
                resultado["decision"] = linea.replace("DECISION:", "").strip()
            elif linea.startswith("CONFIANZA:"):
                resultado["confianza"] = linea.replace("CONFIANZA:", "").strip()
            elif linea.startswith("RAZON:"):
                resultado["razon"] = linea.replace("RAZON:", "").strip()
            elif linea.startswith("RIESGO:"):
                resultado["riesgo"] = linea.replace("RIESGO:", "").strip()
            elif linea.startswith("CONSEJO:"):
                resultado["consejo"] = linea.replace("CONSEJO:", "").strip()
    except Exception as e:
        print(f"Error parseando respuesta de Claude: {e}")

    return resultado


# ============================================================
# 4. FUNCIÓN PRINCIPAL — Análisis completo
# ============================================================
def obtener_analisis(senal_bot, df):
    """
    Función principal que el bot llama para obtener
    el análisis de Claude.

    Recibe:
        senal_bot → diccionario con la señal del bot
        df        → DataFrame con los datos de mercado

    Retorna:
        diccionario con la decisión razonada de Claude
    """
    ultima = df.iloc[-1]
    anterior = df.iloc[-2]

    # Preparar datos para Claude
    datos = {
        "simbolo":   senal_bot["simbolo"],
        "precio":    senal_bot["precio"],
        "rsi":       senal_bot["rsi"],
        "macd":      round(ultima["MACD"], 4),
        "macd_sig":  round(ultima["MACD_sig"], 4),
        "ma20":      round(ultima["MA20"], 2),
        "ma50":      round(ultima["MA50"], 2),
        "ma200":     round(ultima["MA200"], 2),
        "tendencia": senal_bot["tendencia"],
        "senal_bot": senal_bot["tipo"]
    }

    # Obtener análisis de Claude
    texto_respuesta = analizar_con_claude(datos)

    # Parsear y retornar
    analisis = parsear_respuesta(texto_respuesta)

    return analisis


# ============================================================
# 5. CONSTRUIR MENSAJE ENRIQUECIDO PARA TELEGRAM
# ============================================================
def construir_mensaje_claude(senal_bot, analisis, riesgo):
    """
    Construye el mensaje final de Telegram que combina:
    - Los datos del bot (precio, RSI, etc.)
    - El análisis razonado de Claude
    - La gestión de riesgo
    """
    simbolo  = senal_bot["simbolo"]
    precio   = senal_bot["precio"]
    rsi      = senal_bot["rsi"]
    tendencia = senal_bot["tendencia"]

    # Emoji según decisión
    if analisis["decision"] == "COMPRA":
        emoji = "[COMPRA]"
    elif analisis["decision"] == "VENTA":
        emoji = "[VENTA]"
    else:
        emoji = "[ESPERAR]"

    mensaje = (
        f"{emoji} ANALISIS DE CLAUDE\n"
        f"{'='*32}\n"
        f"Activo:      {simbolo}\n"
        f"Precio:      ${precio:,.2f}\n"
        f"Tendencia:   {tendencia}\n"
        f"{'='*32}\n"
        f"DECISION DE CLAUDE\n"
        f"Decision:    {analisis['decision']}\n"
        f"Confianza:   {analisis['confianza']}\n"
        f"Riesgo:      {analisis['riesgo']}\n"
        f"Razon:       {analisis['razon']}\n"
        f"Consejo:     {analisis['consejo']}\n"
        f"{'='*32}\n"
        f"INDICADORES\n"
        f"RSI:         {rsi}\n"
        f"{'='*32}\n"
    )

    # Agregar gestión de riesgo si hay señal accionable
    if riesgo and analisis["decision"] in ["COMPRA", "VENTA"]:
        mensaje += (
            f"GESTION DE RIESGO\n"
            f"Capital:     ${riesgo['capital_a_usar']}\n"
            f"Stop-Loss:   ${riesgo['stop_loss']:,.2f}\n"
            f"Take-Profit: ${riesgo['take_profit']:,.2f}\n"
            f"Max perdida: ${riesgo['perdida_maxima']}\n"
            f"Ganancia esp:${riesgo['ganancia_esperada']}\n"
            f"Ratio:       {riesgo['ratio']}\n"
            f"{'='*32}\n"
        )

    mensaje += "PAPER TRADING - Solo educativo"

    return mensaje


# ============================================================
# 6. TEST — Verificar que Claude responde correctamente
# ============================================================
if __name__ == "__main__":
    print("Probando conexion con Claude...")
    print("=" * 40)

    # Datos de prueba
    datos_prueba = {
        "simbolo":   "BTC/USDT",
        "precio":    67310.57,
        "rsi":       29.5,
        "macd":      -125.4,
        "macd_sig":  -98.2,
        "ma20":      68200.0,
        "ma50":      69100.0,
        "ma200":     68500.0,
        "tendencia": "ALCISTA",
        "senal_bot": "COMPRA"
    }

    print(f"Enviando datos de prueba a Claude:")
    print(f"  Activo: {datos_prueba['simbolo']}")
    print(f"  Precio: ${datos_prueba['precio']:,.2f}")
    print(f"  RSI:    {datos_prueba['rsi']}")
    print(f"  Señal bot: {datos_prueba['senal_bot']}")
    print("=" * 40)

    respuesta_raw = analizar_con_claude(datos_prueba)
    print("Respuesta de Claude:")
    print(respuesta_raw)
    print("=" * 40)

    analisis = parsear_respuesta(respuesta_raw)
    print("Analisis parseado:")
    for clave, valor in analisis.items():
        print(f"  {clave}: {valor}")
    print("=" * 40)
    print("Conexion con Claude exitosa!")