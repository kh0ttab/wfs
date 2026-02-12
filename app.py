import requests
import base64
import uuid
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
import time

# Base URL for Walmart APIs (Production)
BASE_URL = "https://marketplace.walmartapis.com"

# ===========================
# 1. AUTHENTICATION
# ===========================
def get_access_token():
    """Exchanges Client ID/Secret from st.secrets for a temporary Bearer Token."""
    try:
        # Securely access keys from secrets.toml or Streamlit Cloud secrets
        client_id = st.secrets["walmart"]["client_id"]
        client_secret = st.secrets["walmart"]["client_secret"]
    except KeyError:
        st.error("Critical Error: Walmart credentials not found. Please check your `.streamlit/secrets.toml` file or Streamlit Cloud secrets configuration.")
        st.stop()

    url = f"{BASE_URL}/v3/token"
    
    # Walmart requires Basic Auth with Base64 encoded ID:Secret
    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()), # Unique ID required by Walmart for tracking
        "WM_SVC.NAME": "WFS_Streamlit_App",
        "Accept": "application/json",
    }

    data = {
        "grant_type": "client_credentials"
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status() # Raise exception for 4xx/5xx status codes
        token_data = response.json()
        return token_data['access_token']
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to authenticate with Walmart API: {e}")
        # Only try to show response text if the variable exists
        if 'response' in locals() and response is not None and response.text:
             with st.expander("See API Error Response"):
                 st.code(response.text)
        st.stop()


def get_standard_headers(token):
    """Helper to create headers needed for subsequent API calls using the token."""
    return {
        "WM_SEC.ACCESS_TOKEN": token,
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "WM_SVC.NAME": "WFS_Streamlit_App",
        "Accept": "application/json",
    }

# ===========================
# 2. FETCH WFS INVENTORY (WITH PAGINATION - STABLE NO UI)
# ===========================
@st.cache_data(ttl=1800) # Cache data for 30 minutes
def fetch_wfs_inventory():
    """Fetches ALL WFS inventory by paginating through results."""
    token = get_access_token()
    headers = get_standard_headers(token)
    url = f"{BASE_URL}/v3/fulfillment/inventory"
    
    all_items = []
    offset = 0
    limit = 50 # Fetch 50 items per page
    total_count = 1 # Initialize to enter the loop
    
    # NO ST.EMPTY OR UI ELEMENTS HERE

    try:
        while offset < total_count:
            # NO ST.INFO HERE

            params = {
                "offset": offset,
                "limit": limit
            }
            
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Get total count from the first response header
            if offset == 0:
                total_count = data.get('headers', {}).get('totalCount', 0)
                if total_count == 0:
                    return pd.DataFrame()

            # Extract items from the current page
            items_on_page = data.get('payload', {}).get('inventory', [])
            if not items_on_page:
                break # Stop if no more items are returned
                
            all_items.extend(items_on_page)
            
            # Prepare for next page
            offset += limit
            time.sleep(0.2) # Be polite to the API
            
            # Safety break
            if offset > 15000: 
                break

        # NO ST.SUCCESS HERE

        # ---- PROCESS ALL COLLECTED DATA ----
        processed_data = []
        for item in all_items:
            # Each item has a list of 'shipNodes'. We get stock from the first one.
            ship_nodes = item.get('shipNodes', [])
            current_stock = 0
            
            if ship_nodes:
                # The first node's availToSellQty is the current stock
                current_stock = ship_nodes[0].get('availToSellQty', 0)
            
            processed_data.append({
                "SKU": item.get('sku'),
                # The API response doesn't include product name, use SKU as fallback
                "Product Name": item.get('sku', 'N/A'), 
                "Current Stock (WFS)": current_stock,
                "Inbound Stock": 0
            })
            
        return pd.DataFrame(processed_data)

    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching WFS inventory: {e}")
        if 'response' in locals() and response is not None and response.text:
             with st.expander("See API Error Response"):
                 st.code(response.text)
        st.stop()
    except Exception as e:
        st.error(f"An unexpected error occurred processing inventory data: {e}")
        st.stop()

# ===========================
# 3. FETCH SALES HISTORY (STABLE NO UI)
# ===========================
@st.cache_data(ttl=3600) # Cache for 1 hour
def fetch_recent_sales_velocity():
    """Fetches orders from last 7 days to calculate WADS per SKU."""
    token = get_access_token()
    headers = get_standard_headers(token)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    # Walmart API date format: YYYY-MM-DD
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    # Orders endpoint
    url = f"{BASE_URL}/v3/orders"
    params = {
        "createdStartDate": start_str,
        "createdEndDate": end_str,
        "limit": 200 # Fetch up to 200 orders (first page only for now)
    }

    all_order_lines = []

    try:
        # NOTE: This version fetches only the first page of 200 orders.
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Navigate the JSON structure to find order lists
        orders = data.get('list', {}).get('elements', {}).get('order', [])
        
        if not orders:
            return pd.DataFrame(columns=['SKU', 'Sales Last 7 Days', '7-Day Velocity (WADS)'])

        for order in orders:
            # An order can have multiple lines (different SKUs)
            lines = order.get('orderLines', {}).get('orderLine', [])
            for line in lines:
                sku = line.get('item', {}).get('sku')
                qty = int(line.get('orderLineQuantity', {}).get('amount', 0))
                status = line.get('orderLineStatus')

                # Exclude cancelled lines to get accurate sales numbers
                if status != 'Cancelled' and sku:
                    all_order_lines.append({
                        "SKU": sku,
                        "QtySold": qty
                    })
                
        df_sales = pd.DataFrame(all_order_lines)
        
        if df_sales.empty:
             return pd.DataFrame(columns=['SKU', 'Sales Last 7 Days', '7-Day Velocity (WADS)'])

        # Group by SKU to get total sales quantity for the 7-day period
        grouped_sales = df_sales.groupby('SKU')['QtySold'].sum().reset_index()
        grouped_sales.rename(columns={'QtySold': 'Sales Last 7 Days'}, inplace=True)
        
        # Calculate WADS (Weekly Average Daily Sales)
        grouped_sales['7-Day Velocity (WADS)'] = grouped_sales['Sales Last 7 Days'] / 7
        
        return grouped_sales

    except requests.exceptions.RequestException as e:
        st.warning(f"Could not fetch sales history from API: {e}. Velocity metrics will be set to 0.")
        if 'response' in locals() and response is not None and response.text:
             with st.expander("See API Error Response"):
                 st.code(response.text)
        # Return empty dataframe so app can continue running
        return pd.DataFrame(columns=['SKU', 'Sales Last 7 Days', '7-Day Velocity (WADS)'])
    except Exception as e:
        st.error(f"An unexpected error occurred processing sales data: {e}")
        st.stop()
