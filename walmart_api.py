import requests
import base64
import uuid
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
import time

# Base URL for Walmart APIs
BASE_URL = "https://marketplace.walmartapis.com"

# ===========================
# 1. AUTHENTICATION
# ===========================
def get_access_token():
    try:
        client_id = st.secrets["walmart"]["client_id"]
        client_secret = st.secrets["walmart"]["client_secret"]
    except KeyError:
        st.error("Critical Error: Walmart credentials not found in secrets.")
        st.stop()

    url = f"{BASE_URL}/v3/token"
    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "WM_SVC.NAME": "WFS_Streamlit_App",
        "Accept": "application/json",
    }
    
    try:
        response = requests.post(url, headers=headers, data={"grant_type": "client_credentials"})
        response.raise_for_status()
        return response.json()['access_token']
    except Exception as e:
        st.error(f"Authentication Failed: {e}")
        st.stop()

def get_standard_headers(token):
    return {
        "WM_SEC.ACCESS_TOKEN": token,
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "WM_SVC.NAME": "WFS_Streamlit_App",
        "Accept": "application/json",
    }

# ===========================
# 2. FETCH INVENTORY (ROBUST DEBUG VERSION)
# ===========================
@st.cache_data(ttl=1800)
def fetch_wfs_inventory():
    token = get_access_token()
    headers = get_standard_headers(token)
    url = f"{BASE_URL}/v3/fulfillment/inventory"
    
    all_items = []
    offset = 0
    limit = 50 
    
    try:
        while True:
            params = {"offset": offset, "limit": limit}
            response = requests.get(url, headers=headers, params=params)
            
            # --- DEBUG BLOCK START ---
            # If we get an empty response or non-JSON, handle it gracefully
            if not response.text:
                # If it's the first page and empty, assume no inventory
                if offset == 0:
                    return pd.DataFrame()
                break # Stop loop if empty
            # --- DEBUG BLOCK END ---

            response.raise_for_status()
            
            try:
                data = response.json()
            except ValueError:
                st.warning(f"Walmart API Error: Received invalid JSON. Status: {response.status_code}")
                # Optional: Show raw text if debugging needed (comment out for production)
                # st.code(response.text) 
                break

            # Check total count on first run
            if offset == 0 and data.get('headers', {}).get('totalCount', 0) == 0:
                return pd.DataFrame()

            items = data.get('payload', {}).get('inventory', [])
            if not items:
                break
                
            all_items.extend(items)
            offset += limit
            time.sleep(0.1) # Brief pause
            
            if offset > 10000: break # Safety limit

        # Process data
        processed = []
        for item in all_items:
            stock = 0
            if item.get('shipNodes'):
                stock = item['shipNodes'][0].get('availToSellQty', 0)
            
            processed.append({
                "SKU": item.get('sku'),
                "Product Name": item.get('sku', 'N/A'),
                "Current Stock (WFS)": stock,
                "Inbound Stock": 0
            })
            
        return pd.DataFrame(processed)

    except Exception as e:
        st.error(f"Inventory Fetch Error: {e}")
        st.stop()

# ===========================
# 3. FETCH SALES (ROBUST DEBUG VERSION)
# ===========================
@st.cache_data(ttl=3600)
def fetch_recent_sales_velocity():
    token = get_access_token()
    headers = get_standard_headers(token)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    url = f"{BASE_URL}/v3/orders"
    
    params = {
        "createdStartDate": start_date.strftime('%Y-%m-%d'),
        "createdEndDate": end_date.strftime('%Y-%m-%d'),
        "limit": 200
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        
        # Check for empty response
        if not response.text:
            return pd.DataFrame(columns=['SKU', 'Sales Last 7 Days', '7-Day Velocity (WADS)'])

        response.raise_for_status()
        data = response.json()
        
        orders = data.get('list', {}).get('elements', {}).get('order', [])
        sales_data = []

        for order in orders:
            for line in order.get('orderLines', {}).get('orderLine', []):
                if line.get('orderLineStatus') != 'Cancelled':
                    sales_data.append({
                        "SKU": line.get('item', {}).get('sku'),
                        "QtySold": int(line.get('orderLineQuantity', {}).get('amount', 0))
                    })
        
        df = pd.DataFrame(sales_data)
        if df.empty:
            return pd.DataFrame(columns=['SKU', 'Sales Last 7 Days', '7-Day Velocity (WADS)'])
            
        grouped = df.groupby('SKU')['QtySold'].sum().reset_index()
        grouped.rename(columns={'QtySold': 'Sales Last 7 Days'}, inplace=True)
        grouped['7-Day Velocity (WADS)'] = grouped['Sales Last 7 Days'] / 7
        
        return grouped

    except Exception as e:
        # Return empty on error so app doesn't crash
        return pd.DataFrame(columns=['SKU', 'Sales Last 7 Days', '7-Day Velocity (WADS)'])
