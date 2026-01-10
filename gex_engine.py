import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="GEX Volatility Engine", page_icon="📊")

# Estilos CSS Profesionales
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

st.title("📊 GEX Volatility Engine: Market Flow")

# --- SIDEBAR: CONEXIÓN Y SELECCIÓN ---
with st.sidebar:
    st.header("📡 Configuración")
    TOKEN = st.text_input("Tradier Access Token", type="password")
    env_mode = st.radio("Entorno", ["Producción", "Sandbox"])
    BASE_URL = "https://api.tradier.com/v1" if env_mode == "Producción" else "https://sandbox.tradier.com/v1"
    
    st.divider()
    # NUEVO: Selector de activo
    asset_choice = st.selectbox("Activo a Analizar", ["SPY", "QQQ", "IWM", "SPX", "AAPL", "TSLA"])
    dte_limit = st.slider("DTE Máximo (0 = Solo hoy)", 0, 5, 0)
    
    st.divider()
    st.caption("v1.3.0 | Multi-Asset GEX Engine")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- MAPEO DE SÍMBOLOS ---
def map_symbol_for_tradier(symbol):
    if symbol == "SPX": return "$SPXW"
    if symbol == "NDX": return "$NDX"
    if symbol == "RUT": return "$RUT"
    return symbol

# --- MOTOR DE CÁLCULO GEX ---
def fetch_gex_data(symbol):
    try:
        tradier_sym = map_symbol_for_tradier(symbol)
        
        # 1. Obtener precio actual (Spot)
        r_quote = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': tradier_sym}, headers=get_headers())
        q_json = r_quote.json()
        
        # Validación robusta del JSON de Tradier
        if 'quotes' not in q_json or q_json['quotes'] is None or q_json['quotes'] == 'null':
            st.error(f"Símbolo {tradier_sym} no encontrado o sin permisos en tu cuenta.")
            return None, 0
            
        q_data = q_json['quotes']['quote']
        spot_price = float(q_data['last'])
        
        # 2. Obtener fechas de expiración
        r_exp = requests.get(f"{BASE_URL}/markets/options/expirations", params={'symbol': tradier_sym, 'includeAllRoots': 'true'}, headers=get_headers())
        exp_json = r_exp.json()
        
        if 'expirations' not in exp_json or exp_json['expirations'] is None:
            st.error("No se encontraron expiraciones para este activo.")
            return None, 0
            
        exp_dates = exp_json['expirations']['date']
        if isinstance(exp_dates, str): exp_dates = [exp_dates] # Caso de una sola fecha
        
        all_options = []
        # Analizamos expiraciones según slider
        for i in range(dte_limit + 1):
            if i < len(exp_dates):
                target_date = exp_dates[i]
                r_chain = requests.get(f"{BASE_URL}/markets/options/chains", 
                                     params={'symbol': tradier_sym, 'expiration': target_date, 'greeks': 'true'}, 
                                     headers=get_headers())
                
                chain_data = r_chain.json().get('options')
                if chain_data and chain_data != 'null':
                    chain = chain_data.get('option', [])
                    if isinstance(chain, dict): chain = [chain]
                    all_options.extend(chain)

        if not all_options:
            return None, spot_price

        # 3. Procesar datos para GEX
        data = []
        for opt in all_options:
            if not opt.get('greeks'): continue
            
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            o_type = opt['option_type']
            
            # GEX Nominal: Gamma * OI * 100 * Spot * (Spot * 0.01)
            gex_val = gamma * oi * 100 * spot_price * (spot_price * 0.01)
            
            if o_type.lower() == 'put':
                gex_val *= -1
                
            data.append({'strike': strike, 'gex': gex_val})

        df = pd.DataFrame(data)
        df_grouped = df.groupby('strike')['gex'].sum().reset_index()
        
        return df_grouped, spot_price

    except Exception as e:
        st.error(f"Error técnico: {e}")
        return None, 0

# --- LÓGICA DE INTERFAZ ---
if TOKEN:
    if st.button(f"🚀 ANALIZAR FLUJO DE GAMMA ({asset_choice})"):
        with st.spinner(f"Escaneando Option Chain de {asset_choice}..."):
            df_gex, spot = fetch_gex_data(asset_choice)
            
            if df_gex is not None and not df_gex.empty:
                total_gex = df_gex['gex'].sum()
                call_wall = df_gex.loc[df_gex['gex'].idxmax()]['strike']
                put_wall = df_gex.loc[df_gex['gex'].idxmin()]['strike']
                
                # --- MÉTRICAS ---
                st.markdown(f'<div class="section-header">ESTADO GEX: {asset_choice} @ {spot:,.2f}</div>', unsafe_allow_html=True)
                
                c1, c2, c3, c4 = st.columns(4)
                
                g_class = "gamma-pos" if total_gex > 0 else "gamma-neg"
                state = "CALMA / RANGO" if total_gex > 0 else "VOLATILIDAD / VELOCIDAD"
                
                c1.markdown(f'<div class="metric-card"><p class="kpi-label">TOTAL GEX EXPOSURE</p><p class="{g_class}">${total_gex/1e6:.1f}M</p></div>', unsafe_allow_html=True)
                c2.markdown(f'<div class="metric-card"><p class="kpi-label">RÉGIMEN</p><p style="font-size:1.2rem; font-weight:bold; color:white; margin-top:10px;">{state}</p></div>', unsafe_allow_html=True)
                c3.markdown(f'<div class="metric-card"><p class="kpi-label">CALL WALL (Resistencia)</p><p style="font-size:2rem; font-weight:bold; color:#4ade80;">{call_wall:,.1f}</p></div>', unsafe_allow_html=True)
                c4.markdown(f'<div class="metric-card"><p class="kpi-label">PUT WALL (Soporte)</p><p style="font-size:2rem; font-weight:bold; color:#f87171;">{put_wall:,.1f}</p></div>', unsafe_allow_html=True)

                # --- GRÁFICO ---
                st.markdown('<div class="section-header">PERFIL DE EXPOSICIÓN POR STRIKE</div>', unsafe_allow_html=True)
                
                # Filtro dinámico de strikes (rango del 3% alrededor del spot)
                df_plot = df_gex[(df_gex['strike'] > spot * 0.97) & (df_gex['strike'] < spot * 1.03)]
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_plot['strike'],
                    y=df_plot['gex'],
                    marker_color=['#4ade80' if x > 0 else '#f87171' for x in df_plot['gex']],
                    name="Gamma Exposure"
                ))
                
                fig.add_vline(x=spot, line_dash="dash", line_color="yellow", 
                             annotation_text=f"SPOT", annotation_position="top")

                fig.update_layout(
                    template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                    height=500, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(title="Strike Price", gridcolor='#374151'),
                    yaxis=dict(title="GEX ($)", gridcolor='#374151')
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("No se pudieron extraer datos de GEX. Verifica que el mercado esté abierto o que tengas permisos para este símbolo.")
else:
    st.info("👈 Ingresa tu Token para comenzar el análisis de flujo.")
