"""
Analysis functions for rain detection and scatter plot analysis.

This module provides modular functions for:
- Matching CML links to nearby PWS stations
- Rain event detection with a rolling-std rule on CML attenuation
- Plotting detections next to gauge rainfall
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km."""
    R = 6371  # Earth radius in km
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))



def find_nearest_pws_stations(ds_links, links_meta, pws_meta, cml_ids, max_distance_km=5.0, max_stations=None):
    """
    Find nearest PWS stations to CML links.
    
    Parameters
    ----------
    ds_links : xarray.Dataset
        CML links dataset with coordinates
    links_meta : pd.DataFrame
        Links metadata
    pws_meta : pd.DataFrame
        PWS metadata with 'Station ID', 'Latitude', 'Longitude'
    cml_ids : list
        List of CML IDs to analyze
    max_distance_km : float
        Maximum distance for matching (km)
    max_stations : int or None
        Max PWS stations per link (None = all within distance)
    
    Returns
    -------
    tuple : (cml_to_pws_dict, filtered_links_meta, filtered_pws_meta)
    """
    # Get available CML IDs from dataset (convert to string for comparison)
    available_cml_ids = [str(cid) for cid in ds_links.cml_id.values]
    
    # If cml_ids is None, use all available CML IDs
    if cml_ids is None:
        cml_ids = list(ds_links.cml_id.values)
        print(f"ℹ No CML IDs specified - processing all {len(cml_ids)} links in dataset")
    
    # Filter cml_ids to only include those that exist in the dataset
    valid_cml_ids = []
    for cml_id in cml_ids:
        cml_id_str = str(cml_id)
        if cml_id_str in available_cml_ids:
            valid_cml_ids.append(cml_id)
        else:
            print(f"⚠ Warning: CML ID '{cml_id}' not found in dataset. Skipping.")
    
    if len(valid_cml_ids) == 0:
        print("✗ No valid CML IDs found in dataset")
        return {}, pd.DataFrame(), pd.DataFrame()
    
    matches = {}
    
    for cml_id in valid_cml_ids:
        # Convert to string for xarray selection
        cml_id_str = str(cml_id)
        
        try:
            lat0 = float(ds_links['site_0_lat'].sel(cml_id=cml_id_str).values)
            lon0 = float(ds_links['site_0_lon'].sel(cml_id=cml_id_str).values)
            lat1 = float(ds_links['site_1_lat'].sel(cml_id=cml_id_str).values)
            lon1 = float(ds_links['site_1_lon'].sel(cml_id=cml_id_str).values)
        except KeyError:
            print(f"⚠ Warning: Could not access coordinates for CML ID '{cml_id}'. Skipping.")
            continue
        
        # Link midpoint
        mid_lat = (lat0 + lat1) / 2
        mid_lon = (lon0 + lon1) / 2
        
        # Find PWS within range
        distances = []
        for _, pws in pws_meta.iterrows():
            dist = haversine_distance(mid_lat, mid_lon, pws['Latitude'], pws['Longitude'])
            if dist <= max_distance_km:
                distances.append((pws['Station ID'], dist))
        
        # Sort by distance, take top N
        distances.sort(key=lambda x: x[1])
        nearest = [pid for pid, _ in (distances[:max_stations] if max_stations else distances)]
        matches[cml_id] = nearest
    
    # Print only a few example mappings to avoid huge output
    if matches:
        print("\nSample link→PWS matches:")
        for idx, (cml_id, nearest) in enumerate(matches.items()):
            if idx >= 2:
                break
            print(f"  Link {cml_id}: {len(nearest)} PWS within {max_distance_km}km")
        if len(matches) > 2:
            print(f"  ... and {len(matches) - 2} more links")
    
    # Filter links metadata - Use only valid_cml_ids
    if 'cml_id' in links_meta.columns:
        valid_cml_ids_str = [str(cid) for cid in valid_cml_ids]
        cml_ids_col = links_meta['cml_id'].astype(str)
        filtered_links = links_meta[cml_ids_col.isin(valid_cml_ids_str)].copy()
    elif links_meta.index.name == 'cml_id' or (hasattr(links_meta.index, 'name') and 'cml' in str(links_meta.index.name).lower()):
        valid_cml_ids_str = [str(cid) for cid in valid_cml_ids]
        index_str = links_meta.index.astype(str)
        filtered_links = links_meta.loc[index_str.isin(valid_cml_ids_str)].copy()
    else:
        valid_cml_ids_str = [str(cid) for cid in valid_cml_ids]
        index_str = links_meta.index.astype(str)
        filtered_links = links_meta.loc[index_str.isin(valid_cml_ids_str)].copy()
    
    # Filter PWS metadata
    all_pws_ids = list(set(pid for plist in matches.values() for pid in plist))
    filtered_pws = pws_meta[pws_meta['Station ID'].isin(all_pws_ids)].copy()
    
    n_links = (filtered_links['cml_id'].astype(str).nunique() if 'cml_id' in filtered_links.columns
               else filtered_links.index.astype(str).nunique())
    print(f"\n✓ Filtered network: {n_links} links ({len(filtered_links)} sublinks), "
          f"{len(filtered_pws)} PWS stations")
    
    return matches, filtered_links, filtered_pws


# ============================================================================
# DETECTION HELPER FUNCTIONS
# ============================================================================

def prepare_detection_data(
    analysis_data: dict,
    cml_id: str,
    sublink_id: str,
    cml_to_pws: dict,
    baseline_window: str = '6h',
    baseline_method: str = 'max'
):
    """
    Prepare CML data and matched PWS/ASOS rainfall in one call.
    
    Returns
    -------
    tuple: (df_cml, df_pws_rain, df_asos_rain, matched_pws_ids)
    """
    cml_column = f"{cml_id}_{sublink_id}"
    
    # --- CML Data ---
    if 'rsl' not in analysis_data.get('cml', {}) or cml_column not in analysis_data['cml']['rsl'].columns:
        print(f"✗ CML data not found for {cml_column}")
        return None, None, None, []
    
    df_cml = analysis_data['cml']['rsl'][[cml_column]].copy()
    df_cml.columns = ['rsl']
    
    # Baseline & attenuation
    if baseline_method == 'max':
        df_cml['baseline'] = df_cml['rsl'].rolling(window=baseline_window, min_periods=1, center=True).max()
    elif baseline_method == 'quantile':
        df_cml['baseline'] = df_cml['rsl'].rolling(window=baseline_window, min_periods=1, center=True).quantile(0.95)
    else:
        df_cml['baseline'] = df_cml['rsl'].rolling(window=baseline_window, min_periods=1, center=True).mean()
    
    df_cml['attenuation'] = df_cml['baseline'] - df_cml['rsl']
    
    # --- Matched PWS Rainfall ---
    matched_pws = cml_to_pws.get(cml_id, [])
    df_pws_rain = None
    
    if matched_pws and 'rainfall_amount' in analysis_data.get('pws', {}):
        available = [s for s in matched_pws if s in analysis_data['pws']['rainfall_amount'].columns]
        if available:
            df_pws_rain = analysis_data['pws']['rainfall_amount'][available].copy()
    
    # --- ASOS Rainfall ---
    df_asos_rain = None
    if 'rainfall_amount' in analysis_data.get('asos', {}):
        df_asos_rain = analysis_data['asos']['rainfall_amount'].copy()
    
    return df_cml, df_pws_rain, df_asos_rain, matched_pws


def run_rolling_std_detection(
    df_cml: pd.DataFrame,
    window: str = '3h',
    threshold: float = 1.0,
    resample: str = '5min'
):
    """
    Run rolling std detection.
    
    Returns
    -------
    DataFrame with columns: attenuation, rolling_std, rain_detected
    """
    df = df_cml[['attenuation']].resample(resample).mean()
    
    # Window as a number of resampled periods ('3h' at '15min' -> 12; an int is used as is)
    if isinstance(window, str):
        window_periods = max(1, int(pd.Timedelta(window) // pd.Timedelta(resample)))
    else:
        window_periods = int(window)
    
    df['rolling_std'] = df['attenuation'].rolling(window=window_periods, min_periods=1, center=True).std()
    df['rain_detected'] = (df['rolling_std'] > threshold).astype(int)
    df['threshold'] = threshold
    
    rain_pct = 100 * df['rain_detected'].sum() / len(df)
    print(f"✓ Detection: {df['rain_detected'].sum()} periods ({rain_pct:.1f}%) | threshold={threshold} dB")
    
    return df


def plot_detection_results(
    df_cml: pd.DataFrame,
    df_detection: pd.DataFrame,
    df_pws_rain: pd.DataFrame = None,
    df_asos_rain: pd.DataFrame = None,
    title: str = '',
    start_date=None,
    end_date=None,
    rain_y_max: float = 2.0,
    figsize: tuple = (16, 14)
):
    """
    Plot detection results next to gauge rainfall.

    Panels:
    1. RSL + Baseline
    2. Attenuation
    3. Rolling Std + Detection
    4. Gauge rainfall (PWS + ASOS station means, per time step) with the detection overlay
    """
    # Filter time range
    if start_date and end_date:
        df_cml = df_cml.loc[start_date:end_date]
        df_detection = df_detection.loc[start_date:end_date]
        if df_pws_rain is not None:
            df_pws_rain = df_pws_rain.loc[start_date:end_date]
        if df_asos_rain is not None:
            df_asos_rain = df_asos_rain.loc[start_date:end_date]
    
    fig, axes = plt.subplots(4, 1, figsize=figsize, sharex=True)
    threshold = df_detection['threshold'].iloc[0] if 'threshold' in df_detection.columns else 1.0
    
    # --- Panel 1: RSL + Baseline ---
    axes[0].plot(df_cml.index, df_cml['rsl'], 'b-', lw=0.5, alpha=0.8, label='RSL')
    axes[0].plot(df_cml.index, df_cml['baseline'], 'r--', lw=1, label='Baseline')
    axes[0].set_ylabel('RSL (dBm)')
    axes[0].set_title(title or 'CML Rain Detection')
    axes[0].legend(loc='upper right')
    axes[0].grid(True, alpha=0.3)
    
    # --- Panel 2: Attenuation ---
    axes[1].plot(df_detection.index, df_detection['attenuation'], 'tab:blue', lw=0.8)
    axes[1].axhline(0, color='gray', ls='--', alpha=0.5)
    axes[1].set_ylabel('Attenuation (dB)')
    axes[1].grid(True, alpha=0.3)
    
    # --- Panel 3: Rolling Std + Detection ---
    ax3 = axes[2]
    ax3.plot(df_detection.index, df_detection['rolling_std'], 'purple', lw=0.8, label='Rolling Std')
    ax3.axhline(threshold, color='red', ls='--', lw=1.5, label=f'Threshold ({threshold} dB)')
    
    rain_mask = df_detection['rain_detected'] == 1
    ax3.fill_between(df_detection.index, 0, df_detection['rolling_std'].max() * 1.1,
                     where=rain_mask, alpha=0.3, color='red', label='Rain Detected')
    ax3.set_ylabel('Rolling Std (dB)')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    
    # --- Panel 4: Gauge rainfall + detection overlay ---
    ax4 = axes[3]
    
    # Plot PWS rainfall
    if df_pws_rain is not None and len(df_pws_rain) > 0:
        pws_mean = df_pws_rain.mean(axis=1)
        ax4.bar(pws_mean.index, pws_mean.values, width=0.003, color='green', alpha=0.7, label='PWS Rain')
    
    # Plot ASOS rainfall
    if df_asos_rain is not None and len(df_asos_rain) > 0:
        asos_mean = df_asos_rain.mean(axis=1)
        ax4.bar(asos_mean.index, asos_mean.values, width=0.002, color='blue', alpha=0.5, label='ASOS Rain')
    
    # Overlay CML detection periods
    rain_mask = df_detection['rain_detected'] == 1
    y_max = rain_y_max if rain_y_max else 3.0
    ax4.fill_between(df_detection.index, 0, y_max,
                     where=rain_mask, alpha=0.2, color='red', label='CML Detection')
    
    ax4.set_ylabel('Rainfall per step (mm)')
    ax4.set_xlabel('Time')
    ax4.set_ylim(0, y_max)
    ax4.legend(loc='upper right')
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()
