# 🤖 Bot de Alertas de Trading con IA
## Guía completa de instalación y configuración

---

## 📁 Estructura del proyecto

```
trading_bot/
│
├── config.py              ← Variables de configuración (API keys, etc.)
├── bot.py                 ← Código principal del agente
├── historial_senales.csv  ← Se crea automáticamente al correr
└── registro_bot.log       ← Se crea automáticamente al correr
```

---

## ⚙️ Paso 1: Instalar dependencias

Abre una terminal y ejecuta:

```bash
pip install ccxt pandas pandas_ta requests apscheduler
```

---

## 📱 Paso 2: Crear tu bot de Telegram

1. Abre Telegram y busca **@BotFather**
2. Escribe `/newbot`
3. Dale un nombre (ej: "Mi Bot de Trading")
4. Dale un username (ej: `mi_trading_bot`)
5. BotFather te dará un **TOKEN** → cópialo en `config.py`

**Para obtener tu CHAT_ID:**
1. Busca **@userinfobot** en Telegram
2. Escríbele `/start`
3. Te responderá con tu ID → cópialo en `config.py`

---

## 🔑 Paso 3: Crear API Key en Binance (solo lectura)

1. Entra a **binance.com** → Perfil → API Management
2. Crea una nueva API Key
3. **IMPORTANTE**: Desmarca todas las opciones excepto "Enable Reading"
4. Copia el API Key y Secret en `config.py`

> ⚠️ Nunca actives "Enable Spot & Margin Trading" para este bot de prueba

---

## 🚀 Paso 4: Correr el bot

```bash
python bot.py
```

Verás algo así en la consola:

```
2025-03-07 10:00:00 | INFO | 🚀 Bot de alertas de trading iniciado
2025-03-07 10:00:00 | INFO |    Monitoreando: BTC/USDT
2025-03-07 10:00:00 | INFO |    Intervalo de velas: 15m
2025-03-07 10:00:01 | INFO | ✅ Conectado al exchange correctamente
2025-03-07 10:00:02 | INFO | 📊 100 velas obtenidas para BTC/USDT (15m)
2025-03-07 10:00:02 | INFO | 📐 Indicadores calculados correctamente
2025-03-07 10:00:02 | INFO | 🎯 Señal detectada: NEUTRAL | Precio: $84,200 | RSI: 52.3
```

---

## 📊 Lo que el bot analiza: RSI explicado

```
RSI < 30  →  🟢 POSIBLE COMPRA
              El precio cayó mucho, puede rebotar

RSI 30-70 →  ⚪ NEUTRAL
              El mercado está en zona normal

RSI > 70  →  🔴 POSIBLE VENTA
              El precio subió mucho, puede corregir
```

---

## 📱 Ejemplo de alerta en Telegram

```
🟢 ALERTA DE TRADING
━━━━━━━━━━━━━━━━━━
📌 Par: BTC/USDT
💰 Precio: $82,450.00
📊 RSI (14): 27.5
🎯 Señal: COMPRA
📝 Razón: RSI en 27.5 — activo sobrevendido, posible rebote al alza
🕐 Hora: 2025-03-07 14:30
━━━━━━━━━━━━━━━━━━
⚠️ Esto es educativo, no consejo financiero
```

---

## 📈 Analizar resultados después

El bot guarda cada señal en `historial_senales.csv`:

| fecha | simbolo | precio | rsi | senal |
|-------|---------|--------|-----|-------|
| 2025-03-07 10:00 | BTC/USDT | 84200 | 27.5 | COMPRA |
| 2025-03-07 10:15 | BTC/USDT | 84850 | 35.2 | NEUTRAL |

Esto te permite evaluar **qué tan buenas fueron las señales** con el tiempo.

---

## 🔮 Próximos pasos (cuando domines esto)

- [ ] Añadir más indicadores (MACD, Bollinger Bands)
- [ ] Añadir múltiples pares (ETH, SOL, etc.)
- [ ] Integrar IA con CrewAI para análisis más profundo
- [ ] Añadir análisis de noticias de cripto
- [ ] Conectar con agente que ejecute órdenes (solo cuando entiendas el riesgo)

---

## ⚠️ Aviso importante

Este bot es **educativo**. Las señales de RSI son básicas y no garantizan ganancias.
El trading conlleva riesgo de pérdida de capital. Usa siempre paper trading primero.
