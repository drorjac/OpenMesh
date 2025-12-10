"""
Plotting functions for OpenMesh data analysis.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import AutoDateLocator
from typing import Optional, List, Dict, Union


def plot_cml_rsl_attenuation(
    df_cml: pd.DataFrame,
    df_rain: pd.DataFrame,
    selected_link_id: str,
    rain_source: str = "ASOS"
) -> None:
    """
    Plot CML RSL, attenuation, and rain data on the same time axis.
    
    Parameters
    ----------
    df_cml : pd.DataFrame
        CML data with 'rsl' and 'attenuation' columns, indexed by time
    df_rain : pd.DataFrame
        Rain data with 'precipitation_mm' column, indexed by time
    selected_link_id : str
        Link ID for title
    rain_source : str
        Source of rain data (e.g., 'ASOS', 'PWS')
    """
    if df_cml is None or df_rain is None:
        print("⚠ Cannot plot - missing data")
        return
    
    # Align on common time index
    time_start = max(df_cml.index.min(), df_rain.index.min())
    time_end = min(df_cml.index.max(), df_rain.index.max())
    
    freq = '5min'
    
    # Resample CML data (continuous signal)
    df_cml_resampled = df_cml[['rsl', 'attenuation']].resample(freq).mean()
    
    # Don't resample rain data - use original timestamps
    # ASOS: already 5-min timestamps with hourly accumulation
    # PWS: already 5-min timestamps with 5-min amounts
    df_rain_plot = df_rain[['precipitation_mm']].copy()
    
    # Merge on time index (will align automatically)
    df_combined = pd.merge(
        df_cml_resampled,
        df_rain_plot,
        left_index=True,
        right_index=True,
        how='inner'
    )
    df_combined = df_combined.loc[time_start:time_end]
    
    if len(df_combined) == 0:
        print("⚠ Cannot plot - no overlapping data")
        return
    
    # Plot
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    
    # RSL
    ax1.plot(df_combined.index, df_combined['rsl'], 'b-', linewidth=0.5, alpha=0.7, label='RSL')
    ax1.set_ylabel('RSL (dBm)', fontsize=12)
    ax1.set_title(f'OpenMesh Link {selected_link_id} - Received Signal Level', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    
    # Attenuation
    ax2.plot(df_combined.index, df_combined['attenuation'], 'r-', linewidth=0.5, alpha=0.7, label='Attenuation')
    ax2.set_ylabel('Attenuation (dB)', fontsize=12)
    ax2.set_title('CML Attenuation (Baseline - RSL)', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    
    # Precipitation
    if rain_source == "ASOS":
        # ASOS: hourly accumulation (even at 5-min timestamps)
        ax3.bar(df_combined.index, df_combined['precipitation_mm'], width=0.001, 
                color='orange', alpha=0.6, label='ASOS (Hourly Accumulation)')
        ax3.set_ylabel('Precipitation (mm) - Hourly Accumulation', fontsize=12)
    else:
        # PWS: 5-minute interval amounts
        ax3.bar(df_combined.index, df_combined['precipitation_mm'], width=0.001, 
                color='green', alpha=0.6, label='PWS (5-min Interval)')
        ax3.set_ylabel('Precipitation (mm)', fontsize=12)
    ax3.set_xlabel('Time', fontsize=12)
    ax3.set_title(f'Ground Truth Rain Data ({rain_source})', fontsize=14, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    ax3.legend()
    
    # Format x-axis
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    locator = AutoDateLocator(maxticks=20)
    ax3.xaxis.set_major_locator(locator)
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    plt.tight_layout()
    plt.show()
    
    print("✓ Plots generated")


def plot_all_datasets(
    df_cml: Optional[pd.DataFrame],
    df_pws: Optional[pd.DataFrame],
    df_asos: Optional[pd.DataFrame],
    selected_link_id: str,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None,
    pws_stations: Optional[list] = None,
    pws_max_stations: Optional[int] = None,
    ylims: Optional[Dict[str, List[float]]] = None
) -> None:
    """
    Plot all three datasets (CML, PWS, ASOS) on the same time axis.
    Only plots data in the shared/overlapping time period between all available datasets.
    
    Parameters
    ----------
    df_cml : pd.DataFrame, optional
        CML data with 'rsl', 'attenuation', and optionally 'baseline' columns
    df_pws : pd.DataFrame, optional
        PWS data with one column per station (precipitation values)
    df_asos : pd.DataFrame, optional
        ASOS data with one column per station (precipitation values) or single 'precip_mm' column
    selected_link_id : str
        Link ID for title
    start_date : pd.Timestamp, optional
        Start date for filtering. If None, uses shared period start.
    end_date : pd.Timestamp, optional
        End date for filtering. If None, uses shared period end.
    pws_stations : list, optional
        List of specific PWS station IDs to plot. If None (default), plots median and mean across all stations.
    pws_max_stations : int, optional
        Maximum number of PWS stations to plot if pws_stations is None. If None, plots median and mean.
    ylims : dict, optional
        Dictionary of y-axis limits. Keys can be 'pws' and/or 'asos'. Values are [min, max] lists.
        Example: {'pws': [0, 3], 'asos': [0, 3]}. If None, no y-limits are enforced (auto-scale).
    """
    # Find shared/overlapping time period between all available datasets
    time_starts = []
    time_ends = []
    
    if df_cml is not None and len(df_cml) > 0:
        time_starts.append(df_cml.index.min())
        time_ends.append(df_cml.index.max())
    
    if df_pws is not None and len(df_pws) > 0:
        time_starts.append(df_pws.index.min())
        time_ends.append(df_pws.index.max())
    
    if df_asos is not None and len(df_asos) > 0:
        time_starts.append(df_asos.index.min())
        time_ends.append(df_asos.index.max())
    
    # Use shared period if dates not provided
    if start_date is None or end_date is None:
        if len(time_starts) > 0 and len(time_ends) > 0:
            shared_start = max(time_starts)  # Latest start = shared start
            shared_end = min(time_ends)      # Earliest end = shared end
            if start_date is None:
                start_date = shared_start
            if end_date is None:
                end_date = shared_end
            print(f"📅 Using shared time period: {start_date} to {end_date}")
        else:
            # Fallback to default if no data available
            if start_date is None:
                start_date = pd.Timestamp('2024-01-01')
            if end_date is None:
                end_date = pd.Timestamp('2024-01-14 23:59:59')
    
    fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True)
    freq = '5min'
    
    # 1. CML Data (RSL and Attenuation)
    if df_cml is not None and len(df_cml) > 0:
        df_cml_filtered = df_cml[(df_cml.index >= start_date) & (df_cml.index <= end_date)].copy()
        if len(df_cml_filtered) > 0:
            cols_to_plot = ['rsl', 'attenuation']
            if 'baseline' in df_cml_filtered.columns:
                cols_to_plot.append('baseline')
            df_cml_plot = df_cml_filtered[cols_to_plot].resample(freq).mean()
        else:
            df_cml_plot = None
        
        if df_cml_plot is not None and len(df_cml_plot) > 0:
            axes[0].plot(df_cml_plot.index, df_cml_plot['rsl'], 'b-', linewidth=0.8, alpha=0.7, label='RSL')
            if 'baseline' in df_cml_plot.columns:
                axes[0].plot(df_cml_plot.index, df_cml_plot['baseline'], 'g--', linewidth=1.0, alpha=0.6, label='Rolling Baseline (3H)')
            axes[0].set_ylabel('RSL (dBm)', fontsize=11)
            axes[0].set_title(f'OpenMesh CML Link {selected_link_id} - Received Signal Level', fontsize=13, fontweight='bold')
            axes[0].grid(True, alpha=0.3)
            axes[0].legend(loc='upper right')
            
            axes[1].plot(df_cml_plot.index, df_cml_plot['attenuation'], 'r-', linewidth=0.8, alpha=0.7, label='Attenuation')
            axes[1].set_ylabel('Attenuation (dB)', fontsize=11)
            atten_title = 'CML Attenuation (Rolling Baseline - RSL, 3H window)' if 'baseline' in df_cml_plot.columns else 'CML Attenuation'
            axes[1].set_title(atten_title, fontsize=13, fontweight='bold')
            axes[1].grid(True, alpha=0.3)
            axes[1].legend(loc='upper right')
        else:
            axes[0].text(0.5, 0.5, 'No CML data in date range', ha='center', va='center', transform=axes[0].transAxes, fontsize=12)
            axes[0].set_xlim(start_date, end_date)  # Set x-axis limits even with no data
            axes[1].text(0.5, 0.5, 'No CML data in date range', ha='center', va='center', transform=axes[1].transAxes, fontsize=12)
            axes[1].set_xlim(start_date, end_date)  # Set x-axis limits even with no data
    else:
        axes[0].text(0.5, 0.5, 'No CML data available', ha='center', va='center', transform=axes[0].transAxes, fontsize=12)
        if start_date and end_date:
            axes[0].set_xlim(start_date, end_date)
        axes[1].text(0.5, 0.5, 'No CML data available', ha='center', va='center', transform=axes[1].transAxes, fontsize=12)
        if start_date and end_date:
            axes[1].set_xlim(start_date, end_date)
    
    # 2. PWS Data
    if df_pws is not None and len(df_pws) > 0:
        # Use the already-filtered data (high values already removed), just filter by date if needed
        df_pws_filtered = df_pws[(df_pws.index >= start_date) & (df_pws.index <= end_date)].copy()
        
        if len(df_pws_filtered) > 0:
            # Don't resample - use original 5-minute data as-is
            df_pws_plot = df_pws_filtered.copy()
            
            if pws_stations is not None and len(pws_stations) > 0:
                # Plot specific stations if provided
                available_stations = [s for s in pws_stations if s in df_pws_plot.columns]
                if len(available_stations) > 0:
                    # Limit number of stations if pws_max_stations is set
                    if pws_max_stations is not None and len(available_stations) > pws_max_stations:
                        available_stations = available_stations[:pws_max_stations]
                        title_suffix = f' ({len(available_stations)} of {len(pws_stations)} selected stations)'
                    else:
                        title_suffix = f' ({len(available_stations)} selected stations)'
                    
                    for station_id in available_stations:
                        axes[2].plot(df_pws_plot.index, df_pws_plot[station_id], 
                                    linewidth=1.0, alpha=0.7, label=station_id)
                else:
                    # Fallback to median and mean if specified stations not found
                    # Skip NaN values (filtered high values)
                    pws_median = df_pws_plot.median(axis=1, skipna=True)
                    pws_mean = df_pws_plot.mean(axis=1, skipna=True)
                    axes[2].plot(df_pws_plot.index, pws_median, 'g-', linewidth=1.2, alpha=0.8, label=f'PWS Median ({len(df_pws.columns)} stations)')
                    axes[2].plot(df_pws_plot.index, pws_mean, 'g--', linewidth=1.0, alpha=0.7, label=f'PWS Mean ({len(df_pws.columns)} stations)')
                    title_suffix = f' ({len(df_pws.columns)} stations)'
            else:
                # Default: plot median and mean across all stations, or limit individual stations
                if pws_max_stations is not None and pws_max_stations > 0:
                    # Plot individual stations (up to max_stations) instead of median/mean
                    stations_to_plot = list(df_pws_plot.columns)[:pws_max_stations]
                    for station_id in stations_to_plot:
                        axes[2].plot(df_pws_plot.index, df_pws_plot[station_id], 
                                    linewidth=1.0, alpha=0.7, label=station_id)
                    title_suffix = f' ({len(stations_to_plot)} of {len(df_pws.columns)} stations)'
                else:
                    # Plot median and mean across all stations
                    # Skip NaN values (filtered high values)
                    pws_median = df_pws_plot.median(axis=1, skipna=True)
                    pws_mean = df_pws_plot.mean(axis=1, skipna=True)
                    axes[2].plot(df_pws_plot.index, pws_median, 'g-', linewidth=1.2, alpha=0.8, label=f'PWS Median ({len(df_pws.columns)} stations)')
                    axes[2].plot(df_pws_plot.index, pws_mean, 'g--', linewidth=1.0, alpha=0.7, label=f'PWS Mean ({len(df_pws.columns)} stations)')
                    title_suffix = f' ({len(df_pws.columns)} stations)'
            
            axes[2].set_ylabel('Precipitation (mm) - 5-min Interval', fontsize=11)
            axes[2].set_title(f'PWS Rainfall Data{title_suffix}', fontsize=13, fontweight='bold')
            # Set y-limits only if provided
            if ylims is not None and 'pws' in ylims:
                axes[2].set_ylim(ylims['pws'])
            axes[2].grid(True, alpha=0.3)
            axes[2].legend(loc='upper right', fontsize=9)
        else:
            axes[2].text(0.5, 0.5, 'No PWS data in date range', ha='center', va='center', transform=axes[2].transAxes, fontsize=12)
            if start_date and end_date:
                axes[2].set_xlim(start_date, end_date)
    else:
        axes[2].text(0.5, 0.5, 'No PWS data available', ha='center', va='center', transform=axes[2].transAxes, fontsize=12)
        if start_date and end_date:
            axes[2].set_xlim(start_date, end_date)
    
    # 3. ASOS Data - Handle multiple stations
    if df_asos is not None and len(df_asos) > 0:
        df_asos_filtered = df_asos[(df_asos.index >= start_date) & (df_asos.index <= end_date)].copy()
        
        if len(df_asos_filtered) > 0:
            # Check if ASOS has multiple stations (multiple columns) or single column
            # Note: ASOS data is now 1-minute per-minute precipitation (not hourly accumulation)
            if 'precip_mm' in df_asos_filtered.columns:
                # Single station format (legacy)
                # Data is 1-minute per-minute precipitation
                df_asos_plot = df_asos_filtered[['precip_mm']].copy()
                axes[3].plot(df_asos_plot.index, df_asos_plot['precip_mm'], 
                            color='orange', linewidth=1.0, alpha=0.8, 
                            label='ASOS (1-min)')
                axes[3].set_ylabel('Precipitation (mm/min)', fontsize=11)
                axes[3].set_title('NOAA ASOS Rainfall Data (1-minute)', fontsize=13, fontweight='bold')
            else:
                # Multiple stations format (one column per station)
                # Data is 1-minute per-minute precipitation
                df_asos_plot = df_asos_filtered.copy()
                # Skip NaN values (filtered high values)
                asos_mean = df_asos_plot.mean(axis=1, skipna=True)
                axes[3].plot(df_asos_plot.index, asos_mean, 'orange', linewidth=1.0, alpha=0.8, 
                            label=f'ASOS Mean ({len(df_asos_plot.columns)} stations, 1-min)')
                
                # Plot individual stations if not too many
                if len(df_asos_plot.columns) <= 5:
                    for station_id in df_asos_plot.columns:
                        axes[3].plot(df_asos_plot.index, df_asos_plot[station_id], 
                                    linewidth=0.5, alpha=0.4, label=f'{station_id} (1-min)')
                else:
                    sample_stations = list(df_asos_plot.columns)[:3]
                    for station_id in sample_stations:
                        axes[3].plot(df_asos_plot.index, df_asos_plot[station_id], 
                                    linewidth=0.5, alpha=0.4, label=f'{station_id} (1-min, sample)')
                axes[3].set_ylabel('Precipitation (mm/min)', fontsize=11)
                axes[3].set_title(f'NOAA ASOS Rainfall Data ({len(df_asos_plot.columns)} stations, 1-minute)', fontsize=13, fontweight='bold')
            # Set y-limits only if provided
            if ylims is not None and 'asos' in ylims:
                axes[3].set_ylim(ylims['asos'])
            axes[3].grid(True, alpha=0.3)
            axes[3].legend(loc='upper right', fontsize=9)
        else:
            axes[3].text(0.5, 0.5, 'No ASOS data in date range', ha='center', va='center', transform=axes[3].transAxes, fontsize=12)
            if start_date and end_date:
                axes[3].set_xlim(start_date, end_date)
    else:
        axes[3].text(0.5, 0.5, 'No ASOS data available', ha='center', va='center', transform=axes[3].transAxes, fontsize=12)
        if start_date and end_date:
            axes[3].set_xlim(start_date, end_date)
    
    # Format x-axis - apply to all subplots since they share x-axis
    # Format the bottom axis (last subplot) which will be visible
    axes[3].set_xlabel('Time', fontsize=12, fontweight='bold')
    
    # Calculate time range to determine appropriate formatting
    if start_date and end_date:
        time_range = (end_date - start_date).total_seconds() / 3600  # hours
    else:
        # Try to get from data
        all_times = []
        if df_cml is not None and len(df_cml) > 0:
            all_times.extend([df_cml.index.min(), df_cml.index.max()])
        if df_pws is not None and len(df_pws) > 0:
            all_times.extend([df_pws.index.min(), df_pws.index.max()])
        if df_asos is not None and len(df_asos) > 0:
            all_times.extend([df_asos.index.min(), df_asos.index.max()])
        
        if len(all_times) > 0:
            time_range = (max(all_times) - min(all_times)).total_seconds() / 3600
        else:
            time_range = 24  # default
    
    # Choose format based on time range
    if time_range <= 24:
        date_format = '%Y-%m-%d %H:%M'  # Show full date and time
        major_interval = 2  # hours
    elif time_range <= 168:  # 1 week
        date_format = '%m-%d %H:%M'
        major_interval = 6  # hours
    else:
        date_format = '%Y-%m-%d'
        major_interval = 1  # days
    
    # Apply formatting to the bottom axis (last subplot) - this is the one that shows labels
    # With sharex=True, only the bottom axis shows labels
    ax_bottom = axes[3]
    ax_bottom.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
    
    if time_range <= 24:
        ax_bottom.xaxis.set_major_locator(mdates.HourLocator(interval=major_interval))
        ax_bottom.xaxis.set_minor_locator(mdates.HourLocator(interval=1))  # Minor ticks every hour
    elif time_range <= 168:
        ax_bottom.xaxis.set_major_locator(mdates.HourLocator(interval=major_interval))
        ax_bottom.xaxis.set_minor_locator(mdates.HourLocator(interval=3))  # Minor ticks every 3 hours
    else:
        ax_bottom.xaxis.set_major_locator(mdates.DayLocator(interval=major_interval))
        ax_bottom.xaxis.set_minor_locator(mdates.HourLocator(interval=12))  # Minor ticks every 12 hours
    
    # Rotate labels to avoid overlap and make them visible
    if time_range > 24:
        plt.setp(ax_bottom.xaxis.get_majorticklabels(), rotation=45, ha='right', fontsize=10)
    else:
        plt.setp(ax_bottom.xaxis.get_majorticklabels(), rotation=45, ha='right', fontsize=10)
    
    # Ensure x-axis is visible
    ax_bottom.tick_params(axis='x', which='major', labelsize=10, bottom=True)
    ax_bottom.tick_params(axis='x', which='minor', labelsize=8, bottom=True)
    
    # Make sure x-axis labels are not hidden
    for label in ax_bottom.get_xticklabels():
        label.set_visible(True)
    
    # Adjust layout to prevent label cutoff - leave more space at bottom
    plt.tight_layout(rect=[0, 0.03, 1, 0.98])  # Leave 3% space at bottom for labels
    plt.show()
    
    print("✓ Plotted all three datasets (CML, PWS, ASOS)")


def plot_rain_detection(
    df_cml: Optional[pd.DataFrame],
    df_rain_detection: Optional[pd.DataFrame],
    df_rain_ground_truth: Optional[pd.DataFrame] = None,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None,
    overlay_detection_on_rain: bool = True,
    method_name: str = "Detection Method"
) -> None:
    """
    Plot rain detection results with CML attenuation, detection binary signal, and ground truth.
    
    Parameters
    ----------
    df_cml : pd.DataFrame, optional
        CML data with 'attenuation' column
    df_rain_detection : pd.DataFrame, optional
        Rain detection results with 'attenuation', 'rain_detected', and 'threshold_constant' columns
    df_rain_ground_truth : pd.DataFrame, optional
        Ground truth rain data with 'precip_mm' column for comparison
        This is from PWS (Personal Weather Stations) or ASOS (NOAA Automated Surface Observing System)
    start_date : pd.Timestamp, optional
        Start date for filtering
    end_date : pd.Timestamp, optional
        End date for filtering
    overlay_detection_on_rain : bool, optional
        If True, overlay detection signal on ground truth rain plot for direct comparison.
        If False, show detection in separate panel. Default: True
    """
    if overlay_detection_on_rain:
        fig, axes = plt.subplots(2, 1, figsize=(18, 8), sharex=True)
    else:
        fig, axes = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
    
    # Filter by date if provided
    if start_date is not None and end_date is not None:
        if df_cml is not None:
            df_cml = df_cml[(df_cml.index >= start_date) & (df_cml.index <= end_date)]
        if df_rain_detection is not None:
            df_rain_detection = df_rain_detection[(df_rain_detection.index >= start_date) & 
                                                  (df_rain_detection.index <= end_date)]
        if df_rain_ground_truth is not None:
            df_rain_ground_truth = df_rain_ground_truth[(df_rain_ground_truth.index >= start_date) & 
                                                       (df_rain_ground_truth.index <= end_date)]
    
    # 1. CML Attenuation with Threshold (or Rolling Std)
    is_rolling_std_method = False
    if df_rain_detection is not None and len(df_rain_detection) > 0:
        if 'rolling_std' in df_rain_detection.columns:
            is_rolling_std_method = True
            # Plot rolling std instead of attenuation
            axes[0].plot(df_rain_detection.index, df_rain_detection['rolling_std'], 
                       'b-', linewidth=1.0, alpha=0.7, label='Rolling Std')
            if 'threshold' in df_rain_detection.columns:
                threshold_val = df_rain_detection['threshold'].iloc[0]
                axes[0].axhline(y=threshold_val, color='r', linestyle='--', 
                               linewidth=2.0, alpha=0.8, 
                               label=f'Threshold = {threshold_val} dB')
            axes[0].set_ylabel('Rolling Std (dB)', fontsize=12, fontweight='bold')
            axes[0].set_title(f'Rolling Std with Detection Threshold - {method_name}', fontsize=14, fontweight='bold')
        else:
            # Constant baseline method - plot attenuation
            if df_cml is not None and len(df_cml) > 0:
                df_cml_plot = df_cml[['attenuation']].resample('5min').mean()
                axes[0].plot(df_cml_plot.index, df_cml_plot['attenuation'], 'b-', linewidth=1.0, alpha=0.7, label='CML Attenuation')
                
                # Add threshold line if available
                if 'threshold_constant' in df_rain_detection.columns:
                    threshold_val = df_rain_detection['threshold_constant'].iloc[0]
                    axes[0].axhline(y=threshold_val, color='r', linestyle='--', linewidth=2.0, alpha=0.8, 
                                   label=f'Threshold = {threshold_val} dB (constant)')
                elif 'threshold' in df_rain_detection.columns:
                    # Legacy: rolling threshold as a line (for backward compatibility)
                    axes[0].plot(df_rain_detection.index, df_rain_detection['threshold'], 
                               'r--', linewidth=1.5, alpha=0.7, label='Threshold')
            
            axes[0].set_ylabel('Attenuation (dB)', fontsize=12, fontweight='bold')
            axes[0].set_title(f'CML Attenuation with Detection Threshold - {method_name}', fontsize=14, fontweight='bold')
    elif df_cml is not None and len(df_cml) > 0:
        # Fallback: plot attenuation if no detection data
        df_cml_plot = df_cml[['attenuation']].resample('5min').mean()
        axes[0].plot(df_cml_plot.index, df_cml_plot['attenuation'], 'b-', linewidth=1.0, alpha=0.7, label='CML Attenuation')
        axes[0].set_ylabel('Attenuation (dB)', fontsize=12, fontweight='bold')
        axes[0].set_title(f'CML Attenuation - {method_name}', fontsize=14, fontweight='bold')
    else:
        axes[0].text(0.5, 0.5, 'No CML data available', ha='center', va='center', transform=axes[0].transAxes)
    
    axes[0].grid(True, alpha=0.3, linestyle=':')
    axes[0].legend(loc='upper right', fontsize=10)
    
    # Determine which panel index for rain plot
    if overlay_detection_on_rain:
        rain_panel_idx = 1
    else:
        rain_panel_idx = 2
        # 2. Rain Detection (Binary: 1/0) - separate panel
        if df_rain_detection is not None and len(df_rain_detection) > 0:
            # Plot binary detection as filled area
            axes[1].fill_between(df_rain_detection.index, 0, df_rain_detection['rain_detected'], 
                                 color='red', alpha=0.5, label='Rain Detected (1)')
            axes[1].set_ylabel('Rain Detection\n(1 = Rain, 0 = No Rain)', fontsize=12, fontweight='bold')
            axes[1].set_title('Rain Detection (Binary)', fontsize=14, fontweight='bold')
            axes[1].set_ylim(-0.1, 1.1)
            axes[1].set_yticks([0, 1])
            axes[1].grid(True, alpha=0.3, linestyle=':')
            axes[1].legend(loc='upper right', fontsize=10)
        else:
            axes[1].text(0.5, 0.5, 'No detection data available', ha='center', va='center', transform=axes[1].transAxes)
    
    # Ground Truth Rain with optional detection overlay
    if df_rain_ground_truth is not None and len(df_rain_ground_truth) > 0:
        if 'precip_mm' in df_rain_ground_truth.columns:
            df_rain_plot = df_rain_ground_truth[['precip_mm']].resample('5min').mean()
            
            # Plot ground truth rain
            axes[rain_panel_idx].bar(df_rain_plot.index, df_rain_plot['precip_mm'], 
                        width=pd.Timedelta('5min'), color='green', alpha=0.6, 
                        label='Ground Truth: PWS/ASOS Rain')
            
            # Overlay detection signal if requested
            if overlay_detection_on_rain and df_rain_detection is not None and len(df_rain_detection) > 0:
                # Get max rain value for scaling detection signal
                max_rain = df_rain_plot['precip_mm'].max() if len(df_rain_plot) > 0 else 1.0
                if max_rain == 0:
                    max_rain = 1.0
                
                # Plot detection as overlay (scaled to max rain for visibility)
                detection_scaled = df_rain_detection['rain_detected'] * max_rain * 0.3  # Scale to 30% of max rain
                axes[rain_panel_idx].fill_between(df_rain_detection.index, 0, detection_scaled,
                                                 color='red', alpha=0.4, label='CML Detection (overlay)')
            
            axes[rain_panel_idx].set_ylabel('Precipitation (mm)', fontsize=12, fontweight='bold')
            axes[rain_panel_idx].set_xlabel('Time', fontsize=13, fontweight='bold')
            
            # Title with explanation
            title = 'Ground Truth Rain (PWS/ASOS) vs CML Detection'
            if overlay_detection_on_rain:
                title += ' - Red overlay = CML detection'
            axes[rain_panel_idx].set_title(title, fontsize=14, fontweight='bold')
            axes[rain_panel_idx].grid(True, alpha=0.3, linestyle=':')
            axes[rain_panel_idx].legend(loc='upper right', fontsize=10)
        else:
            axes[rain_panel_idx].text(0.5, 0.5, 'No precipitation data in ground truth', ha='center', va='center', transform=axes[rain_panel_idx].transAxes)
    else:
        axes[rain_panel_idx].text(0.5, 0.5, 'No ground truth data available', ha='center', va='center', transform=axes[rain_panel_idx].transAxes)
    
    # Format x-axis - Fix overlapping issue
    # Use AutoDateLocator to automatically adjust based on time range
    # Only format the bottom axis (rain panel)
    ax_to_format = axes[rain_panel_idx] if len(axes) > rain_panel_idx else axes[-1]
    
    # Calculate time range for formatting
    if df_rain_detection is not None and len(df_rain_detection) > 0:
        time_range = (df_rain_detection.index.max() - df_rain_detection.index.min()).total_seconds() / 3600  # hours
    elif df_cml is not None and len(df_cml) > 0:
        time_range = (df_cml.index.max() - df_cml.index.min()).total_seconds() / 3600
    else:
        time_range = 24  # default
    
    # Adjust tick interval based on time range
    if time_range <= 24:
        # Less than 1 day: show every 2-4 hours
        major_interval = 4
        date_format = '%H:%M'
    elif time_range <= 7 * 24:
        # Less than 1 week: show every 12 hours
        major_interval = 12
        date_format = '%m/%d\n%H:%M'
    else:
        # More than 1 week: show daily
        major_interval = 24
        date_format = '%m/%d'
    
    # Format only the bottom axis
    ax_to_format.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
    ax_to_format.xaxis.set_major_locator(mdates.HourLocator(interval=major_interval))
    ax_to_format.xaxis.set_minor_locator(mdates.HourLocator(interval=major_interval // 2))
    
    # Rotate labels to avoid overlap
    if time_range > 24:
        plt.setp(ax_to_format.xaxis.get_majorticklabels(), rotation=45, ha='right', fontsize=9)
    else:
        plt.setp(ax_to_format.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=10)
    
    ax_to_format.tick_params(axis='x', which='major', length=8, width=1.5)
    ax_to_format.tick_params(axis='x', which='minor', length=4, width=1)
    
    # Hide x-axis labels on upper panels
    for i, ax in enumerate(axes):
        if i < len(axes) - 1:
            ax.set_xticklabels([])
    
    # Add vertical grid lines for better time visibility
    for ax in axes:
        ax.grid(True, alpha=0.2, linestyle='-', which='major', axis='x')
        ax.grid(True, alpha=0.1, linestyle=':', which='minor', axis='x')
    
    plt.tight_layout()
    plt.show()
    
    print("✓ Rain detection plots generated")


def plot_both_detection_methods(
    df_cml: Optional[pd.DataFrame],
    df_const_detection: Optional[pd.DataFrame],
    df_rolling_detection: Optional[pd.DataFrame],
    df_rain_ground_truth: Optional[pd.DataFrame] = None,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None,
    overlay_detection_on_rain: bool = True
) -> None:
    """
    Plot both detection methods (Constant Baseline and Rolling Std) side by side for comparison.
    
    Parameters
    ----------
    df_cml : pd.DataFrame, optional
        CML data with 'attenuation' column
    df_const_detection : pd.DataFrame, optional
        Constant baseline detection results
    df_rolling_detection : pd.DataFrame, optional
        Rolling std detection results
    df_rain_ground_truth : pd.DataFrame, optional
        Ground truth rain data with 'precip_mm' column
    start_date : pd.Timestamp, optional
        Start date for filtering
    end_date : pd.Timestamp, optional
        End date for filtering
    overlay_detection_on_rain : bool, optional
        If True, overlay detection signal on ground truth rain plot
    """
    # Filter by date if provided
    if start_date is not None and end_date is not None:
        if df_cml is not None:
            df_cml = df_cml[(df_cml.index >= start_date) & (df_cml.index <= end_date)]
        if df_const_detection is not None:
            df_const_detection = df_const_detection[(df_const_detection.index >= start_date) & 
                                                    (df_const_detection.index <= end_date)]
        if df_rolling_detection is not None:
            df_rolling_detection = df_rolling_detection[(df_rolling_detection.index >= start_date) & 
                                                        (df_rolling_detection.index <= end_date)]
        if df_rain_ground_truth is not None:
            df_rain_ground_truth = df_rain_ground_truth[(df_rain_ground_truth.index >= start_date) & 
                                                        (df_rain_ground_truth.index <= end_date)]
    
    if overlay_detection_on_rain:
        fig, axes = plt.subplots(4, 1, figsize=(18, 14), sharex=True)
    else:
        fig, axes = plt.subplots(6, 1, figsize=(18, 16), sharex=True)
    
    # Determine panel indices
    if overlay_detection_on_rain:
        const_atten_idx = 0
        const_rain_idx = 1
        rolling_atten_idx = 2
        rolling_rain_idx = 3
    else:
        const_atten_idx = 0
        const_det_idx = 1
        const_rain_idx = 2
        rolling_atten_idx = 3
        rolling_det_idx = 4
        rolling_rain_idx = 5
    
    # ===== CONSTANT BASELINE METHOD =====
    # Attenuation with threshold
    if df_cml is not None and len(df_cml) > 0:
        df_cml_plot = df_cml[['attenuation']].resample('5min').mean()
        axes[const_atten_idx].plot(df_cml_plot.index, df_cml_plot['attenuation'], 
                                   'b-', linewidth=1.0, alpha=0.7, label='CML Attenuation')
        
        if df_const_detection is not None and len(df_const_detection) > 0:
            if 'threshold_constant' in df_const_detection.columns:
                threshold_val = df_const_detection['threshold_constant'].iloc[0]
                axes[const_atten_idx].axhline(y=threshold_val, color='r', linestyle='--', 
                                             linewidth=2.0, alpha=0.8, 
                                             label=f'Threshold = {threshold_val} dB (constant)')
        
        axes[const_atten_idx].set_ylabel('Attenuation (dB)', fontsize=12, fontweight='bold')
        axes[const_atten_idx].set_title('Constant Baseline Method - CML Attenuation with Threshold', 
                                       fontsize=14, fontweight='bold')
        axes[const_atten_idx].grid(True, alpha=0.3, linestyle=':')
        axes[const_atten_idx].legend(loc='upper right', fontsize=10)
    
    # Detection binary (if not overlay)
    if not overlay_detection_on_rain and df_const_detection is not None and len(df_const_detection) > 0:
        axes[const_det_idx].fill_between(df_const_detection.index, 0, df_const_detection['rain_detected'], 
                                         color='red', alpha=0.5, label='Rain Detected (1)')
        axes[const_det_idx].set_ylabel('Rain Detection\n(1 = Rain, 0 = No Rain)', fontsize=12, fontweight='bold')
        axes[const_det_idx].set_title('Constant Baseline Method - Rain Detection (Binary)', 
                                     fontsize=14, fontweight='bold')
        axes[const_det_idx].set_ylim(-0.1, 1.1)
        axes[const_det_idx].set_yticks([0, 1])
        axes[const_det_idx].grid(True, alpha=0.3, linestyle=':')
        axes[const_det_idx].legend(loc='upper right', fontsize=10)
    
    # Ground truth rain with detection overlay
    if df_rain_ground_truth is not None and len(df_rain_ground_truth) > 0:
        if 'precip_mm' in df_rain_ground_truth.columns:
            df_rain_plot = df_rain_ground_truth[['precip_mm']].resample('5min').mean()
            axes[const_rain_idx].bar(df_rain_plot.index, df_rain_plot['precip_mm'], 
                        width=pd.Timedelta('5min'), color='green', alpha=0.6, 
                        label='Ground Truth: PWS/ASOS Rain')
            
            if overlay_detection_on_rain and df_const_detection is not None and len(df_const_detection) > 0:
                max_rain = df_rain_plot['precip_mm'].max() if len(df_rain_plot) > 0 else 1.0
                if max_rain == 0:
                    max_rain = 1.0
                detection_scaled = df_const_detection['rain_detected'] * max_rain * 0.3
                axes[const_rain_idx].fill_between(df_const_detection.index, 0, detection_scaled,
                                                 color='red', alpha=0.4, label='CML Detection (Constant Baseline)')
            
            axes[const_rain_idx].set_ylabel('Precipitation (mm)', fontsize=12, fontweight='bold')
            title = 'Constant Baseline Method - Ground Truth vs Detection'
            if overlay_detection_on_rain:
                title += ' (Red overlay = detection)'
            axes[const_rain_idx].set_title(title, fontsize=14, fontweight='bold')
            axes[const_rain_idx].grid(True, alpha=0.3, linestyle=':')
            axes[const_rain_idx].legend(loc='upper right', fontsize=10)
    
    # ===== ROLLING STD METHOD =====
    # Rolling std with threshold
    if df_rolling_detection is not None and len(df_rolling_detection) > 0:
        if 'rolling_std' in df_rolling_detection.columns:
            axes[rolling_atten_idx].plot(df_rolling_detection.index, df_rolling_detection['rolling_std'], 
                                         'b-', linewidth=1.0, alpha=0.7, label='Rolling Std')
            
            if 'threshold' in df_rolling_detection.columns:
                threshold_val = df_rolling_detection['threshold'].iloc[0]
                axes[rolling_atten_idx].axhline(y=threshold_val, color='r', linestyle='--', 
                                               linewidth=2.0, alpha=0.8, 
                                               label=f'Threshold = {threshold_val} dB')
        
        axes[rolling_atten_idx].set_ylabel('Rolling Std (dB)', fontsize=12, fontweight='bold')
        axes[rolling_atten_idx].set_title('Rolling Std Method - Rolling Standard Deviation with Threshold', 
                                         fontsize=14, fontweight='bold')
        axes[rolling_atten_idx].grid(True, alpha=0.3, linestyle=':')
        axes[rolling_atten_idx].legend(loc='upper right', fontsize=10)
    
    # Detection binary (if not overlay)
    if not overlay_detection_on_rain and df_rolling_detection is not None and len(df_rolling_detection) > 0:
        axes[rolling_det_idx].fill_between(df_rolling_detection.index, 0, df_rolling_detection['rain_detected'], 
                                          color='red', alpha=0.5, label='Rain Detected (1)')
        axes[rolling_det_idx].set_ylabel('Rain Detection\n(1 = Rain, 0 = No Rain)', fontsize=12, fontweight='bold')
        axes[rolling_det_idx].set_title('Rolling Std Method - Rain Detection (Binary)', 
                                      fontsize=14, fontweight='bold')
        axes[rolling_det_idx].set_ylim(-0.1, 1.1)
        axes[rolling_det_idx].set_yticks([0, 1])
        axes[rolling_det_idx].grid(True, alpha=0.3, linestyle=':')
        axes[rolling_det_idx].legend(loc='upper right', fontsize=10)
    
    # Ground truth rain with detection overlay
    if df_rain_ground_truth is not None and len(df_rain_ground_truth) > 0:
        if 'precip_mm' in df_rain_ground_truth.columns:
            df_rain_plot = df_rain_ground_truth[['precip_mm']].resample('5min').mean()
            axes[rolling_rain_idx].bar(df_rain_plot.index, df_rain_plot['precip_mm'], 
                        width=pd.Timedelta('5min'), color='green', alpha=0.6, 
                        label='Ground Truth: PWS/ASOS Rain')
            
            if overlay_detection_on_rain and df_rolling_detection is not None and len(df_rolling_detection) > 0:
                max_rain = df_rain_plot['precip_mm'].max() if len(df_rain_plot) > 0 else 1.0
                if max_rain == 0:
                    max_rain = 1.0
                detection_scaled = df_rolling_detection['rain_detected'] * max_rain * 0.3
                axes[rolling_rain_idx].fill_between(df_rolling_detection.index, 0, detection_scaled,
                                                    color='red', alpha=0.4, label='CML Detection (Rolling Std)')
            
            axes[rolling_rain_idx].set_ylabel('Precipitation (mm)', fontsize=12, fontweight='bold')
            axes[rolling_rain_idx].set_xlabel('Time', fontsize=13, fontweight='bold')
            title = 'Rolling Std Method - Ground Truth vs Detection'
            if overlay_detection_on_rain:
                title += ' (Red overlay = detection)'
            axes[rolling_rain_idx].set_title(title, fontsize=14, fontweight='bold')
            axes[rolling_rain_idx].grid(True, alpha=0.3, linestyle=':')
            axes[rolling_rain_idx].legend(loc='upper right', fontsize=10)
    
    # Format x-axis - only on bottom plot
    ax_to_format = axes[rolling_rain_idx]
    
    # Calculate time range for formatting
    if df_rolling_detection is not None and len(df_rolling_detection) > 0:
        time_range = (df_rolling_detection.index.max() - df_rolling_detection.index.min()).total_seconds() / 3600
    elif df_const_detection is not None and len(df_const_detection) > 0:
        time_range = (df_const_detection.index.max() - df_const_detection.index.min()).total_seconds() / 3600
    elif df_cml is not None and len(df_cml) > 0:
        time_range = (df_cml.index.max() - df_cml.index.min()).total_seconds() / 3600
    else:
        time_range = 24
    
    # Adjust tick interval based on time range
    if time_range <= 24:
        major_interval = 4
        date_format = '%H:%M'
    elif time_range <= 7 * 24:
        major_interval = 12
        date_format = '%m/%d\n%H:%M'
    else:
        major_interval = 24
        date_format = '%m/%d'
    
    # Format only the bottom axis
    ax_to_format.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
    ax_to_format.xaxis.set_major_locator(mdates.HourLocator(interval=major_interval))
    ax_to_format.xaxis.set_minor_locator(mdates.HourLocator(interval=major_interval // 2))
    
    if time_range > 24:
        plt.setp(ax_to_format.xaxis.get_majorticklabels(), rotation=45, ha='right', fontsize=9)
    else:
        plt.setp(ax_to_format.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=10)
    
    ax_to_format.tick_params(axis='x', which='major', length=8, width=1.5)
    ax_to_format.tick_params(axis='x', which='minor', length=4, width=1)
    
    # Hide x-axis labels on upper panels
    for i, ax in enumerate(axes):
        if i < len(axes) - 1:
            ax.set_xticklabels([])
    
    # Add vertical grid lines
    for ax in axes:
        ax.grid(True, alpha=0.2, linestyle='-', which='major', axis='x')
        ax.grid(True, alpha=0.1, linestyle=':', which='minor', axis='x')
    
    plt.tight_layout()
    plt.show()
    
    print("✓ Combined plots generated for both detection methods")


def plot_weather_subplots(
    processed_data: Dict[str, pd.DataFrame],
    params: List[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    figsize: tuple = (14, 14),
    ylims: Optional[Union[List[float], Dict[str, List[float]]]] = None,
    title_prefix: str = ""
) -> tuple:
    """
    Plot multiple weather parameters as subplots.
    
    Parameters
    ----------
    processed_data : dict
        Dictionary of DataFrames keyed by station_id, each with datetime index
    params : list of str
        List of parameter names to plot (e.g., ['precip_mm', 'temp_c', 'wind_speed_ms'])
    start_date : pd.Timestamp
        Start date for filtering
    end_date : pd.Timestamp
        End date for filtering
    figsize : tuple, optional
        Figure size (width, height). Default is (14, 14)
    ylims : list or dict, optional
        Y-axis limits. Can be:
        - List [ymin, ymax]: Applied to all subplots
        - Dict {param: [ymin, ymax]}: Different limits per parameter
    title_prefix : str, optional
        Prefix for plot titles
    
    Returns
    -------
    fig, axes : matplotlib figure and axes objects
    """
    n_params = len(params)
    fig, axes = plt.subplots(n_params, 1, figsize=figsize, sharex=True)
    
    # Handle single subplot case (axes is not a list)
    if n_params == 1:
        axes = [axes]
    
    # Determine ylims format
    if ylims is not None:
        if isinstance(ylims, list) and len(ylims) == 2:
            # Single ylim applied to all subplots
            ylims_dict = {param: ylims for param in params}
        elif isinstance(ylims, dict):
            # Different ylims per parameter
            ylims_dict = ylims
        else:
            ylims_dict = None
    else:
        ylims_dict = None
    
    # Plot each parameter
    for idx, param in enumerate(params):
        ax = axes[idx]
        
        # Plot data for each station
        for station_id, df in processed_data.items():
            if param in df.columns:
                df_filtered = df[(df['datetime'] >= start_date) & (df['datetime'] <= end_date)].copy()
                if len(df_filtered) > 0:
                    ax.plot(df_filtered['datetime'], df_filtered[param], 
                           label=station_id, linewidth=1.5, alpha=0.8)
        
        # Set labels and title
        param_label = param.replace('_', ' ').title()
        ax.set_ylabel(param_label, fontsize=12, fontweight='bold')
        if title_prefix:
            ax.set_title(f'{title_prefix} - {param_label}', fontsize=13, fontweight='bold')
        else:
            ax.set_title(param_label, fontsize=13, fontweight='bold')
        
        # Apply ylims if specified
        if ylims_dict and param in ylims_dict:
            ax.set_ylim(ylims_dict[param])
        
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best', fontsize=10)
    
    # Format x-axis on bottom subplot
    axes[-1].set_xlabel('Date (UTC)', fontsize=12, fontweight='bold')
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    locator = AutoDateLocator(maxticks=20)
    axes[-1].xaxis.set_major_locator(locator)
    plt.setp(axes[-1].xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    plt.tight_layout()
    
    return fig, axes

