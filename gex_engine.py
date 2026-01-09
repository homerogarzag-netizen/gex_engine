import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="GEX Volatility Engine", page_icon="📊")

# Estilos CSS (Manteniendo tu línea visual)
st.markdown("""
    <style>
    .stApp {background-color: #0e1117;}
    .metric-card {
        background-color: #1f2937; 
        padding: 20px; 
        border-radius: 10px; 
        border: 1px solid #374151; 
        text-align: center;
    }
    .gamma-pos { color: #4ade80; font-size: 2rem; font-weight: bold; }
    .gamma-neg { color: #f87171; font-size: 2rem; font-weight: bold; }
    .section-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%);
        color: white; padding: 10px 20px; 
        border-radius: 8px; margin: 20px 0; font-size: 1.2rem; font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📊 GEX Volatility Engine: SPX Analysis")

# --- SIDEBAR: CONEXIÓN ---
with st.sidebar:
    st.header("📡 Configuración")
    TOKEN = st.text_input("Tradier Access Token", type="password")
    env_mode = st.radio("Entorno", ["Producción", "Sandbox"])
    BASE_URL = "https://api.tradier.com/v1" if env_mode == "Producción" else "https://sandbox.tradier.com/v1"
    st.divider()
    dte_limit = st.slider("DTE Máximo para Análisis", 0, 30, 0, help="0 para solo 0DTE (Impacto inmediato)")
    st.caption("v1.0.0 | GEX Real-Time Engine")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- MOTOR DE CÁLCULO GEX ---
def fetch_gex_data(symbol):
    try:
        # 1. Obtener precio actual (Spot)
        r_quote = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': symbol}, headers=get_headers())
        spot_price = float(r_quote.json()['quotes']['quote']['last'])
        
        # 2. Obtener cadena de opciones con Griegas
        # Usamos SPX para GEX estructural del mercado
        params = {'symbol': symbol, 'expiration': datetime.now().strftime('%Y-%m-%d'), 'greeks': 'true'}
        # Si queremos más DTEs, primero debemos obtener las fechas de expiración
        r_exp = requests.get(f"{BASE_URL}/markets/options/expirations", params={'symbol': symbol, 'includeAllRoots': 'true'}, headers=get_headers())
        exp_dates = r_exp.json()['expirations']['date']
        
        all_options = []
        # Analizamos solo las expiraciones cercanas (según el slider del sidebar)
        for i in range(dte_limit + 1):
            if i < len(exp_dates):
                target_date = exp_dates[i]
                r_chain = requests.get(f"{BASE_URL}/markets/options/chains", 
                                     params={'symbol': symbol, 'expiration': target_date, 'greeks': 'true'}, 
                                     headers=get_headers())
                chain = r_chain.json().get('options', {}).get('option', [])
                if isinstance(chain, dict): chain = [chain]
                all_options.extend(chain)

        # 3. Procesar datos para GEX
        data = []
        for opt in all_options:
            if opt['greeks'] is None: continue
            
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            o_type = opt['option_type']
            
            # El GEX se calcula: Gamma * OI * 100 * Spot^2 (o Spot * 100 para simplificar exposición nominal)
            # Interpretación estándar: Market Makers son largos en Calls y cortos en Puts
            gex_val = gamma * oi * 100 * spot_price
            if o_type == 'put':
                gex_val *= -1  # Puts restan Gamma al sistema
                
            data.append({'strike': strike, 'gex': gex_val, 'type': o_type})

        df = pd.DataFrame(data)
        # Agrupar por strike para el gráfico
        df_grouped = df.groupby('strike')['gex'].sum().reset_index()
        
        return df_grouped, spot_price
    except Exception as e:
        st.error(f"Error analizando GEX: {e}")
        return None, 0

# --- LÓGICA DE INTERFAZ ---
if TOKEN:
    if st.button("🚀 CALCULAR PERFIL DE GAMMA"):
        with st.spinner("Escaneando Option Chain de SPX..."):
            # Usamos SPX (índice) para análisis de mercado puro
            df_gex, spot = fetch_gex_data("SPX")
            
            if df_gex is not None:
                total_gex = df_gex['gex'].sum()
                
                # Encontrar Gamma Flip (donde el GEX pasa de neg a pos)
                # Es una aproximación buscando el strike más cercano a 0 GEX acumulado
                df_sorted = df_gex.sort_values('strike')
                df_sorted['cum_gex'] = df_sorted['gex'].rolling(window=5).mean()
                
                # Mostrar Métricas Clave
                st.markdown('<div class="section-header">ESTADO DEL RÉGIMEN DE VOLATILIDAD</div>', unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns(3)
                
                # Card 1: Total GEX
                g_class = "gamma-pos" if total_gex > 0 else "gamma-neg"
                state = "CALMA (Long Gamma)" if total_gex > 0 else "TURBULENCIA (Short Gamma)"
                c1.markdown(f"""
                    <div class="metric-card">
                        <p style="color:#aaa; font-weight:bold;">SISTEMA TOTAL GEX</p>
                        <p class="{g_class}">{total_gex/1e9:.2f}Bn</p>
                        <p style="color:#888;">Regimen: {state}</p>
                    </div>
                """, unsafe_allow_html=True)
                
                # Card 2: Spot vs Flip (Simplificado: buscamos el cambio de signo)
                # Para este ejemplo rápido, mostramos el Spot
                c2.markdown(f"""
                    <div class="metric-card">
                        <p style="color:#aaa; font-weight:bold;">SPX ACTUAL</p>
                        <p style="font-size:2rem; font-weight:bold; color:white;">{spot:,.2f}</p>
                        <p style="color:#888;">Índice S&P 500</p>
                    </div>
                """, unsafe_allow_html=True)

                # Card 3: Recomendación 0DTE
                recom = "Venta de Crétido (OTM)" if total_gex > 0 else "Precaución / Direccional"
                c3.markdown(f"""
                    <div class="metric-card">
                        <p style="color:#aaa; font-weight:bold;">SESGO 0DTE</p>
                        <p style="font-size:1.5rem; font-weight:bold; color:#facc15;">{recom}</p>
                        <p style="color:#888;">Basado en exposición Gamma</p>
                    </div>
                """, unsafe_allow_html=True)

                # --- GRÁFICO DE EXPOSICIÓN POR STRIKE ---
                st.markdown('<div class="section-header">PERFIL DE EXPOSICIÓN GAMMA POR STRIKE</div>', unsafe_allow_html=True)
                
                # Filtrar strikes cerca del spot para que el gráfico se vea bien
                range_pct = 0.05 # +- 5%
                df_plot = df_gex[(df_gex['strike'] > spot * (1-range_pct)) & (df_gex['strike'] < spot * (1+range_pct))]
                
                fig = go.Figure()
                
                # Barras de GEX
                colors = ['#4ade80' if x > 0 else '#f87171' for x in df_plot['gex']]
                fig.add_trace(go.Bar(
                    x=df_plot['strike'],
                    y=df_plot['gex'],
                    marker_color=colors,
                    name="Gamma Exposure"
                ))
                
                # Línea de Precio Actual
                fig.add_vline(x=spot, line_dash="dash", line_color="white", 
                             annotation_text=f"SPOT: {spot}", annotation_position="top left")

                fig.update_layout(
                    template="plotly_dark",
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    height=500,
                    margin=dict(l=20, r=20, t=20, b=20),
                    xaxis=dict(title="Strike Price", gridcolor='#374151'),
                    yaxis=dict(title="GEX Nominal", gridcolor='#374151')
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                st.info("💡 **Cómo leer esto:** Si las barras son mayormente rojas y el precio baja, la volatilidad se expandirá violentamente. Si las barras son verdes (Gamma Positiva), el precio tiende a mantenerse en rangos o subir lentamente.")

else:
    st.info("👈 Introduce tu Token en la barra lateral para analizar el flujo de Gamma del mercado.")
