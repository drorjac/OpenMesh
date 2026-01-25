"""
Analysis functions for rain detection and scatter plot analysis.

This module provides modular functions for:
- Rain event detection (constant baseline and rolling std methods)
- Scatter plot analysis (dB/km vs rainfall)
- Link filtering and data preparation
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import Optional, Dict, List, Tuple


def prepare_cml_data_for_detection(
    analysis_data: Dict,
    cml_id: str,
    sublink_id: str,
    window: str = '6h',
    baseline_method: str = 'max'
) -> Optional[pd.DataFrame]:
    """
    Extract CML RSL data and calculate baseline and attenuation.
    
    Parameters
    ----------
    analysis_data : dict
        Analysis data dictionary containing 'cml' -> 'rsl' DataFrame
    cml_id : str
        CML link ID
    sublink_id : str
        Sublink ID
    window : str, optional
        Window size for rolling baseline (default: '6h')
        Examples: '3h', '6h', '12h', '30min', '180min'
    baseline_method : str, optional
        Method for baseline: 'max' (default), 'quantile', 'mean'
        - 'max': Rolling maximum (safest, always positive attenuation)
        - 'quantile': High percentile (e.g., 95th)
        - 'mean': Rolling mean (can give negative attenuation)
    
    Returns
    -------
    pd.DataFrame or None
        DataFrame with columns: 'rsl', 'baseline', 'attenuation'
        Returns None if data not found
    """
    cml_column = f"{cml_id}_{sublink_id}"
    
    if 'rsl' not in analysis_data.get('cml', {}) or cml_column not in analysis_data['cml']['rsl'].columns:
        return None
    
    df_rsl = analysis_data['cml']['rsl'][[cml_column]].copy()
    df_rsl.columns = ['rsl']
    
    # Auto-detect sampling interval from data
    if len(df_rsl) > 1:
        time_diffs = df_rsl.index.to_series().diff().dropna()
        sampling_interval = time_diffs.median()
        sampling_minutes = sampling_interval.total_seconds() / 60
    else:
        sampling_minutes = 5  # fallback default
    
    # Calculate rolling baseline using time-based window
    if baseline_method == 'max':
        # Use rolling maximum (dry weather signal)
        df_rsl['baseline'] = df_rsl['rsl'].rolling(window=window, min_periods=1, center=True).max()
    elif baseline_method == 'quantile':
        # Use 95th percentile
        df_rsl['baseline'] = df_rsl['rsl'].rolling(window=window, min_periods=1, center=True).quantile(0.99)
    else:  # 'mean'
        # Use rolling mean (original, not recommended)
        df_rsl['baseline'] = df_rsl['rsl'].rolling(window=window, min_periods=1, center=True).mean()
    
    # Calculate attenuation = baseline - RSL
    # Positive values indicate signal loss (rain)
    df_rsl['attenuation'] = df_rsl['baseline'] - df_rsl['rsl']
    
    # Add metadata
    df_rsl.attrs['sampling_interval_min'] = sampling_minutes
    df_rsl.attrs['window'] = window
    df_rsl.attrs['baseline_method'] = baseline_method
    
    return df_rsl

def prepare_ground_truth_rainfall(
    analysis_data: Dict,
    matched_pws: Optional[List[str]] = None,
    matched_asos: Optional[List[str]] = None,
    rainfall_source: str = 'both',
    verbose: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Prepare ground truth rainfall data from PWS and/or ASOS stations.
    
    Parameters
    ----------
    analysis_data : dict
        Analysis data dictionary
    matched_pws : list, optional
        List of matched PWS station IDs. If None, uses all available PWS stations.
    matched_asos : list, optional
        List of ASOS station IDs. If None, uses all available ASOS stations.
    rainfall_source : str, optional
        Source selection: 'pws_mean', 'asos_mean', or 'both' (default: 'both')
    
    Returns
    -------
    tuple
        (df_pws_rain_mean, df_asos_rain_mean)
        DataFrames with single column 'pws_rainfall' or 'asos_rainfall'
    """
    df_pws_rain_mean = None
    df_asos_rain_mean = None
    
    # Prepare PWS rainfall
    if rainfall_source in ['pws_mean', 'both'] and 'rainfall_amount' in analysis_data.get('pws', {}):
        df_pws_all = analysis_data['pws']['rainfall_amount'].copy()
        
        if matched_pws:
            available_pws = [s for s in matched_pws if s in df_pws_all.columns]
            if available_pws:
                df_pws_rain = df_pws_all[available_pws].copy()
                # Use mean for PWS (5-min interval amounts)
                df_pws_rain_mean = df_pws_rain.mean(axis=1).to_frame(name='pws_rainfall')
            else:
                # Fallback to all stations
                df_pws_rain_mean = df_pws_all.mean(axis=1).to_frame(name='pws_rainfall')
        else:
            # Use all PWS stations
            df_pws_rain_mean = df_pws_all.mean(axis=1).to_frame(name='pws_rainfall')
    
    # Prepare ASOS rainfall
    if rainfall_source in ['asos_mean', 'both'] and 'rainfall_amount' in analysis_data.get('asos', {}):
        df_asos_all = analysis_data['asos']['rainfall_amount'].copy()
        
        # Diagnostic: Check if data has non-zero values BEFORE processing
        if len(df_asos_all) > 0:
            non_zero_count = (df_asos_all > 0).sum().sum()
            total_values = df_asos_all.notna().sum().sum()
            max_val = df_asos_all.max().max() if not df_asos_all.empty else 0
            min_val = df_asos_all.min().min() if not df_asos_all.empty else 0
            
            if non_zero_count == 0 and total_values > 0:
                print(f"⚠ Warning: ASOS rainfall data contains only zeros")
                print(f"  Data shape: {df_asos_all.shape}")
                print(f"  Columns: {list(df_asos_all.columns)[:5]}")
                print(f"  Value range: {min_val:.4f} to {max_val:.4f}")
                print(f"  Non-zero values: {non_zero_count} out of {total_values}")
            elif max_val > 0:
                print(f"✓ ASOS rainfall data has non-zero values: max={max_val:.2f} mm, {non_zero_count} non-zero points")
        
        if matched_asos:
            available_asos = [s for s in matched_asos if s in df_asos_all.columns]
            if available_asos:
                df_asos_rain = df_asos_all[available_asos].copy()
                # Diagnostic: Check data before averaging
                if verbose and len(df_asos_rain) > 0:
                    before_mean_non_zero = (df_asos_rain > 0).sum().sum()
                    before_mean_max = df_asos_rain.max().max()
                    print(f"  Before averaging: {before_mean_non_zero} non-zero values, max={before_mean_max:.4f} mm")
                
                # Use mean for ASOS (per-minute or per-interval amounts)
                df_asos_rain_mean = df_asos_rain.mean(axis=1).to_frame(name='asos_rainfall')
                
                # Diagnostic: Check data after averaging
                if verbose and len(df_asos_rain_mean) > 0:
                    after_mean_non_zero = (df_asos_rain_mean > 0).sum().sum()
                    after_mean_max = df_asos_rain_mean.max().max()
                    if before_mean_non_zero > 0 and after_mean_non_zero == 0:
                        print(f"  ⚠ Warning: After averaging, all values became zero!")
                        print(f"    Before: {before_mean_non_zero} non-zero, max={before_mean_max:.4f}")
                        print(f"    After: {after_mean_non_zero} non-zero, max={after_mean_max:.4f}")
                    elif after_mean_max > 0:
                        print(f"  After averaging: {after_mean_non_zero} non-zero values, max={after_mean_max:.4f} mm")
            else:
                df_asos_rain_mean = df_asos_all.mean(axis=1).to_frame(name='asos_rainfall')
        else:
            df_asos_rain_mean = df_asos_all.mean(axis=1).to_frame(name='asos_rainfall')
    
    return df_pws_rain_mean, df_asos_rain_mean


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
    
    print(f"\n✓ Filtered network: {len(filtered_links)} links, {len(filtered_pws)} PWS stations")
    
    return matches, filtered_links, filtered_pws


# ============================================================================
# DETECTION HELPER FUNCTIONS (with Ground Truth & Metrics)
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
    
    # Convert window to periods
    if isinstance(window, str) and window.endswith('h'):
        hours = int(window.replace('h', ''))
        resample_min = int(resample.replace('min', ''))
        window_periods = (hours * 60) // resample_min
    else:
        window_periods = int(window)
    
    df['rolling_std'] = df['attenuation'].rolling(window=window_periods, min_periods=1, center=True).std()
    df['rain_detected'] = (df['rolling_std'] > threshold).astype(int)
    df['threshold'] = threshold
    
    rain_pct = 100 * df['rain_detected'].sum() / len(df)
    print(f"✓ Detection: {df['rain_detected'].sum()} periods ({rain_pct:.1f}%) | threshold={threshold} dB")
    
    return df


def calculate_detection_metrics(df_detection, df_pws_rain, df_asos_rain, rain_threshold=0.1):
    """
    Calculate detection performance metrics.
    
    Returns
    -------
    dict with POD, FAR, accuracy, etc.
    """
    # Create ground truth: rain if PWS or ASOS > threshold
    gt_rain = pd.Series(0, index=df_detection.index)
    
    if df_pws_rain is not None:
        pws_resampled = df_pws_rain.resample('5min').mean().mean(axis=1)
        pws_aligned = pws_resampled.reindex(df_detection.index, method='nearest', tolerance='5min')
        gt_rain = gt_rain | (pws_aligned > rain_threshold).fillna(False)
    
    if df_asos_rain is not None:
        asos_resampled = df_asos_rain.resample('5min').mean().mean(axis=1)
        asos_aligned = asos_resampled.reindex(df_detection.index, method='nearest', tolerance='5min')
        gt_rain = gt_rain | (asos_aligned > rain_threshold).fillna(False)
    
    gt_rain = gt_rain.astype(int)
    detected = df_detection['rain_detected'].values
    
    # Confusion matrix
    TP = ((detected == 1) & (gt_rain == 1)).sum()
    FP = ((detected == 1) & (gt_rain == 0)).sum()
    FN = ((detected == 0) & (gt_rain == 1)).sum()
    TN = ((detected == 0) & (gt_rain == 0)).sum()
    
    # Metrics
    POD = TP / (TP + FN) if (TP + FN) > 0 else 0  # Probability of Detection
    FAR = FP / (TP + FP) if (TP + FP) > 0 else 0  # False Alarm Rate
    ACC = (TP + TN) / len(detected) if len(detected) > 0 else 0
    CSI = TP / (TP + FP + FN) if (TP + FP + FN) > 0 else 0  # Critical Success Index
    
    return {
        'TP': TP, 'FP': FP, 'FN': FN, 'TN': TN,
        'POD': POD, 'FAR': FAR, 'ACC': ACC, 'CSI': CSI,
        'gt_rain': gt_rain
    }


def plot_detection_results(
    df_cml: pd.DataFrame,
    df_detection: pd.DataFrame,
    df_pws_rain: pd.DataFrame = None,
    df_asos_rain: pd.DataFrame = None,
    title: str = '',
    start_date=None,
    end_date=None,
    rain_y_max: float = 2.0,
    show_metrics: bool = True,
    figsize: tuple = (16, 14)
):
    """
    Plot detection results with ground truth and metrics.
    
    Panels:
    1. RSL + Baseline
    2. Attenuation
    3. Rolling Std + Detection
    4. Ground Truth Rainfall (PWS + ASOS) with Detection Overlay
    """
    # Filter time range
    if start_date and end_date:
        df_cml = df_cml.loc[start_date:end_date]
        df_detection = df_detection.loc[start_date:end_date]
        if df_pws_rain is not None:
            df_pws_rain = df_pws_rain.loc[start_date:end_date]
        if df_asos_rain is not None:
            df_asos_rain = df_asos_rain.loc[start_date:end_date]
    
    # Calculate metrics
    metrics = None
    if show_metrics and (df_pws_rain is not None or df_asos_rain is not None):
        metrics = calculate_detection_metrics(df_detection, df_pws_rain, df_asos_rain)
    
    fig, axes = plt.subplots(4, 1, figsize=figsize, sharex=True)
    threshold = df_detection['threshold'].iloc[0] if 'threshold' in df_detection.columns else 1.0
    
    # --- Panel 1: RSL + Baseline ---
    axes[0].plot(df_cml.index, df_cml['rsl'], 'b-', lw=0.5, alpha=0.8, label='RSL')
    axes[0].plot(df_cml.index, df_cml['baseline'], 'r--', lw=1, label='Baseline')
    axes[0].set_ylabel('RSL (dB)')
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
    
    # --- Panel 4: Ground Truth + Detection Comparison ---
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
    
    ax4.set_ylabel('Rainfall (mm)')
    ax4.set_xlabel('Time')
    ax4.set_ylim(0, y_max)
    ax4.legend(loc='upper right')
    ax4.grid(True, alpha=0.3)
    
    # Add metrics text box
    if metrics:
        metrics_text = (
            f"POD: {metrics['POD']:.2f}  |  FAR: {metrics['FAR']:.2f}  |  "
            f"ACC: {metrics['ACC']:.2f}  |  CSI: {metrics['CSI']:.2f}\n"
            f"TP: {metrics['TP']}  FP: {metrics['FP']}  FN: {metrics['FN']}  TN: {metrics['TN']}"
        )
        ax4.text(0.02, 0.95, metrics_text, transform=ax4.transAxes, fontsize=10,
                 verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.tight_layout()
    plt.show()
    
    # Print metrics summary
    if metrics:
        print(f"\n{'='*50}")
        print("DETECTION METRICS")
        print(f"{'='*50}")
        print(f"  POD (Hit Rate):     {metrics['POD']:.2%}")
        print(f"  FAR (False Alarm):  {metrics['FAR']:.2%}")
        print(f"  Accuracy:           {metrics['ACC']:.2%}")
        print(f"  CSI (Threat Score): {metrics['CSI']:.2%}")
        print(f"{'='*50}")






# #####

# """
# Backup of older / currently unused analysis helper functions.

# These functions were originally located in analysis_functions.py and moved
# here so they can be restored or experimented with later if needed.
# """

# import pandas as pd
# import numpy as np
# from typing import Optional, Dict, List, Tuple


# def prepare_cml_and_matched_stations(
#     analysis_data: Dict,
#     cml_id: str,
#     sublink_id: str,
#     cml_to_pws: Optional[Dict] = None
# ) -> Tuple[Optional[pd.DataFrame], List[str], List[str]]:
#     """
#     Prepare CML data and get matched PWS/ASOS stations in one call.
    
#     Parameters
#     ----------
#     analysis_data : dict
#         Analysis data dictionary
#     cml_id : str
#         CML link ID
#     sublink_id : str
#         Sublink ID
#     cml_to_pws : dict, optional
#         Mapping of CML IDs to PWS station lists (from section 10)
    
#     Returns
#     -------
#     tuple
#         (df_cml_rsl, matched_pws, matched_asos)
#     """
#     # Get matched PWS stations
#     if cml_to_pws is not None and cml_id in cml_to_pws:
#         matched_pws = cml_to_pws[cml_id]
#     else:
#         matched_pws = []
    
#     # Get ASOS stations
#     if 'rainfall_amount' in analysis_data.get('asos', {}):
#         matched_asos = list(analysis_data['asos']['rainfall_amount'].columns)
#     else:
#         matched_asos = []
    
#     # Extract CML RSL data
#     from .analysis_functions import prepare_cml_data_for_detection
#     df_cml_rsl = prepare_cml_data_for_detection(
#         analysis_data=analysis_data,
#         cml_id=cml_id,
#         sublink_id=sublink_id
#     )
    
#     return df_cml_rsl, matched_pws, matched_asos


# def prepare_combined_ground_truth(
#     analysis_data: Dict,
#     matched_pws: Optional[List[str]] = None,
#     matched_asos: Optional[List[str]] = None,
#     rainfall_source: str = 'both',
#     verbose: bool = True
# ) -> Optional[pd.DataFrame]:
#     """
#     Prepare combined ground truth rainfall data (simplified wrapper).
    
#     Parameters
#     ----------
#     analysis_data : dict
#         Analysis data dictionary
#     matched_pws : list, optional
#         List of matched PWS station IDs
#     matched_asos : list, optional
#         List of ASOS station IDs
#     rainfall_source : str, optional
#         Source selection: 'pws_mean', 'asos_mean', or 'both' (default: 'both')
    
#     Returns
#     -------
#     pd.DataFrame or None
#         DataFrame with 'precip_mm' column, or None if no data available
#     """
#     from .analysis_functions import prepare_ground_truth_rainfall

#     df_pws_rain_mean, df_asos_rain_mean = prepare_ground_truth_rainfall(
#         analysis_data=analysis_data,
#         matched_pws=matched_pws,
#         matched_asos=matched_asos,
#         rainfall_source=rainfall_source,
#         verbose=verbose
#     )
    
#     # Combine for ground truth
#     df_rain_combined = None
#     if df_pws_rain_mean is not None and df_asos_rain_mean is not None:
#         df_rain_combined = pd.concat([df_pws_rain_mean, df_asos_rain_mean], axis=1)
#         df_rain_combined['precip_mm'] = df_rain_combined[['pws_rainfall', 'asos_rainfall']].mean(axis=1)
#     elif df_pws_rain_mean is not None:
#         df_rain_combined = df_pws_rain_mean.copy()
#         df_rain_combined['precip_mm'] = df_rain_combined['pws_rainfall']
#     elif df_asos_rain_mean is not None:
#         df_rain_combined = df_asos_rain_mean.copy()
#         df_rain_combined['precip_mm'] = df_rain_combined['asos_rainfall']
    
#     if df_rain_combined is not None and 'precip_mm' in df_rain_combined.columns:
#         return df_rain_combined[['precip_mm']].copy()
#     else:
#         return None


# def detect_rain_constant_threshold(
#     df_cml_rsl: pd.DataFrame,
#     threshold_dB: float = 2.0,
#     resample_freq: str = '5min',
#     verbose: bool = True
# ) -> Optional[pd.DataFrame]:
#     """
#     Detect rain events using constant baseline threshold method.
    
#     Parameters
#     ----------
#     df_cml_rsl : pd.DataFrame
#         CML data with 'attenuation' column, indexed by time
#     threshold_dB : float, optional
#         Constant threshold in dB (default: 2.0)
#     resample_freq : str, optional
#         Resampling frequency (default: '5min')
#     verbose : bool, optional
#         Print detection statistics (default: True)
    
#     Returns
#     -------
#     pd.DataFrame or None
#         DataFrame with columns: 'attenuation', 'rain_detected', 'threshold_constant'
#     """
#     if df_cml_rsl is None or 'attenuation' not in df_cml_rsl.columns:
#         if verbose:
#             print("⚠ Error: CML data with attenuation not available")
#         return None
    
#     # Resample to specified frequency
#     df_resampled = df_cml_rsl[['attenuation']].resample(resample_freq).mean()
    
#     # Binary detection: 1 = rain, 0 = no rain
#     df_resampled['rain_detected'] = (df_resampled['attenuation'] > threshold_dB).astype(int)
#     df_resampled['threshold_constant'] = threshold_dB
    
#     if verbose and len(df_resampled) > 0:
#         rain_count = df_resampled['rain_detected'].sum()
#         rain_percent = 100 * rain_count / len(df_resampled) if len(df_resampled) > 0 else 0
        
#         print("=" * 70)
#         print("CONSTANT BASELINE METHOD")
#         print("=" * 70)
#         print(f"Threshold: {threshold_dB} dB")
#         print(f"If attenuation > {threshold_dB} dB → Rain detected (1), else No rain (0)")
#         print(f"\nRain detected: {rain_count:,} time points ({rain_percent:.1f}% of time)")
#         print(f"Attenuation range: {df_resampled['attenuation'].min():.2f} to {df_resampled['attenuation'].max():.2f} dB")
    
#     return df_resampled


# def detect_rain_rolling_std(
#     df_cml_rsl: pd.DataFrame,
#     window_size: int = 36,
#     threshold_std: float = 1.0,
#     resample_freq: str = '5min',
#     verbose: bool = True
# ) -> Optional[pd.DataFrame]:
#     """
#     Detect rain events using rolling standard deviation method.
    
#     Parameters
#     ----------
#     df_cml_rsl : pd.DataFrame
#         CML data with 'attenuation' column, indexed by time
#     window_size : int, optional
#         Rolling window size in intervals (default: 36 = 3 hours at 5-min intervals)
#     threshold_std : float, optional
#         Threshold for rolling std in dB (default: 1.0)
#     resample_freq : str, optional
#         Resampling frequency (default: '5min')
#     verbose : bool, optional
#         Print detection statistics (default: True)
    
#     Returns
#     -------
#     pd.DataFrame or None
#         DataFrame with columns: 'attenuation', 'rolling_std', 'rain_detected', 'threshold'
#     """
#     if df_cml_rsl is None or 'attenuation' not in df_cml_rsl.columns:
#         if verbose:
#             print("⚠ Error: CML data with attenuation not available")
#         return None
    
#     # Resample to specified frequency
#     df_resampled = df_cml_rsl[['attenuation']].resample(resample_freq).mean()
    
#     # Calculate rolling standard deviation
#     df_resampled['rolling_std'] = df_resampled['attenuation'].rolling(
#         window=window_size, min_periods=1, center=True
#     ).std()
    
#     # Binary detection: compare rolling_std to threshold
#     df_resampled['rain_detected'] = (df_resampled['rolling_std'] > threshold_std).astype(int)
#     df_resampled['threshold'] = threshold_std
    
#     if verbose and len(df_resampled) > 0:
#         rain_count = df_resampled['rain_detected'].sum()
#         rain_percent = 100 * rain_count / len(df_resampled) if len(df_resampled) > 0 else 0
        
#         print("=" * 70)
#         print("ROLLING STD METHOD")
#         print("=" * 70)
#         print(f"Window size: {window_size} intervals ({window_size * 5} minutes = {window_size * 5 / 60:.1f} hours)")
#         print(f"Threshold: {threshold_std} dB (for rolling_std)")
#         print(f"If rolling_std > {threshold_std} dB → Rain detected (1), else No rain (0)")
#         print(f"\nRain detected: {rain_count:,} time points ({rain_percent:.1f}% of time)")
#         print(f"Rolling std range: {df_resampled['rolling_std'].min():.2f} to {df_resampled['rolling_std'].max():.2f} dB")
    
#     return df_resampled


# def filter_links_by_features(
#     links_metadata: pd.DataFrame,
#     min_length: float = 1000,
#     max_length: float = 5000,
#     min_freq: float = 5000,
#     max_freq: float = 80000
# ) -> Tuple[pd.DataFrame, List[Tuple[str, str]]]:
#     """
#     Filter CML links by length and frequency range.
    
#     Parameters
#     ----------
#     links_metadata : pd.DataFrame
#         Links metadata with columns: 'cml_id', 'sublink_id', 'length', 'frequency'
#     min_length : float, optional
#         Minimum link length in meters (default: 1000)
#     max_length : float, optional
#         Maximum link length in meters (default: 5000)
#     min_freq : float, optional
#         Minimum frequency in MHz (default: 5000 = 5 GHz)
#     max_freq : float, optional
#         Maximum frequency in MHz (default: 80000 = 80 GHz)
    
#     Returns
#     -------
#     tuple
#         (filtered_links_df, filtered_pairs_list)
#         filtered_pairs_list contains (cml_id, sublink_id) tuples as strings
#     """
#     filtered_links = links_metadata[
#         (links_metadata['length'] >= min_length) & 
#         (links_metadata['length'] <= max_length) &
#         (links_metadata['frequency'] >= min_freq) & 
#         (links_metadata['frequency'] <= max_freq)
#     ].copy()
    
#     # Create list of (cml_id, sublink_id) pairs
#     filtered_pairs = list(zip(
#         filtered_links['cml_id'].astype(str), 
#         filtered_links['sublink_id'].astype(str)
#     ))
    
#     return filtered_links, filtered_pairs


# def select_link_group(
#     filtered_pairs: List[Tuple[str, str]],
#     select_mode: str = 'first_n',
#     selected_cml_ids: Optional[List[str]] = None,
#     n_links: int = 10
# ) -> List[Tuple[str, str]]:
#     """
#     Select a group of links from filtered list.
    
#     Parameters
#     ----------
#     filtered_pairs : list
#         List of (cml_id, sublink_id) tuples
#     select_mode : str, optional
#         Selection mode: 'specific', 'first_n', or 'all' (default: 'first_n')
#     selected_cml_ids : list, optional
#         List of CML IDs to select if mode is 'specific'
#     n_links : int, optional
#         Number of links to select if mode is 'first_n' (default: 10)
    
#     Returns
#     -------
#     list
#         Selected list of (cml_id, sublink_id) tuples
#     """
#     if select_mode == 'specific' and selected_cml_ids:
#         selected_pairs = [(cml_id, sublink) for cml_id, sublink in filtered_pairs 
#                           if cml_id in selected_cml_ids]
#     elif select_mode == 'first_n':
#         selected_pairs = filtered_pairs[:n_links]
#     else:  # 'all'
#         selected_pairs = filtered_pairs
    
#     return selected_pairs


# def match_links_to_pws(
#     selected_pairs: List[Tuple[str, str]],
#     filtered_links: pd.DataFrame,
#     pws_metadata: pd.DataFrame,
#     max_distance_km: float = 5.0,
#     haversine_distance_func=None
# ) -> Dict[Tuple[str, str], List[str]]:
#     """
#     Match CML links to PWS stations based on geographic distance.
    
#     Parameters
#     ----------
#     selected_pairs : list
#         List of (cml_id, sublink_id) tuples
#     filtered_links : pd.DataFrame
#         Filtered links metadata with coordinate columns
#     pws_metadata : pd.DataFrame
#         PWS metadata with 'lat', 'lon', and station ID columns
#     max_distance_km : float, optional
#         Maximum distance for matching in km (default: 5.0)
#     haversine_distance_func : callable, optional
#         Function to calculate haversine distance. If None, imports from pipeline.
    
#     Returns
#     -------
#     dict
#         Mapping: (cml_id, sublink_id) -> list of PWS station IDs
#     """
#     if haversine_distance_func is None:
#         from analysis.pipeline import haversine_distance
#         haversine_distance_func = haversine_distance
    
#     link_to_pws = {}
    
#     for cml_id, sublink_id in selected_pairs:
#         # Get link coordinates from metadata
#         link_info = filtered_links[
#             (filtered_links['cml_id'].astype(str) == cml_id) & 
#             (filtered_links['sublink_id'] == sublink_id)
#         ]
        
#         if len(link_info) > 0:
#             row = link_info.iloc[0]
#             # Calculate midpoint of link
#             mid_lat = (row['site_0_lat'] + row['site_1_lat']) / 2
#             mid_lon = (row['site_0_lon'] + row['site_1_lon']) / 2
            
#             # Find nearby PWS stations
#             matched_pws = []
#             if 'lat' in pws_metadata.columns and 'lon' in pws_metadata.columns:
#                 for _, pws_row in pws_metadata.iterrows():
#                     pws_lat = pws_row['lat']
#                     pws_lon = pws_row['lon']
#                     distance = haversine_distance_func(mid_lat, mid_lon, pws_lat, pws_lon)
#                     if distance <= max_distance_km:
#                         pws_id = pws_row.get('station_id', pws_row.get('id', str(pws_row.name)))
#                         matched_pws.append(pws_id)
            
#             link_to_pws[(cml_id, sublink_id)] = matched_pws
    
#     return link_to_pws


# def calculate_db_per_km_for_links(
#     analysis_data: Dict,
#     selected_pairs: List[Tuple[str, str]],
#     filtered_links: pd.DataFrame,
#     sampling_interval: str = '10min',
#     window_3h: int = 36
# ) -> Dict[Tuple[str, str], pd.DataFrame]:
#     """
#     Calculate dB/km for each selected link.
    
#     Parameters
#     ----------
#     analysis_data : dict
#         Analysis data dictionary
#     selected_pairs : list
#         List of (cml_id, sublink_id) tuples
#     filtered_links : pd.DataFrame
#         Links metadata with 'length' column
#     sampling_interval : str, optional
#         Resampling interval (default: '10min')
#     window_3h : int, optional
#         Window size for rolling baseline (default: 36)
    
#     Returns
#     -------
#     dict
#         Mapping: (cml_id, sublink_id) -> DataFrame with 'db_per_km' column
#     """
#     link_data_dict = {}
    
#     for cml_id, sublink_id in selected_pairs:
#         cml_column = f"{cml_id}_{sublink_id}"
        
#         # Get RSL data
#         if 'rsl' in analysis_data.get('cml', {}) and cml_column in analysis_data['cml']['rsl'].columns:
#             df_rsl = analysis_data['cml']['rsl'][[cml_column]].copy()
#             df_rsl.columns = ['rsl']
            
#             # Get link length from metadata
#             link_info = filtered_links[
#                 (filtered_links['cml_id'].astype(str) == cml_id) & 
#                 (filtered_links['sublink_id'] == sublink_id)
#             ]
            
#             if len(link_info) > 0:
#                 link_length_m = link_info.iloc[0]['length']  # in meters
#                 link_length_km = link_length_m / 1000.0  # convert to km
                
#                 # Calculate rolling baseline
#                 df_rsl['baseline'] = df_rsl['rsl'].rolling(window=window_3h, min_periods=1, center=True).mean()
                
#                 # Calculate attenuation
#                 df_rsl['attenuation'] = df_rsl['baseline'] - df_rsl['rsl']
                
#                 # Calculate dB/km = attenuation / link_length_km
#                 df_rsl['db_per_km'] = df_rsl['attenuation'] / link_length_km
                
#                 # Resample to sampling interval
#                 df_resampled = df_rsl[['db_per_km']].resample(sampling_interval).mean()
                
#                 link_data_dict[(cml_id, sublink_id)] = df_resampled
    
#     return link_data_dict

