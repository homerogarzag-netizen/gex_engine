import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="GEX Volatility Engine Pro", page_icon="📊")

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
    .date-tag {
        background-color: #3b82f6; color: white; padding: 2px 8px;
        border-radius: 4px; font-size: 0.8rem; margin-right: 5px;
    }
    .section-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%);
        color: white; padding: 10px 20px; 
        border-radius: 8px; margin: 20px 0; font-size: 1.2rem; font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📊 GEX Volatility Engine: Custom Analysis")

# --- SIDEBAR ---
with st.sidebar:
    st.header("📡 Configuración")
    TOKEN = st.text_input("Tradier Access Token", type="password")
    env_mode = st.radio("Entorno", ["Producción", "Sandbox"])
    BASE_URL = "https://api.tradier.com/v1" if env_mode == "Producción" else "https://sandbox.tradier.com/v1"
    
    st.divider()
    # MEJORA: Campo de texto libre
    asset_input = st.text_input("Activo a Analizar", value="SPY", help="Ejemplos: SPY, QQQ, AAPL, $SPX, $NDX").upper().strip()
    
    dte_limit = st.slider("Expiraciones Adicionales", 0, 10, 0, 
                         help="0 = Solo la expiración más cercana (Hoy). 1 = Hoy + la siguiente disponible.")
    
    st.divider()
    st.caption("v1.4.0 | Precision Date Tracking")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- MOTOR DE CÁLCULO GEX ---
def fetch_gex_data(symbol):
    try:
        # 1. Obtener precio actual (Spot)
        r_quote = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': symbol}, headers=get_headers())
        q_json = r_quote.json()
        
        if 'quotes' not in q_json or q_json['quotes'] is None or q_json['quotes'] == 'null':
            st.error(f"Símbolo '{symbol}' no encontrado. Intenta con $SPX o SPY.")
            return None, 0, []
            
        q_data = q_json['quotes']['quote']
        spot_price = float(q_data['last'])
        
        # 2. Obtener fechas de expiración reales
        r_exp = requests.get(f"{BASE_URL}/markets/options/expirations", params={'symbol': symbol, 'includeAllRoots': 'true'}, headers=get_headers())
        exp_json = r_exp.json()
        
        if 'expirations' not in exp_json or exp_json['expirations'] is None:
            st.error("No se encontraron expiraciones para este activo.")
            return None, 0, []
            
        exp_dates = exp_json['expirations']['date']
        if isinstance(exp_dates, str): exp_dates = [exp_dates]
        
        # Seleccionamos las fechas según el slider
        selected_dates = exp_dates[:dte_limit + 1]
        
        all_options = []
        for target_date in selected_dates:
            r_chain = requests.get(f"{BASE_URL}/markets/options/chains", 
                                 params={'symbol': symbol, 'expiration': target_date, 'greeks': 'true'}, 
                                 headers=get_headers())
            
            chain_data = r_chain.json().get('options')
            if chain_data and chain_data != 'null':
                chain = chain_data.get('option', [])
                if isinstance(chain, dict): chain = [chain]
                all_options.extend(chain)

        if not all_options:
            return None, spot_price, selected_dates

        # 3. Procesar datos para GEX
        data = []
        for opt in all_options:
            if not opt.get('greeks'): continue
            
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            o_type = opt['option_type']
            
            # GEX Nominal simplificado para visualización
            gex_val = gamma * oi * 100 * spot_price * (spot_price * 0.01)
            if o_type.lower() == 'put': gex_val *= -1
            data.append({'strike': strike, 'gex': gex_val})

        df = pd.DataFrame(data)
        df_grouped = df.groupby('strike')['gex'].sum().reset_index()
        
        return df_grouped, spot_price, selected_dates

    except Exception as e:
        st.error(f"Error técnico: {e}")
        return None, 0, []

# --- LÓGICA DE INTERFAZ ---
if TOKEN:
    if st.button(f"🚀 ANALIZAR FLUJO: {asset_input}"):
        with st.spinner(f"Calculando exposición para {asset_input}..."):
            df_gex, spot, dates_used = fetch_gex_data(asset_input)
            
            if df_gex is not None and not df_gex.empty:
                total_gex = df_gex['gex'].sum()
                call_wall = df_gex.loc[df_gex['gex'].idxmax()]['strike']
                put_wall = df_gex.loc[df_gex['gex'].idxmin()]['strike']
                
                # --- INFO DE FECHAS ---
                date_str = " | ".join(dates_used)
                st.markdown(f"🗓️ **Expiraciones incluidas:** `{date_str}`")

                # --- MÉTRICAS ---
                st.markdown(f'<div class="section-header">ESTADO GEX: {asset_input} @ {spot:,.2f}</div>', unsafe_allow_html=True)
                
                c1, c2, c3, c4 = st.columns(4)
                g_class = "gamma-pos" if total_gex > 0 else "gamma-neg"
                
                c1.markdown(f'<div class="metric-card"><p class="kpi-label">TOTAL GEX</p><p class="{g_class}">${total_gex/1e6:.1f}M</p></div>', unsafe_allow_html=True)
                c2.markdown(f'<div class="metric-card"><p class="kpi-label">RÉGIMEN</p><p style="font-size:1.2rem; font-weight:bold; color:white; margin-top:10px;">{"ESTABLE" if total_gex > 0 else "VOLÁTIL"}</p></div>', unsafe_allow_html=True)
                c3.markdown(f'<div class="metric-card"><p class="kpi-label">CALL WALL</p><p style="font-size:2rem; font-weight:bold; color:#4ade80;">{call_wall:,.1f}</p></div>', unsafe_allow_html=True)
                c4.markdown(f'<div class="metric-card"><p class="kpi-label">PUT WALL</p><p style="font-size:2rem; font-weight:bold; color:#f87171;">{put_wall:,.1f}</p></div>', unsafe_allow_html=True)

                # --- GRÁFICO ---
                st.markdown('<div class="section-header">PERFIL DE EXPOSICIÓN POR STRIKE</div>', unsafe_allow_html=True)
                
                # Filtro dinámico 3%
                df_plot = df_gex[(df_gex['strike'] > spot * 0.97) & (df_gex['strike'] < spot * 1.03)]
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_plot['strike'],
                    y=df_plot['gex'],
                    marker_color=['#4ade80' if x > 0 else '#f87171' for x in df_plot['gex']],
                    name="Gamma Exposure"
                ))
                
                fig.add_vline(x=spot, line_dash="dash", line_color="yellow", 
                             annotation_text=f"SPOT: {spot:,.2f}", annotation_position="top")

                fig.update_layout(
                    template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                    height=500, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(title="Strike Price"), yaxis=dict(title="GEX ($)")
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Verifica el símbolo. Para índices prueba con $SPX, para ETFs usa SPY.")
else:
    st.info("👈 Ingresa tu Token para comenzar.")
