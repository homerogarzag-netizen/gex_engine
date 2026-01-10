import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(layout="wide", page_title="0DTE CEO Command Center", page_icon="⚡")

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
        color: white; padding: 12px 20px; 
        border-radius: 8px; margin: 25px 0 10px 0; font-size: 1.3rem; font-weight: bold;
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
    asset_raw = st.text_input("Activo (Ej: SPX, SPY, TSLA)", value="SPX").upper().strip()
    
    st.divider()
    st.caption("v1.8.0 | Precision Zoom & SPX Root Fix")

def get_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- MOTOR DE DATOS (REFORZADO PARA SPX) ---
def get_all_expirations(symbol):
    roots = ["$SPX", "$SPXW"] if symbol == "SPX" else [symbol]
    all_dates = []
    for r in roots:
        try:
            res = requests.get(f"{BASE_URL}/markets/options/expirations", 
                             params={'symbol': r, 'includeAllRoots': 'true'}, headers=get_headers())
            dates = res.json().get('expirations', {}).get('date', [])
            if isinstance(dates, str): dates = [dates]
            all_dates.extend(dates)
        except: continue
    return sorted(list(set(all_dates)))

def fetch_precision_data(symbol, target_date):
    try:
        # 1. Determinar el símbolo real (SPX vs SPXW)
        search_sym = symbol
        if symbol == "SPX":
            # Si el usuario puso SPX, buscamos el spot en $SPX pero las opciones pueden ser $SPXW
            search_sym = "$SPX"
            
        r_q = requests.get(f"{BASE_URL}/markets/quotes", params={'symbols': search_sym, 'greeks': 'true'}, headers=get_headers())
        q = r_q.json()['quotes']['quote']
        spot = float(q['last'])
        iv = float(q.get('ask_iv', 0.15))

        # 2. Intentar descargar la cadena de opciones
        # Probamos con el símbolo tal cual, y si falla y es SPX, probamos con $SPXW
        roots_to_try = ["$SPXW", "$SPX"] if symbol == "SPX" else [symbol]
        options = []
        for r in roots_to_try:
            r_c = requests.get(f"{BASE_URL}/markets/options/chains", 
                               params={'symbol': r, 'expiration': target_date, 'greeks': 'true'}, headers=get_headers())
            opts = r_c.json().get('options', {}).get('option', [])
            if opts and opts != 'null':
                options = [opts] if isinstance(opts, dict) else opts
                break

        if not options: return None, None, 0, 0, 0

        data = []
        for opt in options:
            if not opt.get('greeks'): continue
            strike = float(opt['strike'])
            gamma = float(opt['greeks'].get('gamma', 0))
            oi = int(opt.get('open_interest', 0))
            o_type = opt['option_type'].lower()
            gex = gamma * oi * 100 * spot * (spot * 0.01)
            if o_type == 'put': gex *= -1
            data.append({'strike': strike, 'gex': gex, 'type': o_type})

        df = pd.DataFrame(data)
        df_net = df.groupby('strike')['gex'].sum().reset_index().sort_values('strike')
        
        # Gamma Flip
        flip_row = df_net[df_net['gex'] > 0].iloc[0] if not df_net[df_net['gex'] > 0].empty else df_net.iloc[0]
        gamma_flip = flip_row['strike']
        
        # Expected Move
        expected_move = spot * (iv / 15.87) 
        
        return df, df_net, spot, gamma_flip, expected_move
    except: return None, None, 0, 0, 0

# --- INTERFAZ ---
if TOKEN:
    available_dates = get_all_expirations(asset_raw)
    
    if available_dates:
        selected_date = st.sidebar.selectbox("📅 Seleccionar Fecha", available_dates)

        if st.button(f"🚀 ANALIZAR {asset_raw} ({selected_date})"):
            df_raw, df_net, spot, flip, move = fetch_precision_data(asset_raw, selected_date)
            
            if df_raw is not None:
                # --- KPI PANEL ---
                st.markdown('<div class="section-header">🧠 MÉTRICAS DE ESTRATEGIA</div>', unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
                
                total_gex = df_raw['gex'].sum()
                c1.markdown(f'<div class="metric-card"><p class="kpi-label">TOTAL GEX</p><p class="{"gamma-pos" if total_gex > 0 else "gamma-neg"}">${total_gex/1e6:.1f}M</p></div>', unsafe_allow_html=True)
                c2.markdown(f'<div class="metric-card"><p class="kpi-label">EXPECTED MOVE (±)</p><p style="font-size:1.8rem; font-weight:bold; color:#3b82f6;">±{move:.2f}</p></div>', unsafe_allow_html=True)
                c3.markdown(f'<div class="metric-card"><p class="kpi-label">GAMMA FLIP</p><p class="flip-val">{flip:,.1f}</p></div>', unsafe_allow_html=True)
                status = "CALMA" if spot > flip else "TURBULENCIA"
                c4.markdown(f'<div class="metric-card"><p class="kpi-label">RÉGIMEN</p><p style="font-size:1.8rem; font-weight:bold; color:white;">{status}</p></div>', unsafe_allow_html=True)

                # RANGO DE ZOOM (Para que no se vea empalmado)
                # Mostramos solo +/- 2 veces el movimiento esperado para ver los strikes cercanos
                plot_range = [spot - (move * 3), spot + (move * 3)]

                # --- GRÁFICA 1: NET GEX ---
                st.markdown('<div class="section-header">📊 VISTA 1: SOPORTES Y RESISTENCIAS NETOS</div>', unsafe_allow_html=True)
                
                fig1 = go.Figure()
                fig1.add_trace(go.Bar(
                    x=df_net['strike'], y=df_net['gex'],
                    marker_color=['#4ade80' if x > 0 else '#f87171' for x in df_net['gex']],
                    name="Net GEX"
                ))
                fig1.add_vline(x=spot, line_dash="dash", line_color="yellow", 
                             annotation_text=f"SPOT: {spot:,.2f}", annotation_font_size=14)
                
                fig1.update_layout(
                    template="plotly_dark", height=450,
                    xaxis=dict(range=plot_range, title="Strike Price", tickfont=dict(size=12)),
                    yaxis=dict(title="GEX ($)", tickfont=dict(size=12)),
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                st.plotly_chart(fig1, use_container_width=True)

                # --- GRÁFICA 2: SPLIT GEX CON ZOOM DINÁMICO ---
                st.markdown('<div class="section-header">📊 VISTA 2: COMPOSICIÓN CALL/PUT & RANGO ESPERADO</div>', unsafe_allow_html=True)
                
                df_split = df_raw.groupby(['strike', 'type'])['gex'].sum().reset_index()
                
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(x=df_split[df_split['type']=='call']['strike'], 
                                      y=df_split[df_split['type']=='call']['gex'], 
                                      name="Calls", marker_color='#4ade80', opacity=0.7))
                fig2.add_trace(go.Bar(x=df_split[df_split['type']=='put']['strike'], 
                                      y=df_split[df_split['type']=='put']['gex'], 
                                      name="Puts", marker_color='#f87171', opacity=0.7))
                
                # Sombreado del Expected Move
                fig2.add_vrect(x0=spot-move, x1=spot+move, fillcolor="rgba(59, 130, 246, 0.15)", 
                             line_width=0, annotation_text="AREA DE ALTA PROBABILIDAD", annotation_position="top left")
                
                fig2.add_vline(x=spot, line_dash="dash", line_color="white")
                # Solo mostrar la línea del flip si está cerca del spot
                if flip > plot_range[0] and flip < plot_range[1]:
                    fig2.add_vline(x=flip, line_dash="dot", line_color="#facc15", annotation_text="FLIP")

                fig2.update_layout(
                    template="plotly_dark", barmode='relative', height=550,
                    xaxis=dict(range=plot_range, title="Strike Price", 
                               rangeslider=dict(visible=True), # CONTROL DE ZOOM TIPO TV
                               tickfont=dict(size=12)),
                    yaxis=dict(title="GEX ($)"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig2, use_container_width=True)
                
                st.caption("💡 Tip: Usa el deslizador debajo de la segunda gráfica para ajustar el zoom como en TradingView.")
    else:
        st.error("No se detectaron fechas. Intenta escribir 'SPX' o 'SPY' y dale a Enter.")
else:
    st.info("👈 Ingresa tu Token para comenzar.")
