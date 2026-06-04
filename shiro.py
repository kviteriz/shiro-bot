# shiro.py - Shiro Bot v3.0 - CON LOGS DE DEPURACIÓN
# Configuración: RSI compra <45, RSI venta >55, alerta con 1 señal

import os
import time
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO

load_dotenv()

print("🔧 SHIRO BOT INICIANDO - MODO DEPURACIÓN ACTIVADO")

# ========== CONFIGURACIÓN ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

VENTAS_SHEET_NAME = os.getenv("VENTAS_SHEET_NAME", "Mis Criptos")
COMPRAS_SHEET_NAME = os.getenv("COMPRAS_SHEET_NAME", "Mis Compras")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Portafolio")
HISTORIAL_SHEET_NAME = os.getenv("HISTORIAL_SHEET_NAME", "Historial Shiro")

# Configuración de trading
CAPITAL_TOTAL = float(os.getenv("CAPITAL_TOTAL", "5000"))
RIESGO_POR_OPERACION = float(os.getenv("RIESGO_POR_OPERACION", "2"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "15"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "8"))
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "5"))
DIVERSIFICACION_MAX = float(os.getenv("DIVERSIFICACION_MAX", "20"))

print(f"📊 Configuración cargada: CAPITAL_TOTAL={CAPITAL_TOTAL}")

# ========== CONFIGURACIÓN DE SEÑALES ==========
CONFIG_SEÑALES = {
    "rsi_compra": 45,
    "rsi_venta": 55,
    "min_señales_compra": 1,
    "min_señales_venta": 1,
    "volumen_factor": 1.2,
    "bb_alta_volatilidad": 0.1,
}

print(f"🎯 Señales: RSI compra <{CONFIG_SEÑALES['rsi_compra']} | RSI venta >{CONFIG_SEÑALES['rsi_venta']}")

# ========== MAPEO COINGECKO ==========
MAPEO_COINGECKO = {
    'btc': 'bitcoin', 'eth': 'ethereum', 'sol': 'solana', 'sui': 'sui',
    'hbar': 'hedera-hashgraph', 'doge': 'dogecoin', 'pepe': 'pepe',
    'ray': 'raydium', 'joe': 'joe', 'jup': 'jupiter', 'ondo': 'ondo-finance',
    'pyth': 'pyth-network', 'cetus': 'cetus-protocol', 'aero': 'aerodrome-finance',
    'deep': 'deep', 'cpool': 'clearpool', 'rhea': 'rhea', 'sauce': 'sauce',
    'aster': 'aster', 'met': 'meteora', 'plume': 'plume', 'meteora': 'meteora',
}

# ========== VARIABLES GLOBALES ==========
historial_señales = []
portafolio_actual = {}
precios_maximos = {}

# ========== TELEGRAM ==========
def enviar_telegram(mensaje, foto=None):
    print(f"📱 Intentando enviar mensaje a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        if foto:
            url_foto = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            requests.post(url_foto, data={"chat_id": TELEGRAM_CHAT_ID, "caption": mensaje}, files={"photo": foto})
            print("📱 Foto enviada a Telegram")
        else:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🦈 *SHIRO BOT*\n\n{mensaje}", "parse_mode": "Markdown"}, timeout=15)
            print("📱 Mensaje enviado a Telegram")
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

# ========== GOOGLE SHEETS ==========
def conectar_google_sheets():
    print("🔌 Conectando a Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    if os.getenv("GOOGLE_CREDENTIALS_JSON"):
        import json
        creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        print("✅ Conectado con credenciales desde variable de entorno")
    else:
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        print("✅ Conectado con archivo credentials.json")
    
    client = gspread.authorize(creds)
    return client

def leer_portafolio(sheet_name):
    print(f"📊 Leyendo portafolio desde {sheet_name}...")
    try:
        client = conectar_google_sheets()
        sheet = client.open(sheet_name).worksheet(WORKSHEET_NAME)
        data = sheet.get_all_records()
        
        portafolio = {}
        for row in data:
            moneda = str(row.get('Moneda', '')).strip().lower()
            cantidad = row.get('Cantidad', 0)
            if moneda and cantidad > 0:
                portafolio[moneda] = float(cantidad)
        
        print(f"  ✅ Cargadas {len(portafolio)} monedas: {list(portafolio.keys())}")
        return portafolio
    except Exception as e:
        print(f"  ❌ Error leyendo {sheet_name}: {e}")
        return {}

# ========== OBTENER DATOS ==========
def obtener_velas(symbol, timeframe="1h", limit=100):
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol.upper()}USDT&interval={timeframe}&limit={limit}'
        response = requests.get(url, timeout=10)
        data = response.json()
        if 'code' in data or not isinstance(data, list):
            return None
        df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qa_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return df
    except Exception as e:
        print(f"    ❌ Error obteniendo velas de {symbol}: {e}")
        return None

# ========== INDICADORES TÉCNICOS ==========
def calcular_rsi(df, period=14):
    return RSIIndicator(close=df['close'], window=period).rsi().iloc[-1]

def calcular_volumen_anormal(df, factor=None):
    if factor is None:
        factor = CONFIG_SEÑALES["volumen_factor"]
    vol_promedio = df['volume'].tail(20).mean()
    vol_actual = df['volume'].iloc[-1]
    return vol_actual > vol_promedio * factor, vol_actual / vol_promedio if vol_promedio > 0 else 1

def calcular_soporte_resistencia(df, window=20):
    high = df['high'].tail(window).max()
    low = df['low'].tail(window).min()
    precio_actual = df['close'].iloc[-1]
    cerca_resistencia = (high - precio_actual) / high < 0.02
    cerca_soporte = (precio_actual - low) / precio_actual < 0.02
    return high, low, cerca_resistencia, cerca_soporte

# ========== ANÁLISIS AVANZADO CON LOGS ==========
def analisis_avanzado(symbol, cantidad, modo="venta"):
    print(f"    🔍 Analizando {symbol.upper()} ({modo})...")
    
    resultados = {}
    señales_compra = 0
    señales_venta = 0
    
    # Obtener datos
    df_1h = obtener_velas(symbol, "1h", 100)
    if df_1h is None or len(df_1h) < 50:
        print(f"    ❌ Datos insuficientes para {symbol}")
        return None
    
    rsi_1h = calcular_rsi(df_1h)
    precio_actual = df_1h['close'].iloc[-1]
    valor_total = cantidad * precio_actual
    volumen_anormal, ratio_volumen = calcular_volumen_anormal(df_1h)
    soporte, resistencia, cerca_soporte, cerca_resistencia = calcular_soporte_resistencia(df_1h)
    
    print(f"    📊 RSI: {rsi_1h:.1f} | Precio: ${precio_actual:.4f} | Volumen: {ratio_volumen:.1f}x")
    
    # Acumular señales
    if modo == "compra":
        if rsi_1h < CONFIG_SEÑALES["rsi_compra"]:
            señales_compra += 1
            print(f"    ✅ Señal: RSI bajo ({rsi_1h:.1f} < {CONFIG_SEÑALES['rsi_compra']})")
        if cerca_soporte:
            señales_compra += 1
            print(f"    ✅ Señal: Cerca de soporte (${soporte:.4f})")
        if volumen_anormal:
            señales_compra += 1
            print(f"    ✅ Señal: Volumen anormal ({ratio_volumen:.1f}x)")
        
        print(f"    📊 Total señales COMPRA: {señales_compra}")
        
        if señales_compra >= CONFIG_SEÑALES["min_señales_compra"]:
            print(f"    🎯 *** CONDICIÓN DE COMPRA ACTIVADA! Señales: {señales_compra} ***")
            decision = "🟢 COMPRAR"
            razon = f"{señales_compra} indicadores positivos"
            alerta = True
        else:
            print(f"    ⚪ Condición NO activada (necesita {CONFIG_SEÑALES['min_señales_compra']} señal, tiene {señales_compra})")
            decision = "⚪ ESPERAR"
            razon = "Sin señales suficientes"
            alerta = False
    else:
        # Modo venta
        if rsi_1h > CONFIG_SEÑALES["rsi_venta"]:
            señales_venta += 1
        if cerca_resistencia:
            señales_venta += 1
        if volumen_anormal:
            señales_venta += 1
        
        if señales_venta >= CONFIG_SEÑALES["min_señales_venta"]:
            decision = "🔴 VENDER"
            razon = f"{señales_venta} indicadores negativos"
            alerta = True
        else:
            decision = "⚪ ESPERAR"
            razon = "Sin señales de venta"
            alerta = False
    
    # Take profit / Stop loss
    take_profit = precio_actual * (1 + TAKE_PROFIT_PCT / 100)
    stop_loss = precio_actual * (1 - STOP_LOSS_PCT / 100)
    
    return {
        "moneda": symbol.upper(),
        "precio": round(precio_actual, 8),
        "valor_usdt": round(valor_total, 2),
        "rsi": round(rsi_1h, 1),
        "decision": decision,
        "razon": razon,
        "alerta": alerta,
        "señales_compra": señales_compra,
        "señales_venta": señales_venta,
        "take_profit": round(take_profit, 8),
        "stop_loss": round(stop_loss, 8),
        "modo": modo,
        "fuente": "Binance"
    }

# ========== GENERAR GRÁFICO ==========
def generar_grafico(symbol, df, analisis):
    try:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
        
        ax1.plot(df['time'], df['close'], label='Precio', color='blue', linewidth=1)
        ax1.set_title(f'{symbol.upper()} - Análisis Técnico', fontsize=14)
        ax1.set_ylabel('Precio USDT')
        
        ax2.plot(df['time'], rsi, label='RSI', color='purple', linewidth=1)
        ax2.axhline(y=70, color='red', linestyle='--', alpha=0.5, label='Sobrecompra (70)')
        ax2.axhline(y=30, color='green', linestyle='--', alpha=0.5, label='Sobreventa (30)')
        ax2.axhline(y=CONFIG_SEÑALES["rsi_compra"], color='orange', linestyle=':', alpha=0.5, label=f'Compra ({CONFIG_SEÑALES["rsi_compra"]})')
        ax2.axhline(y=CONFIG_SEÑALES["rsi_venta"], color='orange', linestyle=':', alpha=0.5, label=f'Venta ({CONFIG_SEÑALES["rsi_venta"]})')
        ax2.set_ylabel('RSI')
        ax2.set_xlabel('Fecha')
        ax2.legend(loc='upper left')
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 100)
        
        plt.tight_layout()
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        print(f"⚠️ Error generando gráfico: {e}")
        return None

# ========== PROCESAR LISTA ==========
def procesar_lista(portafolio, modo):
    global historial_señales, portafolio_actual
    
    resultados = []
    for moneda, cantidad in portafolio.items():
        print(f"\n🔍 Analizando {moneda.upper()} ({modo})...")
        
        if moneda in MAPEO_COINGECKO:
            resultado = analisis_avanzado(moneda, cantidad, modo)
        else:
            print(f"  ❌ Moneda {moneda} no está en el mapeo de CoinGecko")
            resultado = None
        
        if resultado:
            print(f"  📊 Resultado: {resultado['decision']} | Alerta: {resultado['alerta']}")
            resultados.append(resultado)
            portafolio_actual[resultado['moneda']] = resultado['valor_usdt']
            
            if resultado['alerta']:
                print(f"  🚨 ¡ALERTA GENERADA para {moneda.upper()}!")
                historial_señales.append({
                    "timestamp": datetime.now(),
                    "moneda": resultado['moneda'],
                    "decision": resultado['decision'],
                    "rsi": resultado['rsi']
                })
                
                # Gráfico
                df = obtener_velas(moneda, "1h", 100)
                if df is not None:
                    grafico = generar_grafico(moneda, df, resultado)
                else:
                    grafico = None
                
                mensaje = f"""💰 OPORTUNIDAD DE {'COMPRA' if 'COMPRA' in resultado['decision'] else 'VENTA'}

📊 *Moneda:* {resultado['moneda']}
🎯 *Decisión:* {resultado['decision']}
📉 *RSI:* {resultado['rsi']}
📈 *Precio:* ${resultado['precio']:.4f}
💰 *Valor:* ${resultado['valor_usdt']:.2f}
📈 *Take Profit:* ${resultado['take_profit']:.4f}
📉 *Stop Loss:* ${resultado['stop_loss']:.4f}
🎯 *Señales:* {resultado.get('señales_compra', resultado.get('señales_venta', 0))} indicadores

🔍 *Motivo:* {resultado['razon']}
⏰ *Hora:* {datetime.now().strftime('%H:%M %d/%m/%Y')}"""
                enviar_telegram(mensaje, grafico)
            else:
                print(f"  🔕 No se generó alerta para {moneda.upper()}")
        else:
            print(f"  ❌ Análisis falló para {moneda.upper()}")
            resultados.append({"moneda": moneda.upper(), "decision": "❌ ERROR", "alerta": False})
        
        time.sleep(2)
    
    return resultados

# ========== REPORTE DIARIO ==========
def enviar_reporte_diario():
    global historial_señales
    if not historial_señales:
        enviar_telegram("📊 *REPORTE DIARIO*\n\nNo hubo señales en las últimas 24 horas.")
        return
    
    mensaje = "📊 *REPORTE DIARIO SHIRO*\n\n"
    mensaje += f"🔔 *Señales hoy:* {len(historial_señales)}\n\n"
    
    for señal in historial_señales[-10:]:
        mensaje += f"• {señal['moneda']}: {señal['decision']} (RSI {señal['rsi']})\n"
    
    enviar_telegram(mensaje)

# ========== MAIN ==========
def main():
    print("""
    ╔══════════════════════════════════════╗
    ║      🦈  SHIRO BOT v3.0  🦈         ║
    ║   Análisis Profesional de Trading   ║
    ║   "El tiburón del mercado"          ║
    ║   MODO DEPURACIÓN ACTIVADO          ║
    ╚══════════════════════════════════════╝
    """)
    
    print(f"📊 Capital total: ${CAPITAL_TOTAL} | Riesgo: {RIESGO_POR_OPERACION}%")
    print(f"📈 Take Profit: {TAKE_PROFIT_PCT}% | Stop Loss: {STOP_LOSS_PCT}%")
    
    print("\n📊 Cargando monedas para VENTA...")
    ventas = leer_portafolio(VENTAS_SHEET_NAME)
    if ventas:
        procesar_lista(ventas, "venta")
    
    print("\n📊 Cargando monedas para COMPRA...")
    compras = leer_portafolio(COMPRAS_SHEET_NAME)
    if compras:
        procesar_lista(compras, "compra")
    
    enviar_reporte_diario()
    
    print("\n✅ Shiro v3.0 ha terminado el análisis")

if __name__ == "__main__":
    main()