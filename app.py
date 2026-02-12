import streamlit as st
import pandas as pd
import numpy as np

# Import the API functions from your other file
try:
    from walmart_api import fetch_wfs_inventory, fetch_recent_sales_velocity
except ImportError:
    st.error("Could not find 'walmart_api.py'. Please ensure it is in the same directory as 'app.py'.")
    st.stop()

# =========================================
# Page Configuration
# =========================================
st.set_page_config(
    page_title="WFS Stock Commander",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.title("📦 Real-Time WFS Stock Commander")

# =========================================
# Sidebar Settings & Controls
# =========================================
with st.sidebar:
    st.header("⚙️ Restock Settings")
    st.write("Configure thresholds to trigger 'SHIP NOW' alerts.")
    
    lead_time_input = st.slider(
        "Avg Lead Time (Days)", 
        min_value=1, max_value=90, value=14,
        help="Estimated days from placing a supplier order until it's received at WFS."
    )
    
    safety_buffer_input = st.slider(
        "Safety Buffer (Days)", 
        min_value=0, max_value=60, value=7,
        help="Additional days of stock required as a safety net against demand spikes or delays."
    )
    
    alert_threshold = lead_time_input + safety_buffer_input
    st.divider()
    st.metric("Alert Threshold", f"{alert_threshold} Days")
    st.info(f"A SKU becomes critical when its Days of Cover drops below {alert_threshold} days.")
    
    st.divider()
    # Button to clear cache and force fresh data fetch
    if st.button("🔄 Force Refresh Real Data", type="primary"):
        st.cache_data.clear()
        st.rerun()

# =========================================
# Data Loading & Processing Engine
# =========================================
with st.spinner('Connecting to Walmart API, fetching inventory, and calculating sales velocity...'):
    # 1. Fetch data using imported functions
    inventory_df = fetch_wfs_inventory()
    sales_velocity_df = fetch_recent_sales_velocity()

    if inventory_df is None or inventory_df.empty:
        st.warning("No WFS inventory data was retrieved. Please check your API connection or seller account.")
        st.stop()

    # 2. Merge Inventory and Sales Data
    # Use 'left' join to keep all inventory items, even if they have no recent sales
    merged_df = pd.merge(inventory_df, sales_velocity_df, on='SKU', how='left')
    
    # Fill NaN values for sales data with 0 for items with no recent orders
    merged_df[['Sales Last 7 Days', '7-Day Velocity (WADS)']] = merged_df[['Sales Last 7 Days', '7-Day Velocity (WADS)']].fillna(0)

    # 3. Calculate Days of Cover (DoC)
    # Formula: Current Stock / Average Daily Sales
    # Handle division by zero or extremely low velocity
    def calculate_doc(row):
        velocity = row['7-Day Velocity (WADS)']
        stock = row['Current Stock (WFS)']
        if velocity > 0.01: # Using a small threshold to avoid absurdly high DoC numbers
            return stock / velocity
        else:
            return 999 # Represents "infinite" cover for items not selling

    merged_df['Days of Cover'] = merged_df.apply(calculate_doc, axis=1)

    # 4. Determine Alert Status based on Sidebar Thresholds
    def define_status(doc):
        if doc <= alert_threshold:
            return "🔴 SHIP NOW"
        elif doc <= (alert_threshold + 7): # Warning zone is 1 week above threshold
            return "🟡 Warning"
        else:
            return "🟢 OK"

    merged_df['Status'] = merged_df['Days of Cover'].apply(define_status)
    
    # 5. Final Formatting for Display
    merged_df['7-Day Velocity (WADS)'] = merged_df['7-Day Velocity (WADS)'].round(2)
    # Cap Days of Cover display at 999 for cleaner UI
    merged_df['Days of Cover'] = merged_df['Days of Cover'].clip(upper=999).round(0).astype(int)
    
    # Sort by most critical items first
    final_df = merged_df.sort_values(by=['Days of Cover', 'Current Stock (WFS)'], ascending=[True, False])

# =========================================
# Dashboard Visualization
# =========================================

# --- Top-Level Scorecards ---
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total WFS Units Available", f"{final_df['Current Stock (WFS)'].sum():,}")
with col2:
    st.metric("Total Inbound Units", f"{final_df['Inbound Stock'].sum():,}")
with col3:
    st.metric("Total Units Sold (Last 7 Days)", f"{final_df['Sales Last 7 Days'].sum():,.0f}")
with col4:
    critical_count = final_df[final_df['Status'].str.contains("SHIP NOW")].shape[0]
    st.metric("🔴 Critical Restock SKUs", f"{critical_count}", delta_color="inverse")

st.divider()

# --- Main Inventory Health Table ---
st.subheader("Inventory Health by SKU")
st.caption(f"Days of Cover is calculated using the 7-Day Weighted Average Daily Sales (WADS). Threshold for alert: {alert_threshold} days.")

# Define a function to style the entire row based on its status
def highlight_row_status(row):
    status = row['Status']
    if "SHIP NOW" in status:
        # Light red background for critical items
        return ['background-color: #ffcccc; color: black'] * len(row)
    elif "Warning" in status:
        # Light yellow background for warning items
        return ['background-color: #fff4cc; color: black'] * len(row)
    else:
        # Default white background
        return ['background-color: white'] * len(row)

# Apply styling and format numbers
styled_df = final_df.style.apply(highlight_row_status, axis=1).format({
    "Current Stock (WFS)": "{:,}",
    "Inbound Stock": "{:,}",
    "Sales Last 7 Days": "{:,.0f}"
})

# Display the interactive dataframe
st.dataframe(
    styled_df,
    use_container_width=True,
    height=700,
    hide_index=True,
    column_order=("Status", "SKU", "Product Name", "Days of Cover", "Current Stock (WFS)", "Inbound Stock", "7-Day Velocity (WADS)", "Sales Last 7 Days"),
    column_config={
        "Status": st.column_config.TextColumn("Alert Status"),
        "Days of Cover": st.column_config.NumberColumn("Days of Cover", format="%d Days", help="How many days until stock runs out at current sales velocity."),
        "7-Day Velocity (WADS)": st.column_config.NumberColumn("Avg Daily Sales (7-Day)", help="Average units sold per day over the last week."),
        "Current Stock (WFS)": st.column_config.NumberColumn("Available Stock", help="Units currently fulfillable at WFS centers."),
    }
)