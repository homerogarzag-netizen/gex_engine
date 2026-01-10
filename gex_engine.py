import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="0DTE Master Command Center", page_icon="🛡️")

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

st.title("🛡️ 0DTE CEO Command Center")

# --- SIDEBAR ---
with st.sidebar:
    st.header("📡 Configuración")
    TOKEN = st.text_input("Tradier Access Token", type="password")
    env_mode = st.radio("Entorno", ["Producción", "Sandbox"])
    BASE_URL = "https://api.tradier.com/v1" if env_mode == "Producción" else "https://sandbox.tradier.com/v1"
    
    st.divider()
    asset_raw = st.text_input("Activo (Ej: SPX, SPY, QQQ)", value="SPX").upper().strip()
    
    # Lógica inteligente para SPX
    asset_input = "$SPXW" if asset_raw == "SPX" else asset_raw
    
    st.divider()
    st.caption("v1.7.0 | Dual View & SPXW Fix")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- FUNCIONES DE DATOS ---
def get_expirations(symbol):
    try:
        # Intentamos obtener expiraciones. Si es SPX, buscamos en el root de weeklies.
        r = requests.get(f"{BASE_URL}/markets/options/expirations", 
                         params={'symbol': symbol, 'includeAllRoots': 'true'}, headers=get_headers())
        dates = r.json().get('expirations', {}).get('date', [])
        if not dates: # Reintento por si falla el root
            return []
        return [dates] if isinstance(dates, str) else dates
    except: return []

def fetch_full_data(symbol, target_date):
    try:
        # 1. Spot y IV para Expected Move
        r_q = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': symbol, 'greeks': 'true'}, headers=get_headers())
        q = r_q.json()['quotes']['quote']
        spot = float(q['last'])
        iv = float(q.get('ask_iv', 0.15))

        # 2. Chain
        r_c = requests.get(f"{BASE_URL}/markets/options/chains", 
                           params={'symbol': symbol, 'expiration': target_date, 'greeks': 'true'}, headers=get_headers())
        options = r_c.json().get('options', {}).get('option', [])
        if isinstance(options, dict): options = [options]

        data = []
        for opt in options:
            if not opt.get('greeks'): continue
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            o_type = opt['option_type'].lower()
            
            # GEX Nominal: Gamma * OI * 100 * Spot * (Spot * 0.01)
            gex = gamma * oi * 100 * spot * (spot * 0.01)
            if o_type == 'put': gex *= -1
            
            data.append({'strike': strike, 'gex': gex, 'type': o_type})

        df = pd.DataFrame(data)
        
        # 3. Cálculos Estratégicos
        df_net = df.groupby('strike')['gex'].sum().reset_index().sort_values('strike')
        df_net['cum_gex'] = df_net['gex'].cumsum()
        
        # Gamma Flip
        flip_row = df_net[df_net['gex'] > 0].iloc[0] if not df_net[df_net['gex'] > 0].empty else df_net.iloc[0]
        gamma_flip = flip_row['strike']
        
        # Expected Move
        expected_move = spot * (iv / 15.87) 
        
        return df, df_net, spot, gamma_flip, expected_move
    except Exception as e:
        st.error(f"Error en datos: {e}")
        return None, None, 0, 0, 0

# --- LÓGICA DE INTERFAZ ---
if TOKEN:
    available_dates = get_expirations(asset_input)
    
    # Si no encuentra con $SPXW, intentamos con el símbolo original
    if not available_dates and asset_input == "$SPXW":
        available_dates = get_expirations("$SPX")
        asset_input = "$SPX"

    if available_dates:
        selected_date = st.sidebar.selectbox("Seleccionar Expiración 0DTE", available_dates)

        if st.button(f"🚀 EJECUTAR ANÁLISIS FORENSE: {asset_raw}"):
            df_raw, df_net, spot, flip, move = fetch_full_data(asset_input, selected_date)
            
            if df_raw is not None:
                # --- KPI PANEL ---
                st.markdown('<div class="section-header">🧠 ESTRATEGIA 0DTE</div>', unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
                
                total_gex = df_raw['gex'].sum()
                c1.markdown(f'<div class="metric-card"><p class="kpi-label">TOTAL GEX</p><p class="{"gamma-pos" if total_gex > 0 else "gamma-neg"}">${total_gex/1e6:.1f}M</p></div>', unsafe_allow_html=True)
                c2.markdown(f'<div class="metric-card"><p class="kpi-label">EXPECTED MOVE (±)</p><p style="font-size:1.8rem; font-weight:bold; color:#3b82f6;">±{move:.2f}</p></div>', unsafe_allow_html=True)
                c3.markdown(f'<div class="metric-card"><p class="kpi-label">GAMMA FLIP</p><p class="flip-val">{flip:,.0f}</p></div>', unsafe_allow_html=True)
                status = "ESTABLE" if spot > flip else "VOLÁTIL"
                c4.markdown(f'<div class="metric-card"><p class="kpi-label">RÉGIMEN</p><p style="font-size:1.8rem; font-weight:bold; color:white;">{status}</p></div>', unsafe_allow_html=True)

                # --- GRÁFICA 1: NET GEX (LA ORIGINAL) ---
                st.markdown('<div class="section-header">📊 VISTA 1: EXPOSICIÓN NETA POR STRIKE (Soporte/Resistencia)</div>', unsafe_allow_html=True)
                
                # Zoom al 2% para ver detalle
                df_plot_net = df_net[(df_net['strike'] > spot * 0.98) & (df_net['strike'] < spot * 1.02)]
                
                fig1 = go.Figure()
                fig1.add_trace(go.Bar(
                    x=df_plot_net['strike'], y=df_plot_net['gex'],
                    marker_color=['#4ade80' if x > 0 else '#f87171' for x in df_plot_net['gex']],
                    name="Net GEX"
                ))
                fig1.add_vline(x=spot, line_dash="dash", line_color="yellow", annotation_text="SPOT")
                fig1.update_layout(template="plotly_dark", height=400, margin=dict(l=10, r=10, t=10, b=10),
                                   xaxis_title="Strike", yaxis_title="Net GEX ($)")
                st.plotly_chart(fig1, use_container_width=True)

                # --- GRÁFICA 2: CALL/PUT SPLIT (LA NUEVA) ---
                st.markdown('<div class="section-header">📊 VISTA 2: FLUJO DE CALLS VS PUTS & EXPECTED RANGE</div>', unsafe_allow_html=True)
                
                df_split = df_raw.groupby(['strike', 'type'])['gex'].sum().reset_index()
                df_plot_split = df_split[(df_split['strike'] > spot * 0.98) & (df_split['strike'] < spot * 1.02)]
                
                fig2 = go.Figure()
                # Calls
                c_data = df_plot_split[df_plot_split['type'] == 'call']
                fig2.add_trace(go.Bar(x=c_data['strike'], y=c_data['gex'], name="Call GEX (Vendedores)", marker_color='#4ade80', opacity=0.6))
                # Puts
                p_data = df_plot_split[df_plot_split['type'] == 'put']
                fig2.add_trace(go.Bar(x=p_data['strike'], y=p_data['gex'], name="Put GEX (Compradores)", marker_color='#f87171', opacity=0.6))
                
                # Sombras de Expected Move
                fig2.add_vrect(x0=spot-move, x1=spot+move, fillcolor="rgba(59, 130, 246, 0.1)", line_width=0, annotation_text="Exp. Move")
                fig2.add_vline(x=spot, line_dash="dash", line_color="white")
                fig2.add_vline(x=flip, line_dash="dot", line_color="#facc15", annotation_text="FLIP")

                fig2.update_layout(template="plotly_dark", barmode='relative', height=500, margin=dict(l=10, r=10, t=10, b=10),
                                   xaxis_title="Strike", yaxis_title="Individual GEX ($)")
                st.plotly_chart(fig2, use_container_width=True)
                
                st.success(f"Análisis completado para {asset_raw} el día {selected_date}. Spot actual: {spot:,.2f}")
    else:
        st.warning("No se encontraron fechas. Si usas SPX, asegúrate de tener permisos para índices o usa SPY.")
else:
    st.info("👈 Ingresa tu Token para comenzar.")
