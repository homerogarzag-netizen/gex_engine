import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="GEX Precision Engine", page_icon="🎯")

# Estilos CSS
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

st.title("🎯 GEX Volatility Engine: Precision Mode")

# --- SIDEBAR ---
with st.sidebar:
    st.header("📡 Configuración")
    TOKEN = st.text_input("Tradier Access Token", type="password")
    env_mode = st.radio("Entorno", ["Producción", "Sandbox"])
    BASE_URL = "https://api.tradier.com/v1" if env_mode == "Producción" else "https://sandbox.tradier.com/v1"
    
    st.divider()
    asset_input = st.text_input("Activo", value="SPY").upper().strip()
    
    # Botón para refrescar fechas
    refresh_dates = st.button("🔄 Cargar Fechas Disponibles")
    
    st.divider()
    st.caption("v1.5.0 | Single Date Precision")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- FUNCIONES DE DATOS ---
def get_expirations(symbol):
    try:
        r = requests.get(f"{BASE_URL}/markets/options/expirations", 
                         params={'symbol': symbol, 'includeAllRoots': 'true'}, headers=get_headers())
        dates = r.json().get('expirations', {}).get('date', [])
        return [dates] if isinstance(dates, str) else dates
    except: return []

def fetch_gex_data(symbol, target_dates):
    try:
        # 1. Spot Price
        r_quote = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': symbol}, headers=get_headers())
        spot_price = float(r_quote.json()['quotes']['quote']['last'])
        
        all_options = []
        for d in target_dates:
            r_chain = requests.get(f"{BASE_URL}/markets/options/chains", 
                                 params={'symbol': symbol, 'expiration': d, 'greeks': 'true'}, 
                                 headers=get_headers())
            chain = r_chain.json().get('options', {}).get('option', [])
            if isinstance(chain, dict): chain = [chain]
            all_options.extend(chain)

        data = []
        for opt in all_options:
            if not opt.get('greeks'): continue
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            gex_val = gamma * oi * 100 * spot_price * (spot_price * 0.01)
            if opt['option_type'].lower() == 'put': gex_val *= -1
            data.append({'strike': strike, 'gex': gex_val})

        df = pd.DataFrame(data).groupby('strike')['gex'].sum().reset_index()
        return df, spot_price
    except Exception as e:
        st.error(f"Error: {e}")
        return None, 0

# --- LÓGICA DE INTERFAZ ---
if TOKEN:
    available_dates = get_expirations(asset_input)
    
    if available_dates:
        with st.sidebar:
            # Selector de modo
            mode = st.radio("Modo de Análisis", ["Fecha Específica", "Acumulado Proximas 5"])
            
            if mode == "Fecha Específica":
                selected_date = st.selectbox("Selecciona Expiración", available_dates)
                dates_to_process = [selected_date]
            else:
                dates_to_process = available_dates[:5]
        
        if st.button(f"🚀 ANALIZAR {asset_input}"):
            df_gex, spot = fetch_gex_data(asset_input, dates_to_process)
            
            if df_gex is not None:
                total_gex = df_gex['gex'].sum()
                call_wall = df_gex.loc[df_gex['gex'].idxmax()]['strike']
                put_wall = df_gex.loc[df_gex['gex'].idxmin()]['strike']
                
                # --- INFO ---
                st.info(f"📅 **Analizando:** {', '.join(dates_to_process)}")

                # --- MÉTRICAS ---
                st.markdown(f'<div class="section-header">ESTADO GEX: {asset_input} @ {spot:,.2f}</div>', unsafe_allow_html=True)
                
                c1, c2, c3, c4 = st.columns(4)
                g_class = "gamma-pos" if total_gex > 0 else "gamma-neg"
                
                c1.markdown(f'<div class="metric-card"><p class="kpi-label">GEX NOMINAL</p><p class="{g_class}">${total_gex/1e6:.1f}M</p></div>', unsafe_allow_html=True)
                c2.markdown(f'<div class="metric-card"><p class="kpi-label">RÉGIMEN</p><p style="font-size:1.2rem; font-weight:bold; color:white; margin-top:10px;">{"CALMA" if total_gex > 0 else "VOLÁTIL"}</p></div>', unsafe_allow_html=True)
                c3.markdown(f'<div class="metric-card"><p class="kpi-label">CALL WALL</p><p style="font-size:2rem; font-weight:bold; color:#4ade80;">{call_wall:,.0f}</p></div>', unsafe_allow_html=True)
                c4.markdown(f'<div class="metric-card"><p class="kpi-label">PUT WALL</p><p style="font-size:2rem; font-weight:bold; color:#f87171;">{put_wall:,.0f}</p></div>', unsafe_allow_html=True)

                # --- GRÁFICO ---
                st.markdown('<div class="section-header">PERFIL DE EXPOSICIÓN POR STRIKE</div>', unsafe_allow_html=True)
                df_plot = df_gex[(df_gex['strike'] > spot * 0.96) & (df_gex['strike'] < spot * 1.04)]
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_plot['strike'], y=df_plot['gex'],
                    marker_color=['#4ade80' if x > 0 else '#f87171' for x in df_plot['gex']]
                ))
                fig.add_vline(x=spot, line_dash="dash", line_color="yellow", annotation_text=f"SPOT: {spot:,.2f}")
                fig.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', height=500)
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No se pudieron cargar fechas. Revisa el símbolo o tu conexión.")
else:
    st.info("👈 Ingresa tu Token para comenzar.")
