import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="0DTE Command Center", page_icon="⚡")

st.markdown("""
    <style>
    .stApp {background-color: #0e1117;}
    .metric-card {
        background-color: #1f2937; padding: 20px; border-radius: 10px; 
        border: 1px solid #374151; text-align: center;
    }
    .gamma-pos { color: #4ade80; font-size: 1.8rem; font-weight: bold; }
    .gamma-neg { color: #f87171; font-size: 1.8rem; font-weight: bold; }
    .flip-val { color: #facc15; font-size: 1.8rem; font-weight: bold; }
    .section-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%);
        color: white; padding: 10px 20px; 
        border-radius: 8px; margin: 20px 0; font-size: 1.2rem; font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

st.title("⚡ 0DTE Command Center: GEX & Volatility Edge")

# --- SIDEBAR ---
with st.sidebar:
    st.header("📡 Configuración")
    TOKEN = st.text_input("Tradier Access Token", type="password")
    env_mode = st.radio("Entorno", ["Producción", "Sandbox"])
    BASE_URL = "https://api.tradier.com/v1" if env_mode == "Producción" else "https://sandbox.tradier.com/v1"
    st.divider()
    asset_input = st.text_input("Activo (Ej: SPY, $SPX)", value="SPY").upper().strip()
    st.divider()
    st.caption("v1.6.0 | 0DTE Strategic Edge")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- FUNCIONES DE CÁLCULO ---
def get_market_data(symbol):
    try:
        # 1. Spot y IV
        r = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': symbol, 'greeks': 'true'}, headers=get_headers())
        q = r.json()['quotes']['quote']
        spot = float(q['last'])
        # Estimación de IV 0DTE (usamos la IV del ATM)
        iv = float(q.get('ask_iv', 0.15)) 
        return spot, iv
    except: return 0, 0

def fetch_gex_extended(symbol, target_date):
    try:
        spot, iv = get_market_data(symbol)
        r_chain = requests.get(f"{BASE_URL}/markets/options/chains", 
                             params={'symbol': symbol, 'expiration': target_date, 'greeks': 'true'}, headers=get_headers())
        options = r_chain.json().get('options', {}).get('option', [])
        if isinstance(options, dict): options = [options]

        data = []
        for opt in options:
            if not opt.get('greeks'): continue
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            type_ = opt['option_type'].lower()
            
            # GEX Nominal
            gex = gamma * oi * 100 * spot * (spot * 0.01)
            if type_ == 'put': gex *= -1
            
            data.append({'strike': strike, 'gex': gex, 'type': type_})

        df = pd.DataFrame(data)
        
        # 1. Encontrar Gamma Flip (donde la suma acumulada cruza 0)
        df_sum = df.groupby('strike')['gex'].sum().reset_index().sort_values('strike')
        df_sum['cum_gex'] = df_sum['gex'].cumsum()
        
        # El Flip es el strike donde el GEX acumulado cambia de signo
        flip_row = df_sum[df_sum['gex'] > 0].iloc[0] if not df_sum[df_sum['gex'] > 0].empty else df_sum.iloc[0]
        gamma_flip = flip_row['strike']

        # 2. Expected Move 0DTE (Regla del 16% / sqrt(252))
        # Para 0DTE simplificado: Spot * (IV / sqrt(252))
        expected_move = spot * (iv / 15.87) 
        
        return df, spot, gamma_flip, expected_move
    except: return None, 0, 0, 0

# --- LÓGICA UI ---
if TOKEN:
    try:
        r_exp = requests.get(f"{BASE_URL}/markets/options/expirations", params={'symbol': asset_input}, headers=get_headers())
        available_dates = r_exp.json().get('expirations', {}).get('date', [])
        if isinstance(available_dates, str): available_dates = [available_dates]
        
        selected_date = st.sidebar.selectbox("Fecha Expiración (0DTE)", available_dates)

        if st.button(f"🔥 CALCULAR ESTRATEGIA 0DTE: {asset_input}"):
            df, spot, flip, move = fetch_gex_extended(asset_input, selected_date)
            
            if df is not None:
                # --- PANEL DE ESTRATEGIA ---
                st.markdown('<div class="section-header">🧠 0DTE TRADING EDGE</div>', unsafe_allow_html=True)
                
                c1, c2, c3, c4 = st.columns(4)
                
                # Card 1: Gamma Flip
                dist_flip = ((spot / flip) - 1) * 100
                c1.markdown(f'<div class="metric-card"><p class="kpi-label">GAMMA FLIP</p><p class="flip-val">{flip:,.0f}</p><p style="color:#888;">Distancia: {dist_flip:.2f}%</p></div>', unsafe_allow_html=True)
                
                # Card 2: Expected Move
                lower_band = spot - move
                upper_band = spot + move
                c2.markdown(f'<div class="metric-card"><p class="kpi-label">EXPECTED MOVE (±)</p><p style="font-size:1.8rem; font-weight:bold; color:#3b82f6;">±{move:.2f}</p><p style="color:#888;">Range: {lower_band:,.0f} - {upper_band:,.0f}</p></div>', unsafe_allow_html=True)
                
                # Card 3: Régimen actual
                total_gex = df['gex'].sum()
                status = "🛡️ PROTEGIDO" if spot > flip else "⚠️ PELIGRO"
                color = "#4ade80" if spot > flip else "#f87171"
                c3.markdown(f'<div class="metric-card"><p class="kpi-label">ESTADO DEL MERCADO</p><p style="font-size:1.8rem; font-weight:bold; color:{color};">{status}</p><p style="color:#888;">Precio vs Flip</p></div>', unsafe_allow_html=True)
                
                # Card 4: GEX Total
                c4.markdown(f'<div class="metric-card"><p class="kpi-label">TOTAL GEX</p><p class="{"gamma-pos" if total_gex > 0 else "gamma-neg"}">${total_gex/1e6:.1f}M</p></div>', unsafe_allow_html=True)

                # --- GRÁFICO AVANZADO ---
                st.markdown('<div class="section-header">📊 MAPA DE MUROS DE GAMMA (0DTE)</div>', unsafe_allow_html=True)
                
                df_grouped = df.groupby(['strike', 'type'])['gex'].sum().reset_index()
                # Filtrar para zoom
                df_plot = df_grouped[(df_grouped['strike'] > spot * 0.985) & (df_grouped['strike'] < spot * 1.015)]
                
                fig = go.Figure()
                # Barra de Calls (Gamma Positiva usualmente)
                calls = df_plot[df_plot['type'] == 'call']
                fig.add_trace(go.Bar(x=calls['strike'], y=calls['gex'], name="Call GEX", marker_color='#4ade80', opacity=0.7))
                
                # Barra de Puts (Gamma Negativa usualmente)
                puts = df_plot[df_plot['type'] == 'put']
                fig.add_trace(go.Bar(x=puts['strike'], y=puts['gex'], name="Put GEX", marker_color='#f87171', opacity=0.7))
                
                # Líneas de referencia
                fig.add_vline(x=spot, line_dash="dash", line_color="white", annotation_text="SPOT")
                fig.add_vline(x=flip, line_dash="dot", line_color="#facc15", annotation_text="FLIP")
                
                # Sombreado del Expected Move
                fig.add_vrect(x0=lower_band, x1=upper_band, fillcolor="rgba(59, 130, 246, 0.1)", line_width=0, annotation_text="Exp. Move")

                fig.update_layout(template="plotly_dark", barmode='relative', height=600, 
                                  xaxis_title="Strike Price", yaxis_title="GEX ($)",
                                  legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
                st.plotly_chart(fig, use_container_width=True)
                
                with st.expander("💡 Guía Rápida para 0DTE hoy:"):
                    st.write(f"""
                    - **ZONA SEGURA:** Si el precio está por encima de **{flip:,.0f}**, busca vender Puts o Spreads alcistas. Los Market Makers ayudan a soportar el precio.
                    - **ZONA DE VOLATILIDAD:** Si el precio cae por debajo de **{flip:,.0f}**, cierra tus ventas de Puts. El mercado se volverá muy rápido.
                    - **NIVELES DE TOMA DE GANANCIA:** El Expected Move sugiere que el SPX morirá entre **{lower_band:,.0f}** y **{upper_band:,.0f}**. Tus Iron Condors deberían estar idealmente fuera de este rango.
                    """)
    except Exception as e:
        st.error(f"Error al cargar fechas: {e}")
else:
    st.info("👈 Ingresa tu Token para desbloquear el 0DTE Edge.")
