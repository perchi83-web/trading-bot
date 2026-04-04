import agente_ia

# Simulamos una señal falsa para ver si la IA responde
senal_prueba = {
    'tipo': 'COMPRA',
    'simbolo': 'BTC/USDT',
    'precio': 65000,
    'rsi': 35,
    'tendencia': 'ALCISTA'
}

print("--- Consultando a Gemini, espera un momento... ---")

# Llamamos a la función que creamos en el archivo anterior
respuesta = agente_ia.obtener_analisis_ia(senal_prueba)

print("\nRESPUESTA DE LA IA:")
print(respuesta)