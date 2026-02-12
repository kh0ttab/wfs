import streamlit as st
import pandas as pd

# Import the API functions from your other file
try:
    from walmart_api import fetch_wfs_inventory, fetch_recent_sales_velocity
except ImportError:
    st.error("Could not find 'walmart_api.py'. Please ensure it is in the same directory.")
    st.stop()

# Page Config
st.set_page_config(page_title="WFS Stock Commander", layout="wide")
st.title("📦 Real-Time WFS Stock Commander")

# Sidebar
with st.sidebar:
    st.header("⚙️ Restock Settings")
    lead_time = st.slider("Lead Time (Days)", 1, 90, 14)
    buffer = st.slider("Safety Buffer (Days)", 0, 60, 7)
    threshold = lead_time + buffer
    st.metric("Alert Threshold", f"{threshold} Days")
    
    st.divider()
    if st.button("🔄 Force Refresh Data", type="primary"):
        st.cache_data.clear()
        st.rerun()

# Main Logic
with st.spinner('Connecting to Walmart API...'):
    # 1. Get Data
    inv_df = fetch_wfs_inventory()
    sales_df = fetch_recent_sales_velocity()

    if inv_df is None or inv_df.empty:
        st.warning("No WFS inventory data found.")
        st.stop()

    # 2. Merge
    df = pd.merge(inv_df, sales_df, on='SKU', how='left')
    df[['Sales Last 7 Days', '7-Day Velocity (WADS)']] = df[['Sales Last 7 Days', '7-Day Velocity (WADS)']].fillna(0)

    # 3. Calculate Metrics
    def calc_doc(row):
        velocity = row['7-Day Velocity (WADS)']
        stock = row['Current Stock (WFS)']
        if velocity > 0.01:
            return stock / velocity
        return 999

    df['Days of Cover'] = df.apply(calc_doc, axis=1)

    def get_status(doc):
        if doc <= threshold: return "🔴 SHIP NOW"
        if doc <= (threshold + 7): return "🟡 Warning"
        return "🟢 OK"

    df['Status'] = df['Days of Cover'].apply(get_status)
    
    # 4. Cleanup
    df['7-Day Velocity (WADS)'] = df['7-Day Velocity (WADS)'].round(2)
    df['Days of Cover'] = df['Days of Cover'].clip(upper=999).astype(int)
    final_df = df.sort_values(by=['Days of Cover', 'Current Stock (WFS)'], ascending=[True, False])

# Display Scorecards
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Units", f"{final_df['Current Stock (WFS)'].sum():,}")
c2.metric("Inbound", f"{final_df['Inbound Stock'].sum():,}")
c3.metric("7-Day Sales", f"{final_df['Sales Last 7 Days'].sum():,.0f}")
critical = final_df[final_df['Status'].str.contains("SHIP NOW")].shape[0]
c4.metric("Critical SKUs", f"{critical}", delta_color="inverse")

# Display Table
def highlight(row):
    if "SHIP NOW" in row['Status']: return ['background-color: #ffcccc; color: black'] * len(row)
    if "Warning" in row['Status']: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

st.subheader("Inventory Health")
st.dataframe(
    final_df.style.apply(highlight, axis=1),
    use_container_width=True,
    height=700,
    hide_index=True,
    column_order=("Status", "SKU", "Days of Cover", "Current Stock (WFS)", "7-Day Velocity (WADS)", "Sales Last 7 Days")
)
