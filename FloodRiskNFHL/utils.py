import time
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

from numpy import save
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

import folium
from folium import GeoJson, CircleMarker
from branca.element import Template, MacroElement


# def prep_mock_data_ny_albany():
#     assets_ny_albany_csv = [
#         [1, "1 Quay St, Albany, NY 12207", "Waterfront warehouse near Hudson River", 42.6448, -73.7502],
#         [2, "140 State St, Albany, NY 12207", "New York State Capitol", 42.6495, -73.7572],
#         [3, "44 Holland Ave, Albany, NY 12229", "NYS Department of Health", 42.6440, -73.7830],
#         [4, "183 Schoolhouse Rd, Albany, NY 12203", "183 Schoolhouse Rd, Albany, NY 12203", 42.6955, -73.8443],
#         [5, "42 S Dove St, Albany, NY 12202", "KIPP Albany Community Charter Middle", 42.6419, -73.7411],
#         [6, "11 N Pearl St, Albany, NY 12207", "Commercial tower (formerly occupied by KeyBank)", 42.6518, -73.7520],
#         [7, "600 Broadway, Albany, NY 12207", "Proximity to Corning Preserve & Hudson River", 42.6505, -73.7427],
#         [8, "126 State St, Albany, NY 12207", "Government law office", 42.6486, -73.7562],
#         [9, "186 Fuller Rd, Albany, NY 12205", "Nanotech research campus", 42.6900, -73.8320],
#         [10, "106 Smith Blvd, Albany, NY 12202", "Albany Port District Commission", 42.6545, -73.7487],
#     ]
#     assets_ny_albany_df = pd.DataFrame(assets_ny_albany_csv, columns=["id", "address", "description", "lat_true", "lon_true"])
#     assets_ny_albany_df.to_csv("data/assets_ny_albany.csv", index=False)
#     return assets_ny_albany_df


def geocode_with_retry(address, max_retries=3, timeout=3, sleep_time=2):
    geolocator = Nominatim(user_agent="flood-risk-checker", timeout=timeout)
    for attempt in range(max_retries):
        try:
            location = geolocator.geocode(address)
            if location:
                return location.latitude, location.longitude
        except GeocoderTimedOut:
            print(f"Timeout on attempt {attempt + 1} for address: {address}")
            time.sleep(sleep_time)
    print(f"Failed to geocode address (need a better geocoding tool, eg Google paid API geopy.GoogleV3): {address}")
    return None, None


def geocode_assets(assets_df, max_retries=3, timeout=3, sleep_time=2):
    assets_df['lat'], assets_df['lon'] = zip(*assets_df['address'].apply(geocode_with_retry, max_retries=max_retries, timeout=timeout, sleep_time=sleep_time))
    if (assets_df['lat'].isna().any() | assets_df['lon'].isna().any()):
        print("Some addresses failed to geocode. Using true coordinates.")
        assets_df['lat'].fillna(assets_df['lat_true'], inplace=True)
        assets_df['lon'].fillna(assets_df['lon_true'], inplace=True)
    assets_df.dropna(subset=['lat', 'lon'], inplace=True)
    return assets_df


def add_geometry_column(assets_df):
    assets_df['geometry'] = assets_df.apply(lambda row: Point(row['lon_true'], row['lat_true']), axis=1)
    gdf_assets = gpd.GeoDataFrame(assets_df, geometry="geometry", crs="EPSG:4326")  # WGS84
    return gdf_assets


def plot_flood_risk(assets_gdf, flood_gdf, save_to_filename):
    # Initialize base map centered on Fairfield, CT
    m = folium.Map(location=[41.14, -73.26], zoom_start=12, tiles='cartodbpositron')

    # --- Add 100-year flood zone polygons (light blue transparent) ---
    flood_100 = flood_gdf[flood_gdf['rp100']]
    GeoJson(
        flood_100.to_crs(epsg=4326),
        name="100-Year Flood Zone",
        style_function=lambda x: {
            "fillColor": "lightblue",
            "color": "lightblue",
            "weight": 0.5,
            "fillOpacity": 0.3,
        },
    ).add_to(m)

    # --- Add 500-year flood zone polygons (light orange transparent) ---
    flood_500 = flood_gdf[(~flood_gdf['rp100']) & (flood_gdf['rp500'])]  # exclude RP100 overlap
    GeoJson(
        flood_500.to_crs(epsg=4326),
        name="500-Year Flood Zone",
        style_function=lambda x: {
            "fillColor": "orange",
            "color": "orange",
            "weight": 0.5,
            "fillOpacity": 0.3,
        },
    ).add_to(m)

    # --- add assets points ---
    # Helper to add assets
    def add_asset_markers(df, color, label):
        for _, row in df.iterrows():
            CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                popup=row['address'],
            ).add_to(m)

    # Filter asset groups
    assets_100 = assets_gdf[assets_gdf['flood_zone'] == 'rp100']
    assets_500 = assets_gdf[assets_gdf['flood_zone'] == 'rp500']
    assets_out = assets_gdf[assets_gdf['flood_zone'] == 'outside']

    add_asset_markers(assets_100, "red", "Assets in 100-yr zone")
    add_asset_markers(assets_500, "orange", "Assets in 500-yr zone")
    add_asset_markers(assets_out, "blue", "Assets outside flood zones")

    # Legend
    legend_html = """
    {% macro html(this=None, kwargs=None) %}
    <div style="
        position: fixed; 
        bottom: 50px; left: 50px; width: 220px; height: 200px; 
        background-color: white;
        border:2px solid grey; 
        z-index:9999;
        font-size:14px;
        padding: 10px;
        ">
        <b>Flood Risk Legend</b><br>
        <i style="background:lightblue;opacity:0.6;width:12px;height:12px;display:inline-block;"></i>
        100-Year Flood Zone<br>
        <i style="background:orange;opacity:0.6;width:12px;height:12px;display:inline-block;"></i>
        500-Year Flood Zone<br><br>
        <i style="background:red;border-radius:50%;width:12px;height:12px;display:inline-block;"></i>
        Asset in 100-Year Zone<br>
        <i style="background:orange;border-radius:50%;width:12px;height:12px;display:inline-block;"></i>
        Asset in 500-Year Zone<br>
        <i style="background:blue;border-radius:50%;width:12px;height:12px;display:inline-block;"></i>
        Asset Outside Zones
    </div>
    {% endmacro %}
    """

    # Prepare the legend template
    legend = MacroElement()
    legend._template = Template(legend_html)

    # 1. Add flood zone layers (GeoJson for RP100 and RP500)
    # 2. Add asset markers (CircleMarker or FeatureGroups)
    # 3. Add layer control for toggling layers
    folium.LayerControl().add_to(m)

    # 4. Add custom HTML legend (not a map layer, just UI)
    m.get_root().add_child(legend)

    # 5. Save map to file
    m.save(save_to_filename)
