import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="GEX Volatility Engine", page_icon="📊")

# Estilos CSS Profesionales (Manteniendo tu línea visual oscura)
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
    dte_limit = st.slider("DTE Máximo (0 = Solo hoy)", 0, 5, 0)
    st.caption("v1.2.0 | GEX Real-Time Engine")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- MOTOR DE CÁLCULO GEX ---
def fetch_gex_data():
    try:
        # 1. Obtener precio actual (Spot) del SPX
        # Usamos $SPX que es el formato común de índices en Tradier
        r_quote = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': '$SPX'}, headers=get_headers())
        if r_quote.status_code != 200:
            st.error("Error al obtener Spot de SPX. Revisa el Token.")
            return None, 0
        
        q_data = r_quote.json()['quotes']['quote']
        spot_price = float(q_data['last'])
        
        # 2. Obtener fechas de expiración
        r_exp = requests.get(f"{BASE_URL}/markets/options/expirations", params={'symbol': '$SPX', 'includeAllRoots': 'true'}, headers=get_headers())
        exp_dates = r_exp.json()['expirations']['date']
        
        all_options = []
        # Analizamos solo las expiraciones según el slider
        for i in range(dte_limit + 1):
            if i < len(exp_dates):
                target_date = exp_dates[i]
                r_chain = requests.get(f"{BASE_URL}/markets/options/chains", 
                                     params={'symbol': '$SPX', 'expiration': target_date, 'greeks': 'true'}, 
                                     headers=get_headers())
                
                # Tradier devuelve un dict si es solo una opción, o lista si son varias
                chain = r_chain.json().get('options', {}).get('option', [])
                if isinstance(chain, dict): chain = [chain]
                all_options.extend(chain)

        # 3. Procesar datos para GEX
        data = []
        for opt in all_options:
            if not opt.get('greeks'): continue
            
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            o_type = opt['option_type']
            
            # CÁLCULO GEX ESTÁNDAR:
            # GEX = Gamma * OI * 100 * Spot * (Spot * 0.01) 
            # Esto representa el valor en dólares que los Market Makers deben comprar/vender por cada 1% de movimiento.
            gex_val = gamma * oi * 100 * spot_price * (spot_price * 0.01)
            
            if o_type.lower() == 'put':
                gex_val *= -1  # Puts representan Gamma negativa para el dealer
                
            data.append({'strike': strike, 'gex': gex_val, 'type': o_type})

        if not data:
            return None, 0
            
        df = pd.DataFrame(data)
        df_grouped = df.groupby('strike')['gex'].sum().reset_index()
        
        return df_grouped, spot_price
    except Exception as e:
        st.error(f"Error técnico: {e}")
        return None, 0

# --- LÓGICA DE INTERFAZ ---
if TOKEN:
    if st.button("🚀 ANALIZAR FLUJO DE GAMMA (SPX)"):
        with st.spinner("Escaneando Option Chain de SPX..."):
            df_gex, spot = fetch_gex_data()
            
            if df_gex is not None:
                total_gex = df_gex['gex'].sum()
                
                # Identificar el mayor muro de Gamma (Strikes críticos)
                call_wall = df_gex.loc[df_gex['gex'].idxmax()]['strike']
                put_wall = df_gex.loc[df_gex['gex'].idxmin()]['strike']
                
                # --- MÉTRICAS ---
                st.markdown('<div class="section-header">ESTADO DEL RÉGIMEN DE VOLATILIDAD (GEX)</div>', unsafe_allow_html=True)
                
                c1, c2, c3, c4 = st.columns(4)
                
                # Total GEX
                g_class = "gamma-pos" if total_gex > 0 else "gamma-neg"
                state = "CALMA" if total_gex > 0 else "VOLATILIDAD"
                c1.markdown(f'<div class="metric-card"><p class="kpi-label">SISTEMA TOTAL GEX</p><p class="{g_class}">${total_gex/1e9:.2f}Bn</p><p style="color:#888;">MODO: {state}</p></div>', unsafe_allow_html=True)
                
                # Spot
                c2.markdown(f'<div class="metric-card"><p class="kpi-label">SPX ACTUAL</p><p style="font-size:2rem; font-weight:bold; color:white;">{spot:,.2f}</p></div>', unsafe_allow_html=True)

                # Call Wall (Resistencia técnica por Gamma)
                c3.markdown(f'<div class="metric-card"><p class="kpi-label">CALL WALL (Resistencia)</p><p style="font-size:2rem; font-weight:bold; color:#4ade80;">{call_wall:,.0f}</p></div>', unsafe_allow_html=True)
                
                # Put Wall (Soporte técnico por Gamma)
                c4.markdown(f'<div class="metric-card"><p class="kpi-label">PUT WALL (Soporte)</p><p style="font-size:2rem; font-weight:bold; color:#f87171;">{put_wall:,.0f}</p></div>', unsafe_allow_html=True)

                # --- GRÁFICO ---
                st.markdown('<div class="section-header">PERFIL DE EXPOSICIÓN GAMMA POR STRIKE</div>', unsafe_allow_html=True)
                
                # Zoom al Spot (+- 2%)
                df_plot = df_gex[(df_gex['strike'] > spot * 0.98) & (df_gex['strike'] < spot * 1.02)]
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_plot['strike'],
                    y=df_plot['gex'],
                    marker_color=['#4ade80' if x > 0 else '#f87171' for x in df_plot['gex']],
                    name="Gamma Exposure"
                ))
                
                fig.add_vline(x=spot, line_dash="dash", line_color="white", annotation_text=f"SPOT", annotation_position="top")

                fig.update_layout(
                    template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                    height=500, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(title="Strike Price"), yaxis=dict(title="GEX ($)")
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # --- TIPS DE TRADING ---
                with st.expander("📝 Interpretación para tu operativa 0DTE"):
                    st.write("""
                    - **Gamma Positiva ($ > 0):** Los Market Makers compran las caídas y venden las subidas para mantenerse neutrales. Esto 'ancla' el precio. Es el escenario ideal para vender Iron Condors o Spreads OTM.
                    - **Gamma Negativa ($ < 0):** Los Market Makers deben vender cuando el precio baja y comprar cuando sube, lo que acelera los movimientos. **Peligro para vendedores de opciones**, mejor para estrategias direccionales.
                    - **Call/Put Walls:** Son imanes de precio. El SPX suele tener dificultades para cruzar estos niveles porque requieren grandes ajustes de cobertura.
                    """)
            else:
                st.warning("No se encontraron datos para la expiración seleccionada.")
else:
    st.info("👈 Introduce tu Tradier Token en la barra lateral para comenzar.")
