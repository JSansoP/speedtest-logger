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
        # Per-row advertised download line (step shape)
        df_adv_down = df.dropna(subset=['advertised_download'])
        df_adv_down = df_adv_down[df_adv_down['advertised_download'] > 0]
        if not df_adv_down.empty:
            fig_down.add_trace(go.Scatter(
                x=df_adv_down['timestamp'], y=df_adv_down['advertised_download'],
                name="Advertised", line=dict(color="#FECB52", width=2, dash="dash"),
                line_shape='hv', mode='lines'
            ))
        fig_down.update_layout(**chart_layout)
        fig_down.update_yaxes(title_text="Mbps")
        st.plotly_chart(fig_down, use_container_width=True)

        # Upload Chart
        st.write("### Upload Speed")
        fig_up = go.Figure()
        fig_up.add_trace(go.Scatter(x=df['timestamp'], y=df['upload'], name="Upload", line=dict(color="#EF553B", width=3), mode='lines+markers'))
        # Per-row advertised upload line (step shape)
        df_adv_up = df.dropna(subset=['advertised_upload'])
        df_adv_up = df_adv_up[df_adv_up['advertised_upload'] > 0]
        if not df_adv_up.empty:
            fig_up.add_trace(go.Scatter(
                x=df_adv_up['timestamp'], y=df_adv_up['advertised_upload'],
                name="Advertised", line=dict(color="#FECB52", width=2, dash="dash"),
                line_shape='hv', mode='lines'
            ))
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

        # --- % of Advertised Speed Charts ---
        # Download % of Advertised
        df_pct_down = df.dropna(subset=['advertised_download']).copy()
        df_pct_down = df_pct_down[df_pct_down['advertised_download'] > 0]
        if not df_pct_down.empty:
            df_pct_down['download_pct'] = (df_pct_down['download'] / df_pct_down['advertised_download']) * 100

            st.write("### Download — % of Advertised Speed")
            fig_dl_pct = go.Figure()
            # 100% goal reference line
            fig_dl_pct.add_trace(go.Scatter(
                x=df_pct_down['timestamp'], y=[100] * len(df_pct_down),
                name="100 % Target", line=dict(color="#FECB52", width=2, dash="dash"),
                mode='lines', hoverinfo='skip'
            ))
            # Actual percentage line with fill towards goal
            fig_dl_pct.add_trace(go.Scatter(
                x=df_pct_down['timestamp'], y=df_pct_down['download_pct'],
                name="Download %", line=dict(color="#00CC96", width=3),
                mode='lines+markers', fill='tonexty',
                fillcolor='rgba(0,204,150,0.15)',
                hovertemplate='%{y:.1f}%<extra></extra>'
            ))
            fig_dl_pct.update_layout(**chart_layout)
            fig_dl_pct.update_yaxes(title_text="%", rangemode="tozero")
            st.plotly_chart(fig_dl_pct, use_container_width=True)

        # Upload % of Advertised
        df_pct_up = df.dropna(subset=['advertised_upload']).copy()
        df_pct_up = df_pct_up[df_pct_up['advertised_upload'] > 0]
        if not df_pct_up.empty:
            df_pct_up['upload_pct'] = (df_pct_up['upload'] / df_pct_up['advertised_upload']) * 100

            st.write("### Upload — % of Advertised Speed")
            fig_ul_pct = go.Figure()
            # 100% goal reference line
            fig_ul_pct.add_trace(go.Scatter(
                x=df_pct_up['timestamp'], y=[100] * len(df_pct_up),
                name="100 % Target", line=dict(color="#FECB52", width=2, dash="dash"),
                mode='lines', hoverinfo='skip'
            ))
            # Actual percentage line with fill towards goal
            fig_ul_pct.add_trace(go.Scatter(
                x=df_pct_up['timestamp'], y=df_pct_up['upload_pct'],
                name="Upload %", line=dict(color="#EF553B", width=3),
                mode='lines+markers', fill='tonexty',
                fillcolor='rgba(239,85,59,0.15)',
                hovertemplate='%{y:.1f}%<extra></extra>'
            ))
            fig_ul_pct.update_layout(**chart_layout)
            fig_ul_pct.update_yaxes(title_text="%", rangemode="tozero")
            st.plotly_chart(fig_ul_pct, use_container_width=True)

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
        df_sorted = df.sort_values('timestamp', ascending=False)

        # Show confirmation banner if a deletion is pending
        pending_id = st.session_state.get('confirm_delete_id', None)
        if pending_id is not None:
            pending_row = df[df['id'] == pending_id]
            if not pending_row.empty:
                ts = pending_row['timestamp'].iloc[0]
                st.warning(f"⚠️ Are you sure you want to delete the record from **{ts}** (ID {pending_id})?")
                col_yes, col_no, _ = st.columns([1, 1, 6])
                with col_yes:
                    if st.button("✅ Yes, Delete", key="confirm_yes"):
                        try:
                            res = httpx.delete(f"{API_URL}/history/{pending_id}")
                            if res.status_code == 200:
                                st.success(f"Record {pending_id} deleted!")
                                st.session_state.confirm_delete_id = None
                                st.rerun()
                            else:
                                st.error(f"Failed to delete record: {res.text}")
                        except Exception as e:
                            st.error(f"Error: {e}")
                with col_no:
                    if st.button("❌ Cancel", key="confirm_no"):
                        st.session_state.confirm_delete_id = None
                        st.rerun()

        total_rows = len(df_sorted)
        use_pagination = total_rows > 25

        # Pagination controls (rows per page selector)
        if use_pagination:
            pg_col1, pg_col2, pg_col3 = st.columns([2, 6, 2])
            with pg_col1:
                rows_per_page = st.selectbox(
                    "Rows per page",
                    options=[25, 50, 75, 100],
                    index=0,
                    key="history_rows_per_page",
                )
            # Reset page when rows_per_page changes
            if st.session_state.get('_prev_rows_per_page') != rows_per_page:
                st.session_state['history_page'] = 0
                st.session_state['_prev_rows_per_page'] = rows_per_page

            total_pages = max(1, -(-total_rows // rows_per_page))  # ceil division
            current_page = st.session_state.get('history_page', 0)
            current_page = min(current_page, total_pages - 1)

            start_idx = current_page * rows_per_page
            end_idx = min(start_idx + rows_per_page, total_rows)
            df_page = df_sorted.iloc[start_idx:end_idx]

            with pg_col3:
                st.markdown(f"**Showing {start_idx + 1}–{end_idx} of {total_rows}**")
        else:
            df_page = df_sorted

        # Render table with inline delete buttons
        header_cols = st.columns([2, 2, 2, 2, 2, 3, 1])
        headers = ["Timestamp", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)", "Advertised (DL/UL)", "Server", ""]
        for col, h in zip(header_cols, headers):
            col.markdown(f"**{h}**")

        for _, row in df_page.iterrows():
            cols = st.columns([2, 2, 2, 2, 2, 3, 1])
            cols[0].text(str(row['timestamp'].strftime('%Y-%m-%d %H:%M')))
            cols[1].text(f"{row['download']:.2f}")
            cols[2].text(f"{row['upload']:.2f}")
            cols[3].text(f"{row['ping']:.1f}")
            adv_dl = row.get('advertised_download')
            adv_ul = row.get('advertised_upload')
            if adv_dl and adv_ul:
                cols[4].text(f"{adv_dl:.0f} / {adv_ul:.0f}")
            elif adv_dl:
                cols[4].text(f"{adv_dl:.0f} / —")
            elif adv_ul:
                cols[4].text(f"— / {adv_ul:.0f}")
            else:
                cols[4].text("—")
            cols[5].text(str(row.get('server_name', '')))
            if cols[6].button("🗑️", key=f"del_row_{row['id']}"):
                st.session_state.confirm_delete_id = row['id']
                st.rerun()

        # Page navigation buttons
        if use_pagination:
            nav_col1, nav_col2, nav_col3 = st.columns([1, 6, 1])
            with nav_col1:
                if st.button("⬅️ Previous", disabled=(current_page == 0), key="history_prev"):
                    st.session_state['history_page'] = current_page - 1
                    st.rerun()
            with nav_col3:
                if st.button("Next ➡️", disabled=(current_page >= total_pages - 1), key="history_next"):
                    st.session_state['history_page'] = current_page + 1
                    st.rerun()
    else:
        st.info("No records found.")

# --- REPORTS TAB ---
with tabs[2]:
    st.subheader("Configure Reports")
    reports = fetch_data("reports")
    
    if reports:
        for r in reports:
            dw_label = {"last_day": "Last Day", "last_week": "Last Week", "last_month": "Last Month", "last_3_months": "Last 3 Months", "last_6_months": "Last 6 Months", "last_year": "Last Year"}.get(r.get('data_window', 'last_day'), 'Last Day')
            with st.expander(f"Report: {r['name']} ({r['type']}) · 📅 {dw_label} - {'🟢 Active' if r['enabled'] else '🔴 Disabled'}"):
                with st.form(f"edit_report_{r['id']}"):
                    new_name = st.text_input("Name", value=r['name'])
                    new_type = st.selectbox("Type", ["telegram"], index=0)
                    new_schedule = st.text_input("Schedule (Cron Expression, e.g. */30 * * * *)", value=r['schedule'])
                    data_window_options = ["last_day", "last_week", "last_month", "last_3_months", "last_6_months", "last_year"]
                    data_window_labels = {"last_day": "Last Day", "last_week": "Last Week", "last_month": "Last Month", "last_3_months": "Last 3 Months", "last_6_months": "Last 6 Months", "last_year": "Last Year"}
                    current_window = r.get('data_window', 'last_day')
                    new_data_window = st.selectbox("Data Window", data_window_options, index=data_window_options.index(current_window) if current_window in data_window_options else 0, format_func=lambda x: data_window_labels[x], key=f"dw_{r['id']}")
                    new_recipient = st.text_input("Recipient", value=r['recipient'])
                    new_enabled = st.checkbox("Enabled", value=r['enabled'])
                    
                    if st.form_submit_button("💾 Save Changes"):
                        try:
                            payload = {
                                "name": new_name, 
                                "type": new_type, 
                                "recipient": new_recipient, 
                                "schedule": new_schedule,
                                "data_window": new_data_window,
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
        schedule = st.text_input("Schedule (Cron Expression)", value="0 8 * * *", help="Examples: '*/2 * * * *' (every 2 min), '0 * * * *' (hourly), '0 8 * * *' (daily at 8 AM UTC)")
        data_window_options_new = ["last_day", "last_week", "last_month", "last_3_months", "last_6_months", "last_year"]
        data_window_labels_new = {"last_day": "Last Day", "last_week": "Last Week", "last_month": "Last Month", "last_3_months": "Last 3 Months", "last_6_months": "Last 6 Months", "last_year": "Last Year"}
        data_window = st.selectbox("Data Window", data_window_options_new, index=0, format_func=lambda x: data_window_labels_new[x], help="Time window of speedtest data to include in the report")
        
        if st.form_submit_button("💾 Save Report"):
            try:
                payload = {"name": name, "type": type, "recipient": recipient, "schedule": schedule, "data_window": data_window}
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
    st.caption("The speed your ISP promises in your plan. When set, a reference line will appear on the Dashboard charts, and extra statistics will be displayed in the reports.")
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
