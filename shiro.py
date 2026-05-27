# shiro.py
import os
import time
import requests
import pandas as pd
from datetime import datetime
from ta.momentum import RSIIndicator
from ta.trend import MACD
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# ========== CONFIGURACIÓN DE SHIRO ==========
NOMBRE_BOT = "🦈 SHIRO"
VERSION = "1.0"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Mis Criptos")
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME", "Portafolio")

# ========== TELEGRAM ==========
def enviar_telegram(mensaje):
    """Shiro envía alerta a Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🦈 *SHIRO BOT*\n\n{mensaje}",
            "parse_mode": "Markdown"
        }, timeout=5)
        print("📱 Shiro envió alerta a Telegram")
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

# ========== GOOGLE SHEETS ==========
def obtener_portafolio():
    """Shiro lee tus monedas desde Google Sheets"""
    try:
        # Render necesita la variable de entorno GOOGLE_CREDENTIALS_JSON
        if os.getenv("GOOGLE_CREDENTIALS_JSON"):
            import json
            creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
            from oauth2client.service_account import ServiceAccountCredentials
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
        else:
            # Local: usa el archivo
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet(GOOGLE_WORKSHEET_NAME)
        data = sheet.get_all_records()
        
        portafolio = {}
        for row in data:
            moneda = str(row.get('Moneda', '')).strip().lower()
            cantidad = row.get('Cantidad', 0)
            if moneda and cantidad > 0:
                portafolio[moneda] = float(cantidad)
        
        print(f"🦈 Shiro cargó {len(portafolio)} monedas")
        return portafolio
    except Exception as e:
        print(f"❌ Error Google Sheets: {e}")
        return {}

# ========== ANÁLISIS TÉCNICO ==========
def analizar_moneda(symbol, cantidad):
    """Shiro analiza una moneda con RSI + MACD"""
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol.upper()}USDT&interval=1h&limit=100'
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if 'code' in data or not isinstance(data, list):
            raise Exception(f"Moneda {symbol} no encontrada")
        
        df = pd.DataFrame(data, columns=['time','open','high','low','close','volume','close_time','quote_asset_volume','trades','taker_buy_base','taker_buy_quote','ignore'])
        df['close'] = df['close'].astype(float)
        
        if len(df) < 30:
            raise Exception("Datos insuficientes")
        
        rsi = RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]
        macd = MACD(close=df['close'])
        macd_line = macd.macd().iloc[-1]
        signal_line = macd.macd_signal().iloc[-1]
        precio_actual = df['close'].iloc[-1]
        valor_total = cantidad * precio_actual
        
        # Lógica de decisión
        if rsi > 80:
            decision = "🔴 VENDER YA"
            razon = f"RSI extremo ({rsi:.1f})"
            alerta = True
        elif rsi > 70 and macd_line < signal_line:
            decision = "🔴 VENDER"
            razon = f"RSI {rsi:.1f} + MACD bajista"
            alerta = True
        elif macd_line < signal_line and rsi > 60:
            decision = "🟡 VENDER PARCIAL"
            razon = f"MACD bajista + RSI {rsi:.1f}"
            alerta = True
        else:
            decision = "⚪ ESPERAR"
            razon = f"RSI {rsi:.1f}"
            alerta = False
        
        if alerta:
            mensaje = f"""🚨 *ALERTA DE VENTA*

📊 *Moneda:* {symbol.upper()}
🎯 *Decisión:* {decision}
💰 *Cantidad:* {cantidad}
💵 *Valor:* ${valor_total:,.2f}
📈 *Precio:* ${precio_actual:.8f}
📉 *RSI:* {rsi:.1f}

🔍 *Motivo:* {razon}
⏰ *Hora:* {datetime.now().strftime('%H:%M %d/%m/%Y')}"""
            enviar_telegram(mensaje)
        
        return {
            "moneda": symbol.upper(),
            "valor_usdt": round(valor_total, 2),
            "rsi": round(rsi, 1),
            "decision": decision,
            "alerta": alerta
        }
        
    except Exception as e:
        return {"moneda": symbol.upper(), "error": str(e), "decision": "❌ ERROR"}

# ========== BIENVENIDA ==========
def mostrar_bienvenida():
    print("""
    ╔══════════════════════════════════════╗
    ║      🦈  SHIRO BOT v1.0  🦈         ║
    ║   Analizador de Criptomonedas       ║
    ║   "El tiburón del mercado"          ║
    ╚══════════════════════════════════════╝
    """)

# ========== EJECUCIÓN PRINCIPAL ==========
def main():
    mostrar_bienvenida()
    
    portafolio = obtener_portafolio()
    if not portafolio:
        print("❌ Shiro no encontró monedas")
        return
    
    print(f"📊 Monedas: {', '.join(portafolio.keys())}")
    print("-" * 40)
    
    for moneda, cantidad in portafolio.items():
        print(f"🔍 Analizando {moneda.upper()}...")
        resultado = analizar_moneda(moneda, cantidad)
        time.sleep(1)
    
    print("\n✅ Shiro ha terminado el análisis")

if __name__ == "__main__":
    main()