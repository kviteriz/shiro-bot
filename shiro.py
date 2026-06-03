# shiro.py - Shiro Bot v3.0
# Mejoras: Múltiples timeframes, Bollinger Bands, Volumen anormal,
# Soporte/Resistencia, Confirmación múltiple, Take profit/Stop loss,
# Trailing stop, Diversificación, Reporte diario, Gráficos, Comandos, Correlación BTC

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
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO

load_dotenv()

# ========== CONFIGURACIÓN ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

VENTAS_SHEET_NAME = os.getenv("VENTAS_SHEET_NAME", "Mis Criptos")
COMPRAS_SHEET_NAME = os.getenv("COMPRAS_SHEET_NAME", "Mis Compras")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Portafolio")
HISTORIAL_SHEET_NAME = os.getenv("HISTORIAL_SHEET_NAME", "Historial Shiro")

# Configuración de trading
CAPITAL_TOTAL = float(os.getenv("CAPITAL_TOTAL", "10000"))  # USD
RIESGO_POR_OPERACION = float(os.getenv("RIESGO_POR_OPERACION", "2"))  # 2%
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "15"))  # 15%
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "8"))  # 8%
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "5"))  # 5%
DIVERSIFICACION_MAX = float(os.getenv("DIVERSIFICACION_MAX", "20"))  # 20% por moneda

# ========== MAPEO COMPLETO DE COINGECKO ==========
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
precios_maximos = {}  # Para trailing stop

# ========== TELEGRAM ==========
def enviar_telegram(mensaje, foto=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        if foto:
            # Enviar foto
            url_foto = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            requests.post(url_foto, data={"chat_id": TELEGRAM_CHAT_ID, "caption": mensaje}, files={"photo": foto})
        else:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🦈 *SHIRO BOT*\n\n{mensaje}", "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

# ========== GOOGLE SHEETS ==========
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if os.getenv("GOOGLE_CREDENTIALS_JSON"):
        creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
        return ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

def leer_portafolio(sheet_name):
    try:
        creds = conectar_google_sheets()
        client = gspread.authorize(creds)
        sheet = client.open(sheet_name).worksheet(WORKSHEET_NAME)
        data = sheet.get_all_records()
        portafolio = {}
        for row in data:
            moneda = str(row.get('Moneda', '')).strip().lower()
            cantidad = row.get('Cantidad', 0)
            if moneda and cantidad > 0:
                portafolio[moneda] = float(cantidad)
        return portafolio
    except Exception as e:
        print(f"❌ Error leyendo {sheet_name}: {e}")
        return {}

def guardar_historico(moneda, decision, razon, rsi, precio, take_profit=None, stop_loss=None):
    try:
        creds = conectar_google_sheets()
        client = gspread.authorize(creds)
        try:
            sheet = client.open(HISTORIAL_SHEET_NAME).worksheet("Señales")
        except:
            # Crear si no existe
            workbook = client.open(HISTORIAL_SHEET_NAME)
            sheet = workbook.add_worksheet("Señales", 1000, 10)
            sheet.append_row(["Timestamp", "Moneda", "Decisión", "Razón", "RSI", "Precio", "Take Profit", "Stop Loss"])
        
        sheet.append_row([datetime.now().isoformat(), moneda, decision, razon, rsi, precio, take_profit or "", stop_loss or ""])
    except Exception as e:
        print(f"⚠️ No se pudo guardar histórico: {e}")

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
    except:
        return None

def obtener_precio_coingecko(gecko_id):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={gecko_id}&vs_currencies=usd"
        response = requests.get(url, timeout=10)
        data = response.json()
        return data.get(gecko_id, {}).get('usd', None)
    except:
        return None

# ========== INDICADORES TÉCNICOS ==========
def calcular_rsi(df, period=14):
    return RSIIndicator(close=df['close'], window=period).rsi().iloc[-1]

def calcular_macd(df):
    macd = MACD(close=df['close'])
    return macd.macd().iloc[-1], macd.macd_signal().iloc[-1]

def calcular_bollinger_bands(df, period=20, std=2):
    bb = BollingerBands(close=df['close'], window=period, window_dev=std)
    return bb.bollinger_hband().iloc[-1], bb.bollinger_lband().iloc[-1]

def calcular_volumen_anormal(df, factor=1.5):
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

def calcular_correlacion_btc(df_moneda, df_btc):
    if df_moneda is None or df_btc is None or len(df_moneda) < 30 or len(df_btc) < 30:
        return 0, "sin datos"
    ret_moneda = df_moneda['close'].pct_change().dropna()
    ret_btc = df_btc['close'].pct_change().dropna()
    min_len = min(len(ret_moneda), len(ret_btc))
    if min_len < 10:
        return 0, "sin datos"
    correlacion = ret_moneda.iloc[-min_len:].corr(ret_btc.iloc[-min_len:])
    if correlacion > 0.7:
        return correlacion, "alta correlación con BTC"
    elif correlacion < 0.3:
        return correlacion, "⚠️ baja correlación - se mueve independiente"
    return correlacion, "correlación normal"

# ========== GESTIÓN DE POSICIÓN ==========
def calcular_tamano_posicion(capital, riesgo_pct, precio, stop_loss_pct):
    riesgo_por_operacion = capital * (riesgo_pct / 100)
    stop_loss_price = precio * (1 - stop_loss_pct / 100)
    cantidad = riesgo_por_operacion / (precio - stop_loss_price) if (precio - stop_loss_price) > 0 else 0
    return cantidad, stop_loss_price

def calcular_take_profit(precio, take_profit_pct):
    return precio * (1 + take_profit_pct / 100)

def calcular_trailing_stop(precio_actual, maximo_anterior, trailing_pct):
    stop_loss = maximo_anterior * (1 - trailing_pct / 100)
    return stop_loss, precio_actual <= stop_loss

def verificar_diversificacion(portafolio, nueva_moneda, precio, cantidad):
    valor_nuevo = precio * cantidad
    valor_total = sum(portafolio.values()) + valor_nuevo
    if valor_total == 0:
        return True, 0
    porcentaje = (valor_nuevo / valor_total) * 100
    return porcentaje <= DIVERSIFICACION_MAX, porcentaje

# ========== ANÁLISIS AVANZADO ==========
def analisis_avanzado(symbol, cantidad, modo="venta"):
    resultados = {}
    señales_compra = 0
    señales_venta = 0
    
    # 1. Múltiples timeframes
    timeframes = {"1h": 1, "4h": 2, "1d": 3}
    rsis = {}
    for tf in timeframes:
        df = obtener_velas(symbol, tf)
        if df is not None and len(df) > 30:
            rsis[tf] = calcular_rsi(df)
            resultados[f"rsi_{tf}"] = rsis[tf]
            
            if modo == "compra":
                if rsis[tf] < 30:
                    señales_compra += timeframes[tf]
                elif rsis[tf] < 45:
                    pass
            else:
                if rsis[tf] > 70:
                    señales_venta += timeframes[tf]
    
    # Usar timeframe 1h para indicadores adicionales
    df_1h = obtener_velas(symbol, "1h", 100)
    if df_1h is None or len(df_1h) < 50:
        return None
    
    rsi_1h = calcular_rsi(df_1h)
    macd_line, signal_line = calcular_macd(df_1h)
    bb_upper, bb_lower = calcular_bollinger_bands(df_1h)
    precio_actual = df_1h['close'].iloc[-1]
    valor_total = cantidad * precio_actual
    volumen_anormal, ratio_volumen = calcular_volumen_anormal(df_1h)
    soporte, resistencia, cerca_soporte, cerca_resistencia = calcular_soporte_resistencia(df_1h)
    
    # 2. Bollinger Bands
    bb_ancho = (bb_upper - bb_lower) / precio_actual
    if bb_ancho > 0.1:
        resultados["bb_alta_volatilidad"] = True
        print(f"  📊 Bollinger Bands: alta volatilidad ({bb_ancho:.1%})")
    
    # 3. Volumen anormal
    if volumen_anormal:
        señales_compra += 1 if modo == "compra" else 0
        señales_venta += 1 if modo == "venta" else 0
        print(f"  📊 Volumen {ratio_volumen:.1f}x promedio - inusual")
    
    # 4. Soporte/Resistencia
    if cerca_soporte:
        señales_compra += 1
        print(f"  📊 Precio cerca de soporte (${soporte:.4f})")
    if cerca_resistencia:
        señales_venta += 1
        print(f"  📊 Precio cerca de resistencia (${resistencia:.4f})")
    
    # 5. Correlación con BTC
    df_btc = obtener_velas("btc", "1h", 50)
    correlacion, msg_corr = calcular_correlacion_btc(df_1h, df_btc)
    resultados["correlacion_btc"] = correlacion
    if correlacion < 0.3 and correlacion > 0:
        print(f"  📊 {msg_corr} (correl: {correlacion:.2f})")
    
    # 6. Confirmación múltiple
    if modo == "compra":
        if rsi_1h < 30: señales_compra += 1
        if precio_actual < bb_lower: señales_compra += 1
        if cerca_soporte: señales_compra += 1
        if volumen_anormal: señales_compra += 1
        
        if señales_compra >= 4:
            decision = "🔵 COMPRAR MUCHO"
            razon = f"Señal fuerte: {señales_compra} indicadores"
            alerta = True
        elif señales_compra >= 3:
            decision = "🟢 COMPRAR"
            razon = f"Señal moderada: {señales_compra} indicadores"
            alerta = True
        elif señales_compra >= 2:
            decision = "🟡 CONSIDERAR COMPRA"
            razon = f"Señal débil: {señales_compra} indicadores"
            alerta = False
        else:
            decision = "⚪ ESPERAR"
            razon = f"Sin señales claras"
            alerta = False
    else:
        if rsi_1h > 70: señales_venta += 1
        if precio_actual > bb_upper: señales_venta += 1
        if cerca_resistencia: señales_venta += 1
        
        if señales_venta >= 3:
            decision = "🔴 VENDER YA"
            razon = f"Señal fuerte de venta"
            alerta = True
        elif señales_venta >= 2:
            decision = "🟡 VENDER PARCIAL"
            razon = f"Señal moderada de venta"
            alerta = True
        else:
            decision = "⚪ ESPERAR"
            razon = f"Sin señales de venta"
            alerta = False
    
    # 7. Take profit / Stop loss
    take_profit = calcular_take_profit(precio_actual, TAKE_PROFIT_PCT)
    stop_loss = precio_actual * (1 - STOP_LOSS_PCT / 100)
    
    # 8. Trailing stop
    global precios_maximos
    if symbol not in precios_maximos:
        precios_maximos[symbol] = precio_actual
    else:
        precios_maximos[symbol] = max(precios_maximos[symbol], precio_actual)
    
    trailing_stop, activar_trailing = calcular_trailing_stop(precio_actual, precios_maximos[symbol], TRAILING_STOP_PCT)
    
    if activar_trailing and modo == "venta":
        decision = "🔴 ACTIVAR TRAILING STOP"
        razon = f"Stop loss dinámico en ${trailing_stop:.4f}"
        alerta = True
    
    # 9. Diversificación
    global portafolio_actual
    diversifica_ok, porcentaje = verificar_diversificacion(portafolio_actual, symbol, precio_actual, cantidad)
    if not diversifica_ok:
        print(f"  ⚠️ Excede límite de diversificación: {porcentaje:.1f}% > {DIVERSIFICACION_MAX}%")
    
    return {
        "moneda": symbol.upper(),
        "precio": round(precio_actual, 8),
        "valor_usdt": round(valor_total, 2),
        "rsi": round(rsi_1h, 1),
        "rsi_4h": round(rsis.get("4h", 0), 1) if "4h" in rsis else "N/A",
        "rsi_1d": round(rsis.get("1d", 0), 1) if "1d" in rsis else "N/A",
        "correlacion_btc": round(correlacion, 2) if correlacion else "N/A",
        "volumen_anormal": volumen_anormal,
        "ratio_volumen": round(ratio_volumen, 1),
        "soporte": round(soporte, 8),
        "resistencia": round(resistencia, 8),
        "take_profit": round(take_profit, 8),
        "stop_loss": round(stop_loss, 8),
        "trailing_stop": round(trailing_stop, 8),
        "decision": decision,
        "razon": razon,
        "alerta": alerta,
        "señales_compra": señales_compra,
        "señales_venta": señales_venta,
        "modo": modo,
        "fuente": "Binance"
    }

# ========== GENERAR GRÁFICO ==========
def generar_grafico(symbol, df, analisis):
    try:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})
        
        # Gráfico de precios
        ax1.plot(df['time'], df['close'], label='Precio', color='blue', linewidth=1)
        ax1.set_title(f'{symbol.upper()} - Análisis Técnico', fontsize=14)
        ax1.set_ylabel('Precio USDT')
        
        # Bollinger Bands
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        upper = bb.bollinger_hband()
        lower = bb.bollinger_lband()
        ax1.plot(df['time'], upper, label='Banda Superior', color='gray', linestyle='--', alpha=0.7)
        ax1.plot(df['time'], lower, label='Banda Inferior', color='gray', linestyle='--', alpha=0.7)
        
        # Soporte/Resistencia
        if analisis.get('soporte'):
            ax1.axhline(y=analisis['soporte'], color='green', linestyle='-', alpha=0.5, label=f"Soporte: ${analisis['soporte']:.4f}")
        if analisis.get('resistencia'):
            ax1.axhline(y=analisis['resistencia'], color='red', linestyle='-', alpha=0.5, label=f"Resistencia: ${analisis['resistencia']:.4f}")
        
        ax1.legend(loc='upper left')
        ax1.grid(True, alpha=0.3)
        
        # RSI
        rsi = RSIIndicator(close=df['close'], window=14).rsi()
        ax2.plot(df['time'], rsi, label='RSI', color='purple', linewidth=1)
        ax2.axhline(y=70, color='red', linestyle='--', alpha=0.5, label='Sobrecompra (70)')
        ax2.axhline(y=30, color='green', linestyle='--', alpha=0.5, label='Sobreventa (30)')
        ax2.set_ylabel('RSI')
        ax2.set_xlabel('Fecha')
        ax2.legend(loc='upper left')
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 100)
        
        plt.tight_layout()
        
        # Guardar en buffer
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        print(f"⚠️ Error generando gráfico: {e}")
        return None

# ========== COMANDOS INTERACTIVOS ==========
def comando_status():
    global portafolio_actual
    if not portafolio_actual:
        return "📊 *Portafolio vacío*\n\nAgrega monedas en Google Sheets"
    
    mensaje = "📊 *ESTADO DEL PORTAFOLIO*\n\n"
    valor_total = sum(portafolio_actual.values())
    
    for moneda, valor in sorted(portafolio_actual.items(), key=lambda x: x[1], reverse=True):
        porcentaje = (valor / valor_total * 100) if valor_total > 0 else 0
        mensaje += f"• *{moneda.upper()}*: ${valor:.2f} ({porcentaje:.1f}%)\n"
    
    mensaje += f"\n💰 *Capital total*: ${valor_total:.2f}"
    return mensaje

def comando_analizar(moneda, cantidad):
    resultado = analisis_avanzado(moneda, cantidad)
    if resultado:
        return f"""📊 *Análisis de {moneda.upper()}*

🎯 *Decisión:* {resultado['decision']}
📉 *RSI 1h/4h/1d:* {resultado['rsi']} / {resultado.get('rsi_4h', 'N/A')} / {resultado.get('rsi_1d', 'N/A')}
🔗 *Correlación BTC:* {resultado.get('correlacion_btc', 'N/A')}
💰 *Precio:* ${resultado['precio']:.4f}
📈 *Take Profit:* ${resultado.get('take_profit', 0):.4f}
📉 *Stop Loss:* ${resultado.get('stop_loss', 0):.4f}

🔍 *Motivo:* {resultado['razon']}"""
    return f"❌ No se pudo analizar {moneda}"

# ========== REPORTE DIARIO ==========
def enviar_reporte_diario():
    global historial_señales
    if not historial_señales:
        enviar_telegram("📊 *REPORTE DIARIO*\n\nNo hubo señales en las últimas 24 horas.")
        return
    
    mensaje = "📊 *REPORTE DIARIO SHIRO*\n\n"
    mensaje += f"🔔 *Señales hoy:* {len(historial_señales)}\n\n"
    
    for señal in historial_señales[-10:]:  # Últimas 10
        mensaje += f"• {señal['moneda']}: {señal['decision']} (RSI {señal['rsi']})\n"
    
    enviar_telegram(mensaje)

# ========== PROCESAR LISTA ==========
def procesar_lista(portafolio, modo):
    global historial_señales, portafolio_actual
    
    resultados = []
    for moneda, cantidad in portafolio.items():
        print(f"🔍 Analizando {moneda.upper()} ({modo})...")
        
        if moneda in MAPEO_COINGECKO:
            resultado = analisis_avanzado(moneda, cantidad, modo)
        else:
            resultado = None
        
        if resultado:
            resultados.append(resultado)
            portafolio_actual[resultado['moneda']] = resultado['valor_usdt']
            
            if resultado['alerta']:
                historial_señales.append({
                    "timestamp": datetime.now(),
                    "moneda": resultado['moneda'],
                    "decision": resultado['decision'],
                    "rsi": resultado['rsi']
                })
                guardar_historico(
                    resultado['moneda'], resultado['decision'], resultado['razon'],
                    resultado['rsi'], resultado['precio'],
                    resultado.get('take_profit'), resultado.get('stop_loss')
                )
                
                # Gráfico
                df = obtener_velas(moneda, "1h", 100)
                if df is not None:
                    grafico = generar_grafico(moneda, df, resultado)
                else:
                    grafico = None
                
                # Alerta enriquecida
                mensaje = f"""{'💰 OPORTUNIDAD' if 'COMPRA' in resultado['decision'] else '💸 ALERTA'}

📊 *Moneda:* {resultado['moneda']}
🎯 *Decisión:* {resultado['decision']}
📉 *RSI:* {resultado['rsi']} (1h) | {resultado.get('rsi_4h', 'N/A')} (4h)
🔗 *Correlación BTC:* {resultado.get('correlacion_btc', 'N/A')}
📈 *Precio:* ${resultado['precio']:.4f}
💰 *Valor:* ${resultado['valor_usdt']:.2f}
📈 *Take Profit:* ${resultado.get('take_profit', 0):.4f}
📉 *Stop Loss:* ${resultado.get('stop_loss', 0):.4f}
📊 *Volumen:* {resultado.get('ratio_volumen', 1)}x promedio

🎯 *Señales:* {resultado.get('señales_compra', resultado.get('señales_venta', 0))}/3 indicadores

🔍 *Motivo:* {resultado['razon']}
⏰ *Hora:* {datetime.now().strftime('%H:%M %d/%m/%Y')}"""
                enviar_telegram(mensaje, grafico)
        else:
            resultados.append({"moneda": moneda.upper(), "decision": "❌ NO SOPORTADA", "alerta": False})
        
        time.sleep(2)
    
    return resultados

# ========== MAIN ==========
def mostrar_bienvenida():
    print("""
    ╔══════════════════════════════════════╗
    ║      🦈  SHIRO BOT v3.0  🦈         ║
    ║   Análisis Profesional de Trading   ║
    ║   "El tiburón del mercado"          ║
    ╚══════════════════════════════════════╝
    """)

def main():
    mostrar_bienvenida()
    
    print(f"📊 Capital total: ${CAPITAL_TOTAL} | Riesgo: {RIESGO_POR_OPERACION}%")
    print(f"📈 Take Profit: {TAKE_PROFIT_PCT}% | Stop Loss: {STOP_LOSS_PCT}%")
    print(f"🔄 Trailing Stop: {TRAILING_STOP_PCT}% | Diversificación max: {DIVERSIFICACION_MAX}%")
    
    print("\n📊 Cargando monedas para VENTA...")
    ventas = leer_portafolio(VENTAS_SHEET_NAME)
    if ventas:
        procesar_lista(ventas, "venta")
    
    print("\n📊 Cargando monedas para COMPRA...")
    compras = leer_portafolio(COMPRAS_SHEET_NAME)
    if compras:
        procesar_lista(compras, "compra")
    
    # Enviar reporte diario
    enviar_reporte_diario()
    
    print("\n✅ Shiro v3.0 ha terminado el análisis")

if __name__ == "__main__":
    main()