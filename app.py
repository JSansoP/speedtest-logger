import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import httpx
import os
from datetime import datetime

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:5000/api")

st.set_page_config(page_title="Speedtest Logger", layout="wide", page_icon="🚀")

st.title("🚀 Speedtest Logger Dashboard")

# Navigation
tabs = st.tabs(["📊 Dashboard", "📜 History", "🔔 Reports", "⚙️ Settings"])

def fetch_data(endpoint):
    try:
        response = httpx.get(f"{API_URL}/{endpoint}")
        if response.status_code == 200:
            return response.json()
        else:
            return {} if endpoint == "settings" else []
    except Exception as e:
        return {} if endpoint == "settings" else []

# --- DASHBOARD TAB ---
with tabs[0]:
    st.subheader("Latest Speed Performance")
    col1, col2 = st.columns([1, 1])
    
    data = fetch_data("speedtests")
    if data:
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        # Latest stats
        latest = df.iloc[-1]
        with col1:
            st.metric("Latest Download", f"{latest['download']:.2f} Mbps", delta=None)
        with col2:
            st.metric("Latest Upload", f"{latest['upload']:.2f} Mbps", delta=None)
            
        # Download/Upload Chart
        st.write("### Speed Over Time")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['download'], name="Download (Mbps)", line=dict(color="#00CC96", width=3), mode='lines+markers'))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['upload'], name="Upload (Mbps)", line=dict(color="#EF553B", width=3), mode='lines+markers'))
        fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)
        
        # Ping Chart
        st.write("### Latency (Ping)")
        fig_ping = px.line(df, x='timestamp', y='ping', title="Ping (ms)", template="plotly_dark")
        fig_ping.update_traces(line_color='#636EFA')
        st.plotly_chart(fig_ping, use_container_width=True)

    else:
        st.info("No speedtest data available. Running the first one now?")
    
    if st.button("🚀 Run Manual Speedtest"):
        try:
            httpx.post(f"{API_URL}/speedtests/run")
            st.success("Speedtest triggered in background! Refresh in a few moments.")
        except Exception as e:
            st.error(f"Failed to trigger speedtest: {e}")

# --- HISTORY TAB ---
with tabs[1]:
    st.subheader("Historical Data")
    if data:
        st.dataframe(df.sort_values('timestamp', ascending=False), use_container_width=True)
    else:
        st.info("No records found.")

# --- REPORTS TAB ---
with tabs[2]:
    st.subheader("Configure Reports")
    reports = fetch_data("reports")
    
    if reports:
        for r in reports:
            with st.expander(f"Report: {r['name']} ({r['type']})"):
                st.write(f"**Schedule:** {r['schedule']}")
                st.write(f"**Recipient:** {r['recipient']}")
                st.write(f"**Enabled:** {r['enabled']}")
                st.write(f"**Last Run:** {r['last_run']}")
    else:
        st.info("No reports configured yet.")
        
    st.markdown("---")
    st.write("### Create New Report")
    with st.form("new_report_form"):
        name = st.text_input("Report Name", placeholder="Daily Summary")
        type = st.selectbox("Type", ["telegram"])
        recipient = st.text_input("Recipient (Chat ID)")
        schedule = st.text_input("Schedule (Cron)", value="daily")
        
        if st.form_submit_button("💾 Save Report"):
            try:
                payload = {"name": name, "type": type, "recipient": recipient, "schedule": schedule}
                res = httpx.post(f"{API_URL}/reports", json=payload)
                if res.status_code == 201:
                    st.success("Report created!")
                else:
                    st.error("Failed to create report.")
            except Exception as e:
                st.error(f"Error: {e}")

# --- SETTINGS TAB ---
with tabs[3]:
    st.subheader("App Settings")
    st.info("Configure your Telegram bot and speedtest interval here.")
    
    current_settings = fetch_data("settings")
    if not isinstance(current_settings, dict):
        current_settings = {}

    has_env_token = current_settings.get("has_env_token", False)

    if has_env_token:
        st.success("✅ **Telegram Bot Token** is configured via environment variables (.env).")
        telegram_token = st.text_input(
            "Telegram Bot Token (Managed via ENV)", 
            value="********************", 
            disabled=True,
            type="password"
        )
    else:
        st.warning("⚠️ **Telegram Bot Token** is being stored in the database. Please use a .env file for better security.")
        telegram_token = st.text_input(
            "Telegram Bot Token", 
            value=current_settings.get("telegram_bot_token", ""), 
            type="password"
        )
        
    speedtest_interval = st.number_input(
        "Speedtest Interval (minutes)", 
        min_value=1, 
        value=int(current_settings.get("speedtest_interval", 60))
    )
    
    if st.button("💾 Save Settings"):
         try:
            payload = {
                "speedtest_interval": speedtest_interval
            }
            # Only add token to payload if it's NOT managed via ENV
            if not has_env_token:
                payload["telegram_bot_token"] = telegram_token
                
            res = httpx.post(f"{API_URL}/settings", json=payload)
            if res.status_code == 200:
                st.success("Settings updated!")
            else:
                st.error(f"Failed to update settings: {res.text}")
         except Exception as e:
            st.error(f"Error: {e}")
