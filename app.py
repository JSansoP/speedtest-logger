import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
    
    # Fetch settings for advertised speed lines
    dashboard_settings = fetch_data("settings")
    advertised_download = float(dashboard_settings.get("advertised_download", 0) or 0)
    advertised_upload = float(dashboard_settings.get("advertised_upload", 0) or 0)
    
    data = fetch_data("speedtests")
    if data:
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        # Latest stats & Aggregate stats
        st.write("### Speed Statistics (All Time)")
        col_down, col_med, col_std, col_up = st.columns(4)
        
        latest = df.iloc[-1]
        down_latest = latest['download']
        down_avg = df['download'].mean()
        down_med = df['download'].median()
        down_std = df['download'].std()

        up_latest = latest['upload']
        up_avg = df['upload'].mean()
        up_med = df['upload'].median()
        up_std = df['upload'].std()
        
        with col_down:
            st.metric("Latest Download", f"{down_latest:.2f} Mbps")
            st.metric("Latest Upload", f"{up_latest:.2f} Mbps")
        with col_med:
            st.metric("Avg Download", f"{down_avg:.2f} Mbps")
            st.metric("Avg Upload", f"{up_avg:.2f} Mbps")
        with col_std:
            st.metric("Median Download", f"{down_med:.2f} Mbps")
            st.metric("Median Upload", f"{up_med:.2f} Mbps")
        with col_up:
            st.metric("Std Dev Download", f"{down_std:.2f} Mbps")
            st.metric("Std Dev Upload", f"{up_std:.2f} Mbps")
            
        # Shared layout
        chart_layout = dict(template="plotly_dark", height=300, margin=dict(l=60, r=20, t=40, b=20))
        
        # Download Chart
        st.write("### Download Speed")
        fig_down = go.Figure()
        fig_down.add_trace(go.Scatter(x=df['timestamp'], y=df['download'], name="Download", line=dict(color="#00CC96", width=3), mode='lines+markers'))
        if advertised_download > 0:
            fig_down.add_hline(
                y=advertised_download,
                line_dash="dash",
                line_color="#FECB52",
                line_width=2,
                annotation_text=f"Advertised: {advertised_download} Mbps",
                annotation_position="top left",
                annotation_font_color="#FECB52",
            )
        fig_down.update_layout(**chart_layout)
        fig_down.update_yaxes(title_text="Mbps")
        st.plotly_chart(fig_down, use_container_width=True)

        # Upload Chart
        st.write("### Upload Speed")
        fig_up = go.Figure()
        fig_up.add_trace(go.Scatter(x=df['timestamp'], y=df['upload'], name="Upload", line=dict(color="#EF553B", width=3), mode='lines+markers'))
        if advertised_upload > 0:
            fig_up.add_hline(
                y=advertised_upload,
                line_dash="dash",
                line_color="#FECB52",
                line_width=2,
                annotation_text=f"Advertised: {advertised_upload} Mbps",
                annotation_position="top left",
                annotation_font_color="#FECB52",
            )
        fig_up.update_layout(**chart_layout)
        fig_up.update_yaxes(title_text="Mbps")
        st.plotly_chart(fig_up, use_container_width=True)

        # Ping Chart
        st.write("### Latency (Ping)")
        fig_ping = go.Figure()
        fig_ping.add_trace(go.Scatter(x=df['timestamp'], y=df['ping'], name="Ping", line=dict(color="#636EFA", width=3), mode='lines+markers'))
        fig_ping.update_layout(**chart_layout)
        fig_ping.update_yaxes(title_text="ms")
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

    col1, col2 = st.columns([8, 2])
    with col2:
        if st.button("🗑️ Delete All Data", type="primary"):
            st.session_state.confirm_delete_all = True
            
    if st.session_state.get('confirm_delete_all', False):
        st.warning("⚠️ Are you extremely sure you want to delete ALL data? This action cannot be undone.")
        col_y, col_n = st.columns([1, 1])
        with col_y:
            if st.button("Yes, Delete Everything", type="primary"):
                try:
                    res = httpx.delete(f"{API_URL}/history/all")
                    if res.status_code == 200:
                        st.success("All data deleted!")
                        st.session_state.confirm_delete_all = False
                        st.rerun()
                    else:
                        st.error("Failed to delete records.")
                except Exception as e:
                    st.error(f"Error: {e}")
        with col_n:
            if st.button("Cancel"):
                st.session_state.confirm_delete_all = False
                st.rerun()
                
    if data:
        st.dataframe(df.sort_values('timestamp', ascending=False), use_container_width=True)
        
        st.markdown("---")
        st.write("### Delete Specific Record")
        col_del1, col_del2 = st.columns([3, 1])
        with col_del1:
            record_to_delete = st.selectbox(
                "Select record by ID", 
                options=df['id'].tolist(), 
                format_func=lambda x: f"ID: {x} - {df[df['id']==x]['timestamp'].iloc[0]}"
            )
        with col_del2:
            st.write("") # spacer
            st.write("")
            if st.button("🗑️ Delete Record"):
                try:
                    res = httpx.delete(f"{API_URL}/history/{record_to_delete}")
                    if res.status_code == 200:
                        st.success(f"Record {record_to_delete} deleted!")
                        st.rerun()
                    else:
                        st.error(f"Failed to delete record: {res.text}")
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        st.info("No records found.")

# --- REPORTS TAB ---
with tabs[2]:
    st.subheader("Configure Reports")
    reports = fetch_data("reports")
    
    if reports:
        for r in reports:
            with st.expander(f"Report: {r['name']} ({r['type']}) - {'🟢 Active' if r['enabled'] else '🔴 Disabled'}"):
                with st.form(f"edit_report_{r['id']}"):
                    new_name = st.text_input("Name", value=r['name'])
                    new_type = st.selectbox("Type", ["telegram"], index=0)
                    new_schedule = st.text_input("Schedule (e.g. daily, hourly, interval:60)", value=r['schedule'])
                    new_recipient = st.text_input("Recipient", value=r['recipient'])
                    new_enabled = st.checkbox("Enabled", value=r['enabled'])
                    
                    if st.form_submit_button("💾 Save Changes"):
                        try:
                            payload = {
                                "name": new_name, 
                                "type": new_type, 
                                "recipient": new_recipient, 
                                "schedule": new_schedule,
                                "enabled": new_enabled
                            }
                            res = httpx.put(f"{API_URL}/reports/{r['id']}", json=payload)
                            if res.status_code == 200:
                                st.success("Report updated!")
                                st.rerun()
                            else:
                                st.error("Failed to update report.")
                        except Exception as e:
                            st.error(f"Error: {e}")
                
                if st.button("🗑️ Delete Report", key=f"del_{r['id']}"):
                    try:
                        res = httpx.delete(f"{API_URL}/reports/{r['id']}")
                        if res.status_code == 200:
                            st.success("Report deleted!")
                            st.rerun()
                        else:
                            st.error("Failed to delete report.")
                    except Exception as e:
                        st.error(f"Error: {e}")
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

    st.markdown("---")
    st.write("### 📶 Advertised Speed")
    st.caption("The speed your ISP promises in your plan. When set, a reference line will appear on the Dashboard charts.")
    col_adv_down, col_adv_up = st.columns(2)
    with col_adv_down:
        advertised_download_setting = st.number_input(
            "Advertised Download (Mbps)",
            min_value=0.0,
            step=1.0,
            value=float(current_settings.get("advertised_download", 0) or 0),
            help="Set to 0 to hide the reference line"
        )
    with col_adv_up:
        advertised_upload_setting = st.number_input(
            "Advertised Upload (Mbps)",
            min_value=0.0,
            step=1.0,
            value=float(current_settings.get("advertised_upload", 0) or 0),
            help="Set to 0 to hide the reference line"
        )
    
    if st.button("💾 Save Settings"):
         try:
            payload = {
                "speedtest_interval": speedtest_interval,
                "advertised_download": advertised_download_setting,
                "advertised_upload": advertised_upload_setting,
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
