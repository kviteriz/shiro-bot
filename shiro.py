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

# ========== CONFIGURACIÓN ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Archivos de Google Sheets
VENTAS_SHEET_NAME = os.getenv("VENTAS_SHEET_NAME", "Mis Criptos")
COMPRAS_SHEET_NAME = os.getenv("COMPRAS_SHEET_NAME", "Mis Compras")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Portafolio")

# Mapeo de nombres a IDs de CoinGecko (actualizado)
MAPEO_COINGECKO = {
    # Grandes capitalizaciones
    'btc': 'bitcoin',
    'eth': 'ethereum',
    'sol': 'solana',
    'sui': 'sui',
    'hbar': 'hedera-hashgraph',
    'doge': 'dogecoin',
    'pepe': 'pepe',
    'ada': 'cardano',
    'dot': 'polkadot',
    'matic': 'polygon',
    'link': 'chainlink',
    'uni': 'uniswap',
    'aave': 'aave',
    
    # DeFi y exchanges
    'ray': 'raydium',
    'joe': 'joe',
    'jup': 'jupiter',
    'ondo': 'ondo-finance',
    'pyth': 'pyth-network',
    'cetus': 'cetus-protocol',
    'aero': 'aerodrome-finance',
    
    # Tokens de SUI
    'deep': 'deep-book',
    'cpool': 'clearpool',
    
    # Verificados uno por uno
    'rhea': 'rhea',           # ✅ Verificado
    'sauce': 'sauce',         # ✅ Verificado (SaucerSwap)
    'aster': 'aster',         # ✅ Verificado (Aster)
    'astr': 'aster',          # Alias
    'met': 'meteora',         # ✅ Verificado (Meteora)
    'plume': 'plume',         # ✅ Verificado (Plume)
    
    # Alias adicionales
    'meteora': 'meteora',
}

# ========== TELEGRAM ==========
def enviar_telegram(mensaje):
    """Shiro envía alerta a Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado. Las alertas no se enviarán.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🦈 *SHIRO BOT*\n\n{mensaje}",
            "parse_mode": "Markdown"
        }, timeout=15)  # Aumentado de 5 a 15 segundos
        print("📱 Shiro envió alerta a Telegram")
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

# ========== GOOGLE SHEETS ==========
def conectar_google_sheets():
    """Conecta con Google Sheets usando credenciales"""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if os.getenv("GOOGLE_CREDENTIALS_JSON"):
        import json
        creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
        return ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        return ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

def leer_portafolio(sheet_name):
    """Lee monedas desde un Google Sheets (ventas o compras)"""
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
        
        print(f"🦈 Shiro cargó {len(portafolio)} monedas desde {sheet_name}")
        return portafolio
    except Exception as e:
        print(f"❌ Error leyendo {sheet_name}: {e}")
        return {}

# ========== ANÁLISIS CON BINANCE ==========
def analizar_con_binance(symbol, cantidad, modo="venta"):
    """Analiza moneda usando Binance"""
    try:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol.upper()}USDT&interval=1h&limit=100'
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if 'code' in data or not isinstance(data, list) or len(data) < 30:
            return None
        
        df = pd.DataFrame(data, columns=['time','open','high','low','close','volume','close_time','quote_asset_volume','trades','taker_buy_base','taker_buy_quote','ignore'])
        df['close'] = df['close'].astype(float)
        
        rsi = RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]
        macd = MACD(close=df['close'])
        macd_line = macd.macd().iloc[-1]
        signal_line = macd.macd_signal().iloc[-1]
        precio = df['close'].iloc[-1]
        valor_total = cantidad * precio
        
        # ========== LÓGICA DE COMPRA ==========
        if modo == "compra":
            if rsi < 20:
                decision = "🔵 COMPRAR MUCHO"
                razon = f"RSI extremadamente bajo ({rsi:.1f})"
                alerta = True
            elif rsi < 25 and macd_line > signal_line:
                decision = "🟢 COMPRAR YA"
                razon = f"RSI {rsi:.1f} + MACD alcista"
                alerta = True
            elif rsi < 30:
                decision = "🟢 COMPRAR"
                razon = f"RSI sobrevendido ({rsi:.1f})"
                alerta = True
            elif rsi < 45:
                decision = "⚪ OBSERVAR"
                razon = f"RSI {rsi:.1f} - podría bajar más"
                alerta = False
            else:
                decision = "⚪ ESPERAR"
                razon = f"RSI {rsi:.1f} - no está barato"
                alerta = False
        
        # ========== LÓGICA DE VENTA ==========
        else:
            # Detectar oportunidades de COMPRA en modo venta (RSI bajo)
            if rsi < 25:
                decision = "🔵 ¡OPORTUNIDAD DE COMPRA!"
                razon = f"RSI extremadamente bajo ({rsi:.1f}) - considera comprar más"
                alerta = True
            elif rsi < 30:
                decision = "🟢 OPORTUNIDAD DE COMPRA"
                razon = f"RSI {rsi:.1f} - zona de sobreventa"
                alerta = True
            elif rsi > 80:
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
        
        return {
            "moneda": symbol.upper(),
            "precio": round(precio, 8),
            "valor_usdt": round(valor_total, 2),
            "rsi": round(rsi, 1),
            "decision": decision,
            "razon": razon,
            "alerta": alerta,
            "modo": modo,
            "fuente": "Binance"
        }
        
    except Exception as e:
        return None

# ========== ANÁLISIS CON COINGECKO ==========
def analizar_con_coingecko(symbol, cantidad, modo="venta"):
    """Analiza moneda usando CoinGecko (fallback)"""
    if symbol not in MAPEO_COINGECKO:
        return None
    
    gecko_id = MAPEO_COINGECKO[symbol]
    try:
        # Obtener precio actual
        url_price = f"https://api.coingecko.com/api/v3/simple/price?ids={gecko_id}&vs_currencies=usd"
        response = requests.get(url_price, timeout=10)
        data = response.json()
        
        if gecko_id not in data:
            return None
        
        precio = data[gecko_id]['usd']
        valor_total = cantidad * precio
        
        # Intentar obtener RSI de velas diarias
        rsi_valor = "N/A"
        try:
            url_ohlc = f"https://api.coingecko.com/api/v3/coins/{gecko_id}/ohlc?vs_currency=usd&days=30"
            ohlc_data = requests.get(url_ohlc, timeout=10).json()
            if ohlc_data and len(ohlc_data) >= 14:
                df = pd.DataFrame(ohlc_data, columns=['timestamp', 'open', 'high', 'low', 'close'])
                df['close'] = df['close'].astype(float)
                rsi_valor = round(RSIIndicator(close=df['close'], window=14).rsi().iloc[-1], 1)
        except:
            pass
        
        # Lógica según modo y RSI disponible
        if modo == "compra":
            if rsi_valor != "N/A" and rsi_valor < 30:
                decision = "🟢 COMPRAR (CoinGecko)"
                razon = f"RSI diario {rsi_valor}"
                alerta = True
            else:
                decision = "⚪ OBSERVAR (CoinGecko)"
                razon = "Solo precio disponible" if rsi_valor == "N/A" else f"RSI diario {rsi_valor}"
                alerta = False
        else:
            # Modo venta: también detectar oportunidades de compra
            if rsi_valor != "N/A" and rsi_valor < 30:
                decision = "🟢 OPORTUNIDAD COMPRA (CoinGecko)"
                razon = f"RSI diario {rsi_valor} - zona sobreventa"
                alerta = True
            elif rsi_valor != "N/A" and rsi_valor > 70:
                decision = "🟡 REVISAR VENTA (CoinGecko)"
                razon = f"RSI diario {rsi_valor}"
                alerta = False
            else:
                decision = "⚪ ESPERAR (CoinGecko)"
                razon = "Solo precio disponible" if rsi_valor == "N/A" else f"RSI diario {rsi_valor}"
                alerta = False
        
        return {
            "moneda": symbol.upper(),
            "precio": round(precio, 8),
            "valor_usdt": round(valor_total, 2),
            "rsi": rsi_valor,
            "decision": decision,
            "razon": razon,
            "alerta": alerta,
            "modo": modo,
            "fuente": "CoinGecko"
        }
    except Exception as e:
        print(f"  ❌ Error CoinGecko: {e}")
        return None

# ========== ANÁLISIS INTELIGENTE ==========
def analizar_moneda(symbol, cantidad, modo="venta"):
    """Intenta Binance primero, luego CoinGecko"""
    
    # 1. Intentar Binance
    resultado = analizar_con_binance(symbol, cantidad, modo)
    
    if resultado:
        return resultado
    
    # 2. Si falla, intentar CoinGecko
    resultado = analizar_con_coingecko(symbol, cantidad, modo)
    
    if resultado:
        return resultado
    
    # 3. No encontrada en ninguna parte
    return {
        "moneda": symbol.upper(),
        "decision": "❌ NO SOPORTADA",
        "razon": "No encontrada en Binance ni CoinGecko",
        "alerta": False,
        "modo": modo,
        "fuente": "Ninguna"
    }

# ========== PROCESAR LISTA ==========
def procesar_lista(portafolio, modo):
    """Procesa una lista de monedas (ventas o compras)"""
    resultados = []
    for moneda, cantidad in portafolio.items():
        print(f"🔍 Analizando {moneda.upper()} ({modo})...")
        
        resultado = analizar_moneda(moneda, cantidad, modo)
        resultados.append(resultado)
        
        # Enviar alerta a Telegram si es necesario
        if resultado.get('alerta', False):
            if modo == "compra":
                icono = "💰 OPORTUNIDAD DE COMPRA"
            else:
                # Detectar si es alerta de compra o venta
                if "COMPRA" in resultado['decision']:
                    icono = "💰 OPORTUNIDAD DE COMPRA"
                else:
                    icono = "💸 ALERTA DE VENTA"
            
            mensaje = f"""{icono}

📊 *Moneda:* {resultado['moneda']}
🎯 *Decisión:* {resultado['decision']}
💰 *Cantidad:* {cantidad}
💵 *Valor:* ${resultado.get('valor_usdt', 0):,.2f}
📈 *Precio:* ${resultado.get('precio', 0):.8f}
📉 *RSI:* {resultado.get('rsi', 'N/A')}
📡 *Fuente:* {resultado.get('fuente', 'Binance')}

🔍 *Motivo:* {resultado['razon']}
⏰ *Hora:* {datetime.now().strftime('%H:%M %d/%m/%Y')}"""
            enviar_telegram(mensaje)
        
        time.sleep(1)  # Evitar rate limit
    
    return resultados

# ========== MOSTRAR REPORTE ==========
def mostrar_reporte(resultados, titulo):
    """Muestra un reporte formateado en consola"""
    print("\n" + "=" * 60)
    print(f"📋 {titulo}")
    print("=" * 60)
    
    for r in resultados:
        if 'NO SOPORTADA' in r['decision']:
            print(f"❌ {r['moneda']}: {r['decision']}")
        else:
            rsi_texto = f"RSI: {r['rsi']}" if r.get('rsi') != "N/A" else "RSI: ---"
            alerta_icono = "🔔" if r.get('alerta', False) else "🔕"
            valor_texto = f"${r.get('valor_usdt', 0):.2f}" if r.get('valor_usdt') else "$---"
            fuente_icono = "📊" if r.get('fuente') == "Binance" else "🌐"
            print(f"{alerta_icono} {fuente_icono} {r['decision']} {r['moneda']} | {valor_texto} | {rsi_texto}")

# ========== BIENVENIDA ==========
def mostrar_bienvenida():
    print("""
    ╔══════════════════════════════════════╗
    ║      🦈  SHIRO BOT v2.0  🦈         ║
    ║   Compra + Venta - El tiburón       ║
    ║   "El tiburón del mercado"          ║
    ╚══════════════════════════════════════╝
    """)

# ========== EJECUCIÓN PRINCIPAL ==========
def main():
    mostrar_bienvenida()
    
    # 1. Leer y procesar monedas para VENTA (las que tienes)
    print("\n📊 Cargando monedas para VENTA...")
    ventas = leer_portafolio(VENTAS_SHEET_NAME)
    resultados_venta = []
    if ventas:
        resultados_venta = procesar_lista(ventas, "venta")
        mostrar_reporte(resultados_venta, "📉 SEÑALES DE VENTA Y OPORTUNIDADES")
    
    # 2. Leer y procesar monedas para COMPRA (watchlist)
    print("\n📊 Cargando monedas para COMPRA...")
    compras = leer_portafolio(COMPRAS_SHEET_NAME)
    resultados_compra = []
    if compras:
        resultados_compra = procesar_lista(compras, "compra")
        mostrar_reporte(resultados_compra, "💰 SEÑALES DE COMPRA")
    
    # 3. Resumen final
    if not ventas and not compras:
        print("❌ No se encontraron monedas en ningún archivo.")
        return
    
    # Contar alertas
    total_alertas = sum(1 for r in resultados_venta + resultados_compra if r.get('alerta', False))
    
    print("\n" + "=" * 60)
    print(f"✅ Shiro ha terminado el análisis")
    print(f"📊 Total de monedas analizadas: {len(resultados_venta) + len(resultados_compra)}")
    print(f"🔔 Alertas generadas: {total_alertas}")
    print("=" * 60)

if __name__ == "__main__":
    main()