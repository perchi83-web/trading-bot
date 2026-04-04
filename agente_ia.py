from google import genai
import config
import logging

log = logging.getLogger(__name__)

# En 2026, el cliente necesita especificar que usamos la API de Google AI Studio
client = genai.Client(api_key=config.GEMINI_API_KEY)

def obtener_analisis_ia(senal):
    """
    Versión 2026 optimizada para Gemini 2.0 Flash.
    """
    prompt = f"""
    Hola Gemini, analiza esta señal de trading para Marvin:
    Activo: {senal['simbolo']}
    Operación: {senal['tipo']}
    Precio: ${senal['precio']}
    RSI: {senal['rsi']}
    Tendencia: {senal['tendencia']}
    
    Responde en español (máximo 3 líneas):
    1. Veredicto (SÍ/NO)
    2. Razón técnica.
    """

    try:
        # Cambiamos a gemini-2.0-flash que es el estándar actual
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt
        )
        return response.text
    except Exception as e:
        log.error(f"Error al hablar con la IA: {e}")
        # Si el 2.0 falla por algo, intentamos con el nombre genérico
        return "Error de conexión con el cerebro de IA."