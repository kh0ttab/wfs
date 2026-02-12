# ===========================
# 2. FETCH WFS INVENTORY (STABLE - NO UI IN CACHE)
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
    
    # --- NO UI COMMANDS HERE ---

    try:
        while offset < total_count:
            params = {
                "offset": offset,
                "limit": limit
            }
            
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if offset == 0:
                total_count = data.get('headers', {}).get('totalCount', 0)
                if total_count == 0:
                    return pd.DataFrame()

            items_on_page = data.get('payload', {}).get('inventory', [])
            if not items_on_page:
                break 
                
            all_items.extend(items_on_page)
            offset += limit
            time.sleep(0.2)
            
            if offset > 15000: 
                break

        # --- NO UI COMMANDS HERE ---

        processed_data = []
        for item in all_items:
            ship_nodes = item.get('shipNodes', [])
            current_stock = 0
            if ship_nodes:
                current_stock = ship_nodes[0].get('availToSellQty', 0)
            
            processed_data.append({
                "SKU": item.get('sku'),
                "Product Name": item.get('sku', 'N/A'), 
                "Current Stock (WFS)": current_stock,
                "Inbound Stock": 0
            })
            
        return pd.DataFrame(processed_data)

    except Exception as e:
        # It is okay to have st.error here as it stops execution
        st.error(f"An error occurred: {e}")
        st.stop()
