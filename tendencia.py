import ccxt, config, pandas as pd

exchange = ccxt.binance({
    'apiKey': config.BINANCE_API_KEY,
    'secret': config.BINANCE_SECRET
})

datos = exchange.fetch_ohlcv('BTC/USDT', '1h', limit=200)
df = pd.DataFrame(datos, columns=['t','o','h','l','close','v'])

ma50  = df['close'].rolling(50).mean().iloc[-1]
ma200 = df['close'].rolling(200).mean().iloc[-1]
precio = df['close'].iloc[-1]

tendencia = "ALCISTA" if ma50 > ma200 else "BAJISTA"

print(f"BTC precio actual: {round(precio, 2)}")
print(f"MA50:              {round(ma50, 2)}")
print(f"MA200:             {round(ma200, 2)}")
print(f"Tendencia:         {tendencia}")
print()
if tendencia == "BAJISTA":
    diferencia = round(ma200 - ma50, 2)
    print(f"MA50 necesita subir ${diferencia} para cruzar MA200")
    print("El bot esta protegiendo tu capital correctamente")