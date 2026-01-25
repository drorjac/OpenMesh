"""
Plotting functions for OpenMesh data analysis.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import AutoDateLocator
from typing import Optional, List, Dict, Union, Tuple






def plot_subnetwork(ds_links, analysis_data, cml_to_pws,
                              sublink_id='sublink_1',
                              date_range=None,
                              figsize=(18, 12),
                              y_lim=None,
                              stats='all',
                              plot_type=None,
                              layout='horizontal',
                              rainfall_source='both'):
    """
    Plot CML RSL + ASOS/PWS mean rainfall
    
    Parameters:
    -----------
    stats : str
        'all' = show all stations, 'mean' = show mean only
    plot_type : str, optional
        ASOS station ID (e.g., 'LGA') to use precip_type for grid coloring
    layout : str
        'horizontal' (default) or 'vertical'
    rainfall_source : str
        'both' (default), 'asos', or 'pws'
    """
    import matplotlib.gridspec as gridspec
    
    if y_lim is None:
        y_lim = [0, 3]
    if len(cml_to_pws) == 0:
        print("✗ No CML links to plot")
        return None
    
    # Define color_map FIRST (before it's used)
    color_map = {'NP': 'white', 'SN': 'cyan', 'RA': plt.cm.tab10(0), 'UP': 'gray', 'FZRA': 'gray', 'PL': 'gray'}
    
    # Validate CML IDs
    available_cml_ids = [str(cid) for cid in ds_links.cml_id.values]
    valid_cml_to_pws = {cid: pws for cid, pws in cml_to_pws.items() 
                        if str(cid) in available_cml_ids}
    
    if len(valid_cml_to_pws) == 0:
        print("✗ No valid CML links to plot")
        return None
    
    # Filter by date range
    if date_range:
        start_date, end_date = date_range
        ds_plot = ds_links.sel(time=slice(start_date, end_date))
    else:
        ds_plot = ds_links
        start_date = pd.to_datetime(ds_links.time.values[0])
        end_date = pd.to_datetime(ds_links.time.values[-1])
    
    # Get ASOS and PWS mean rainfall
    df_asos_mean = None
    df_pws_mean = None
    
    if rainfall_source in ['both', 'asos'] and 'rainfall_amount' in analysis_data.get('asos', {}):
        df_asos = analysis_data['asos']['rainfall_amount'].copy()
        if date_range:
            df_asos = df_asos[(df_asos.index >= start_date) & (df_asos.index <= end_date)]
        df_asos_mean = df_asos.mean(axis=1)
    
    if rainfall_source in ['both', 'pws'] and 'rainfall_amount' in analysis_data.get('pws', {}):
        df_pws = analysis_data['pws']['rainfall_amount'].copy()
        if date_range:
            df_pws = df_pws[(df_pws.index >= start_date) & (df_pws.index <= end_date)]
        all_matched_pws = list(set(pws for pws_list in valid_cml_to_pws.values() for pws in pws_list))
        matched_pws_cols = [p for p in all_matched_pws if p in df_pws.columns]
        if matched_pws_cols:
            df_pws_mean = df_pws[matched_pws_cols].mean(axis=1)
    
    # Get precip_type for grid coloring - RESAMPLE to reduce spans
    precip_periods = {}
    if plot_type and 'precip_type' in analysis_data.get('asos', {}):
        if plot_type in analysis_data['asos']['precip_type'].columns:
            precip_series = analysis_data['asos']['precip_type'][plot_type].copy()
            if date_range:
                precip_series = precip_series.loc[start_date:end_date]
            # Resample to 1H to reduce number of spans (much faster)
            precip_series = precip_series.resample('1H').first()
            # Group consecutive periods of same type
            for ptype in precip_series.unique():
                if pd.notna(ptype) and ptype != 'NP' and ptype in color_map:
                    mask = precip_series == ptype
                    if mask.any():
                        # Get start/end of consecutive periods
                        periods = []
                        in_period = False
                        period_start = None
                        for t, val in zip(precip_series.index, mask):
                            if val and not in_period:
                                period_start = t
                                in_period = True
                            elif not val and in_period:
                                periods.append((period_start, t))
                                in_period = False
                        if in_period:
                            periods.append((period_start, precip_series.index[-1] + pd.Timedelta(hours=1)))
                        precip_periods[ptype] = periods
    
    if layout == 'vertical':
        # VERTICAL LAYOUT: All CMLs in ONE panel (top), Rainfall on bottom
        # Get all CMLs with specified sublink_id only
        all_links = []
        for cml_id in valid_cml_to_pws.keys():
            all_links.append((str(cml_id), sublink_id))
        
        fig = plt.figure(figsize=(20, 10))
        gs = gridspec.GridSpec(2, 1, hspace=0.15, height_ratios=[3, 2])
        
        # Single RSL panel for all links
        ax_rsl = fig.add_subplot(gs[0, 0])
        colors_rsl = plt.cm.tab10(np.linspace(0, 1, len(all_links)))
        
        for idx, (cml_id, sublink_id_plot) in enumerate(all_links):
            try:
                freq = float(ds_links['frequency'].sel(cml_id=cml_id, sublink_id=sublink_id_plot).values)
                length = float(ds_links['length'].sel(cml_id=cml_id).values)
                rsl = ds_plot['rsl'].sel(cml_id=cml_id, sublink_id=sublink_id_plot)
                
                label = f'CML {cml_id} (L={length:.0f}m, f={freq/1000:.1f}GHz)'
                ax_rsl.plot(rsl.time.values, rsl.values, '-', lw=1.5, alpha=0.8, 
                           color=colors_rsl[idx], label=label)
            except (KeyError, ValueError):
                continue
        
        ax_rsl.set_ylabel('RSL (dBm)', fontsize=16, fontweight='bold')
        ax_rsl.set_title('All CML RSL Activations', fontsize=18, fontweight='bold')
        ax_rsl.tick_params(labelsize=14)
        ax_rsl.grid(True, alpha=0.3)
        ax_rsl.legend(loc='upper right', fontsize=11, ncol=2)
        ax_rsl.set_xticklabels([])
        
        # Plot Rainfall with precip_type grid (bottom)
        ax_rain = fig.add_subplot(gs[1, 0], sharex=ax_rsl)
        
        # Color background by precip_type (optimized - use grouped periods)
        if precip_periods:
            for ptype, periods in precip_periods.items():
                color = color_map.get(ptype, 'lightgray')
                for period_start, period_end in periods:
                    ax_rain.axvspan(period_start, period_end, alpha=0.3, color=color, zorder=0)
        
        # Plot rainfall means
        if df_asos_mean is not None and len(df_asos_mean) > 0:
            ax_rain.plot(df_asos_mean.index, df_asos_mean.values, 'orange', lw=2.5, 
                        label='ASOS Mean', zorder=5, alpha=0.9)
        if df_pws_mean is not None and len(df_pws_mean) > 0:
            ax_rain.plot(df_pws_mean.index, df_pws_mean.values, 'green', lw=2.5, 
                        label='PWS Mean', zorder=5, alpha=0.9)
        
        ax_rain.set_ylabel('Rainfall (mm)', fontsize=16, fontweight='bold')
        ax_rain.set_xlabel('Time', fontsize=16, fontweight='bold')
        ax_rain.set_ylim(y_lim)
        ax_rain.tick_params(labelsize=14)
        ax_rain.legend(loc='upper right', fontsize=14)
        ax_rain.grid(True, alpha=0.3, zorder=1)
        ax_rain.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
        ax_rain.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax_rain.xaxis.get_majorticklabels(), rotation=45, ha='right', fontsize=14)
        
        title = 'CML RSL Activations + ASOS/PWS Mean Rainfall'
        if plot_type:
            title += f' (Precip Type Grid: {plot_type})'
        plt.suptitle(title, fontsize=18, fontweight='bold', y=0.995)
        plt.tight_layout()
        return fig, (ax_rsl, ax_rain)
    
    else:
        # HORIZONTAL LAYOUT (default): One row per CML, 3 columns (RSL, ASOS, PWS)
        n_cmls = len(valid_cml_to_pws)
        fig, axes = plt.subplots(n_cmls, 3, figsize=(figsize[0]*1.5, figsize[1]), sharex=True)
        if n_cmls == 1:
            axes = axes.reshape(1, -1)
        
        for idx, (cml_id, pws_stations) in enumerate(valid_cml_to_pws.items()):
            cml_id_str = str(cml_id)
            
            # Panel 1: CML RSL
            try:
                freq = float(ds_links['frequency'].sel(cml_id=cml_id_str, sublink_id=sublink_id).values)
                if not np.isnan(freq):
                    rsl = ds_plot['rsl'].sel(cml_id=cml_id_str, sublink_id=sublink_id)
                    length = float(ds_links['length'].sel(cml_id=cml_id_str).values)
                    axes[idx, 0].plot(ds_plot['time'].values, rsl.values, 'b-', lw=1.5, alpha=0.8)
                    axes[idx, 0].set_ylabel('RSL (dBm)', fontsize=12, fontweight='bold')
                    axes[idx, 0].set_title(f'CML {cml_id} - {sublink_id}\n(L={length:.0f}m, f={freq/1000:.1f}GHz)', 
                                          fontsize=13, fontweight='bold')
                    axes[idx, 0].grid(True, alpha=0.3)
            except KeyError:
                axes[idx, 0].text(0.5, 0.5, f'CML {cml_id}\nNo data', ha='center', va='center', 
                                transform=axes[idx, 0].transAxes, fontsize=12)
            
            # Panel 2: ASOS Mean
            if df_asos_mean is not None:
                axes[idx, 1].plot(df_asos_mean.index, df_asos_mean.values, 'orange', lw=2, label='ASOS Mean')
                axes[idx, 1].set_ylabel('Rainfall (mm)', fontsize=12, fontweight='bold')
                axes[idx, 1].set_title('ASOS Mean Rainfall', fontsize=13, fontweight='bold')
                axes[idx, 1].set_ylim(y_lim)
                axes[idx, 1].grid(True, alpha=0.3)
                axes[idx, 1].legend(loc='upper right', fontsize=10)
            
            # Panel 3: PWS Mean
            if df_pws_mean is not None:
                axes[idx, 2].plot(df_pws_mean.index, df_pws_mean.values, 'green', lw=2, label='PWS Mean')
                axes[idx, 2].set_ylabel('Rainfall (mm)', fontsize=12, fontweight='bold')
                axes[idx, 2].set_title('PWS Mean Rainfall', fontsize=13, fontweight='bold')
                axes[idx, 2].set_ylim(y_lim)
                axes[idx, 2].grid(True, alpha=0.3)
                axes[idx, 2].legend(loc='upper right', fontsize=10)
            
            # Color code by precip_type (optimized - use grouped periods)
            if precip_periods:
                for ptype, periods in precip_periods.items():
                    color = color_map.get(ptype, 'lightgray')
                    for period_start, period_end in periods:
                        for col in range(3):
                            axes[idx, col].axvspan(period_start, period_end, alpha=0.2, color=color, zorder=0)
        
        # Format x-axis
        for ax in axes[-1, :]:
            ax.set_xlabel('Time', fontsize=12, fontweight='bold')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        title = 'CML RSL + ASOS/PWS Mean Rainfall'
        if plot_type:
            title += f' (Precip Type: {plot_type})'
        plt.suptitle(title, fontsize=16, fontweight='bold', y=0.995)
        plt.tight_layout()
        return fig, axes



def plot_weather_params(analysis_data, 
                        parameter='rainfall_amount',
                        mode='raw',  # 'raw', 'stats', 'overlay'
                        resample=None,
                        start_date=None,
                        end_date=None,
                        outlier_method='clip',
                        outlier_percentile=(1, 99.99),
                        ylim=None,  # NEW: Set y-axis limits
                        figsize=(16, 8),
                        debug=False,
                        max_stations=10):
    """
    Plot weather parameters from ASOS and PWS.
    
    Parameters
    ----------
    mode : str
        'raw' = individual stations
        'stats' = mean/median/min-max only
        'overlay' = stations (faded) + mean/median (bold)  ← NEW!
    ylim : float, tuple, or dict, optional
        Y-axis limits. Options:
        - None (default): auto-scale
        - float: e.g., 5 sets [0, 5] for both plots
        - tuple: e.g., (0, 10) sets limits for both plots
        - dict: e.g., {'asos': (0, 5), 'pws': (0, 3)} for separate limits
    max_stations : int or None
        Maximum number of stations to plot. If None, plots all stations.
        Default is 10.
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import pandas as pd
    import numpy as np
    
    # Unit mapping
    def get_unit(param):
        param_lower = param.lower()
        if 'temperature' in param_lower or 'temp' in param_lower:
            return '°C'
        elif 'dewpoint' in param_lower or 'dew' in param_lower:
            return '°C'
        elif 'rainfall' in param_lower or 'precip' in param_lower:
            return 'mm/h' if 'rate' in param_lower else 'mm'
        elif 'wind_speed' in param_lower:
            return 'm/s'
        elif 'pressure' in param_lower:
            return 'hPa'
        elif 'humidity' in param_lower:
            return '%'
        else:
            return ''
    
    def handle_outliers(df, method='clip', percentile=(1, 99)):
        if method == 'none':
            return df
        df_clean = df.copy()
        for col in df_clean.columns:
            if df_clean[col].isna().all():
                continue
                
            valid_data = df_clean[col].dropna()
            if len(valid_data) == 0:
                continue
                
            lower = valid_data.quantile(percentile[0] / 100)
            upper = valid_data.quantile(percentile[1] / 100)
            
            if 'rainfall' in parameter.lower() or 'precip' in parameter.lower():
                if method == 'clip':
                    if upper > 0:
                        df_clean[col] = df_clean[col].clip(lower=0, upper=upper)
                elif method == 'remove':
                    if upper > 0:
                        df_clean.loc[df_clean[col] > upper, col] = np.nan
            else:
                if method == 'clip':
                    df_clean[col] = df_clean[col].clip(lower=lower, upper=upper)
                elif method == 'remove':
                    df_clean.loc[(df_clean[col] < lower) | (df_clean[col] > upper), col] = np.nan
        return df_clean
    
    def parse_ylim(ylim_input, plot_type):
        """Parse ylim parameter for specific plot type."""
        if ylim_input is None:
            return None
        
        # Dict: separate limits for ASOS and PWS
        if isinstance(ylim_input, dict):
            return ylim_input.get(plot_type.lower())
        
        # Single number: [0, value]
        if isinstance(ylim_input, (int, float)):
            return (0, ylim_input)
        
        # Tuple: use as-is
        if isinstance(ylim_input, tuple):
            return ylim_input
        
        return None
    
    # Check if parameter exists
    has_asos = parameter in analysis_data.get('asos', {})
    has_pws = parameter in analysis_data.get('pws', {})
    
    if not has_asos and not has_pws:
        print(f"✗ Parameter '{parameter}' not found")
        print(f"  Available ASOS: {list(analysis_data.get('asos', {}).keys())}")
        print(f"  Available PWS: {list(analysis_data.get('pws', {}).keys())}")
        return None
    
    # Get unit
    unit = get_unit(parameter)
    unit_str = f' ({unit})' if unit else ''
    
    # Setup figure
    n_plots = sum([has_asos, has_pws])
    fig, axes = plt.subplots(n_plots, 1, figsize=figsize, sharex=True)
    if n_plots == 1:
        axes = [axes]
    
    plot_idx = 0
    colors = plt.cm.tab10.colors
    
    # ===== ASOS =====
    if has_asos:
        ax = axes[plot_idx]
        df = analysis_data['asos'][parameter].copy()
        
        # CLEAN DATA
        df = df.select_dtypes(include=[np.number])
        df.index = pd.to_datetime(df.index)
        
        # Filter dates
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]
        
        # Handle outliers
        df = handle_outliers(df, method=outlier_method, percentile=outlier_percentile)
        
        # Resample
        if resample:
            agg = 'sum' if 'rain' in parameter else 'mean'
            df = df.resample(resample).agg(agg)
            if 'rain' in parameter:
                df = df.fillna(0)
        
        # Plot
        if mode == 'raw' and len(df) > 0 and len(df.columns) > 0:
            cols_to_plot = df.columns[:max_stations] if max_stations else df.columns
            for idx, col in enumerate(cols_to_plot):
                ax.plot(df.index, df[col].values,
                       color=colors[idx % len(colors)],
                       label=str(col),
                       alpha=0.7, linewidth=1.5)
            ax.legend(loc='upper right', fontsize=11, framealpha=0.9)
            if max_stations and len(df.columns) > max_stations:
                print(f"  ℹ Showing first {max_stations} of {len(df.columns)} ASOS stations")
        
        elif mode == 'stats' and len(df) > 0 and len(df.columns) > 0:
            mean_vals = df.mean(axis=1)
            median_vals = df.median(axis=1)
            min_vals = df.min(axis=1)
            max_vals = df.max(axis=1)
            
            ax.plot(df.index, mean_vals.values, 'b-', linewidth=2, label='Mean', alpha=0.8)
            ax.plot(df.index, median_vals.values, 'g-', linewidth=2, label='Median', alpha=0.8)
            ax.fill_between(df.index, min_vals.values, max_vals.values, 
                           alpha=0.2, color='gray', label='Min-Max')
            ax.legend(loc='upper right', fontsize=11, framealpha=0.9)
        
        elif mode == 'overlay' and len(df) > 0 and len(df.columns) > 0:
            # NEW MODE: Show all stations faded + mean/median bold
            # Plot all stations with low intensity (no labels)
            for col in df.columns:
                ax.plot(df.index, df[col].values,
                       color='gray', alpha=0.15, linewidth=0.8)
            
            # Plot mean and median with high intensity
            mean_vals = df.mean(axis=1)
            median_vals = df.median(axis=1)
            
            ax.plot(df.index, mean_vals.values, 'b-', linewidth=2.5, 
                   label='Mean', alpha=0.9, zorder=10)
            ax.plot(df.index, median_vals.values, 'g-', linewidth=2.5, 
                   label='Median', alpha=0.9, zorder=10)
            
            ax.legend(loc='upper right', fontsize=12, framealpha=0.9)
        else:
            ax.text(0.5, 0.5, 'No data in date range', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=14)
        
        # Set y-axis limits
        ylim_asos = parse_ylim(ylim, 'asos')
        if ylim_asos:
            ax.set_ylim(ylim_asos)
        
        # Format
        n_stations = len(df.columns)
        shown = min(n_stations, max_stations) if (mode == 'raw' and max_stations) else n_stations
        param_label = parameter.replace('_', ' ').title()
        
        if mode == 'overlay':
            title = f"ASOS - {param_label}{unit_str} ({n_stations} stations)"
        else:
            title = f"ASOS - {param_label}{unit_str} "
            title += f"({shown}/{n_stations} stations)" if (mode == 'raw' and max_stations and shown < n_stations) else f"({n_stations} stations)"
        
        ax.set_title(title, fontsize=15, fontweight='bold')
        ax.set_ylabel(f"{param_label}{unit_str}", fontsize=13, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=12)
        
        plot_idx += 1
    
    # ===== PWS =====
    if has_pws:
        ax = axes[plot_idx]
        df = analysis_data['pws'][parameter].copy()
        
        # CLEAN DATA
        df = df.select_dtypes(include=[np.number])
        df.index = pd.to_datetime(df.index)
        
        # Filter dates
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]
        
        # Handle outliers
        df = handle_outliers(df, method=outlier_method, percentile=outlier_percentile)
        
        # Resample
        if resample:
            agg = 'sum' if 'rain' in parameter else 'mean'
            df = df.resample(resample).agg(agg)
            if 'rain' in parameter:
                df = df.fillna(0)
        
        # Plot
        if mode == 'raw' and len(df) > 0 and len(df.columns) > 0:
            cols_to_plot = df.columns[:max_stations] if max_stations else df.columns
            
            for idx, col in enumerate(cols_to_plot):
                ax.plot(df.index, df[col].values,
                       color=colors[idx % len(colors)],
                       label=str(col),
                       alpha=0.7, linewidth=1.5)
            
            ax.legend(loc='upper right', fontsize=11, framealpha=0.9, ncol=2)
            if max_stations and len(df.columns) > max_stations:
                print(f"  ℹ Showing first {max_stations} of {len(df.columns)} PWS stations")
        
        elif mode == 'stats' and len(df) > 0 and len(df.columns) > 0:
            mean_vals = df.mean(axis=1)
            median_vals = df.median(axis=1)
            min_vals = df.min(axis=1)
            max_vals = df.max(axis=1)
            
            ax.plot(df.index, mean_vals.values, 'b-', linewidth=2, label='Mean', alpha=0.8)
            ax.plot(df.index, median_vals.values, 'g-', linewidth=2, label='Median', alpha=0.8)
            ax.fill_between(df.index, min_vals.values, max_vals.values, 
                           alpha=0.2, color='gray', label='Min-Max')
            ax.legend(loc='upper right', fontsize=11, framealpha=0.9)
        
        elif mode == 'overlay' and len(df) > 0 and len(df.columns) > 0:
            # NEW MODE: Show all stations faded + mean/median bold
            # Plot all stations with low intensity (no labels)
            for col in df.columns:
                ax.plot(df.index, df[col].values,
                       color='gray', alpha=0.15, linewidth=0.8)
            
            # Plot mean and median with high intensity
            mean_vals = df.mean(axis=1)
            median_vals = df.median(axis=1)
            
            ax.plot(df.index, mean_vals.values, 'b-', linewidth=2.5, 
                   label='Mean', alpha=0.9, zorder=10)
            ax.plot(df.index, median_vals.values, 'g-', linewidth=2.5, 
                   label='Median', alpha=0.9, zorder=10)
            
            ax.legend(loc='upper right', fontsize=12, framealpha=0.9)
        else:
            ax.text(0.5, 0.5, 'No data in date range', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=14)
        
        # Set y-axis limits
        ylim_pws = parse_ylim(ylim, 'pws')
        if ylim_pws:
            ax.set_ylim(ylim_pws)
        
        # Format
        n_stations = len(df.columns)
        shown = min(n_stations, max_stations) if (mode == 'raw' and max_stations) else n_stations
        param_label = parameter.replace('_', ' ').title()
        
        if mode == 'overlay':
            title = f"PWS - {param_label}{unit_str} ({n_stations} stations)"
        else:
            title = f"PWS - {param_label}{unit_str} "
            title += f"({shown}/{n_stations} stations)" if (mode == 'raw' and max_stations and shown < n_stations) else f"({n_stations} stations)"
        
        ax.set_title(title, fontsize=15, fontweight='bold')
        ax.set_ylabel(f"{param_label}{unit_str}", fontsize=13, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=12)
        
        plot_idx += 1
    
    # Format x-axis
    axes[-1].set_xlabel('Time', fontsize=13, fontweight='bold')
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(axes[-1].xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # Title
    mode_names = {'raw': 'Individual Stations', 'stats': 'Statistics', 'overlay': 'Overlay'}
    mode_str = mode_names.get(mode, mode)
    resample_str = f' (resampled: {resample})' if resample else ''
    outlier_str = f' [outliers: {outlier_method}]' if outlier_method != 'none' else ''
    plt.suptitle(f'{parameter.replace("_", " ").title()}{unit_str} - {mode_str}{resample_str}{outlier_str}',
                fontsize=17, fontweight='bold', y=0.995)
    
    plt.tight_layout()
    return fig, axes





def accumulation_plot(analysis_data,
                     date_range=None,
                     datasets='both',  # 'both', 'asos', 'pws'
                     stations=None,  # None = all, or list of station IDs
                     stats=False,  # If True, plot PWS mean and median
                     show_precip_grid=False,  # If True, add precip_type grid coloring
                     ylim_percentile=95,  # Percentile for y-limit (or 'max' for full range)
                     figsize=(16, 8)):
    """
    Plot cumulative rainfall accumulation from ASOS and/or PWS stations.
    
    Parameters
    ----------
    analysis_data : dict
        Dictionary with 'asos' and 'pws' containing DataFrames
    date_range : tuple, optional
        (start_date, end_date) to filter data
    datasets : str
        'both' (default), 'asos', or 'pws'
    stations : list or None
        List of station IDs to plot. If None, plots all available stations.
    stats : bool
        If True, plot PWS mean and median accumulation (in addition to individual stations)
    show_precip_grid : bool
        If True, add background grid coloring based on precip_type (best agreement from ASOS stations)
    ylim_percentile : int or str
        Percentile (0-100) for setting y-axis upper limit to avoid outliers.
        Use 'max' or 100 for the full range. Default is 95.
    figsize : tuple
        Figure size (width, height)
    
    Returns
    -------
    fig, ax : matplotlib figure and axis
    """
    # Define color_map for standardized precip types
    color_map = {
        'dry': 'lightgray',
        'rain': 'lightblue',
        'snow': 'cyan',
        'ice': 'orange',
        'mix': 'yellow'
    }
    
    # Filter by date range
    if date_range:
        start_date, end_date = date_range
    else:
        start_date = None
        end_date = None
    
    # Setup figure
    fig, ax = plt.subplots(figsize=figsize)
    
    # Track all max values for y-limit calculation
    all_max_values = []
    
    # Get ASOS data
    df_asos = None
    if datasets in ['both', 'asos'] and 'rainfall_amount' in analysis_data.get('asos', {}):
        df_asos = analysis_data['asos']['rainfall_amount'].copy()
        if date_range:
            df_asos = df_asos[(df_asos.index >= start_date) & (df_asos.index <= end_date)]
        
        # Filter by stations if specified
        if stations is not None:
            available_stations = [s for s in stations if s in df_asos.columns]
            if available_stations:
                df_asos = df_asos[available_stations]
            else:
                print(f"⚠ No ASOS stations found in list: {stations}")
                df_asos = None
    
    # Get PWS data
    df_pws = None
    if datasets in ['both', 'pws'] and 'rainfall_amount' in analysis_data.get('pws', {}):
        df_pws = analysis_data['pws']['rainfall_amount'].copy()
        if date_range:
            df_pws = df_pws[(df_pws.index >= start_date) & (df_pws.index <= end_date)]
        
        # Filter by stations if specified
        if stations is not None:
            available_stations = [s for s in stations if s in df_pws.columns]
            if available_stations:
                df_pws = df_pws[available_stations]
            else:
                print(f"⚠ No PWS stations found in list: {stations}")
                df_pws = None
    
    # Get precip_type for grid coloring (best agreement from ASOS stations)
    precip_periods = {}
    if show_precip_grid:
        if 'precip_type' in analysis_data.get('asos', {}):
            df_precip = analysis_data['asos']['precip_type'].copy()
            
            if date_range:
                df_precip = df_precip[(df_precip.index >= start_date) & (df_precip.index <= end_date)]
            
            # Filter by stations if specified
            if stations is not None:
                available_stations = [s for s in stations if s in df_precip.columns]
                if available_stations:
                    df_precip = df_precip[available_stations]
            
            if len(df_precip.columns) > 0:
                # Get best agreement: mode (most common value) across stations at each time
                def get_mode(row):
                    """Get mode (most common value) from row, ignoring NaN."""
                    valid_vals = row.dropna()
                    if len(valid_vals) == 0:
                        return np.nan
                    value_counts = valid_vals.value_counts()
                    if len(value_counts) > 0:
                        return value_counts.index[0]
                    return np.nan
                
                precip_series = df_precip.apply(get_mode, axis=1)
                
                # Resample to 1H to reduce number of spans
                precip_series = precip_series.resample('1H').first()
                
                # Group consecutive periods of same type (skip 'dry')
                for ptype in precip_series.unique():
                    if pd.notna(ptype) and ptype != 'dry' and ptype in color_map:
                        mask = precip_series == ptype
                        if mask.any():
                            periods = []
                            in_period = False
                            period_start = None
                            for t, val in zip(precip_series.index, mask):
                                if val and not in_period:
                                    period_start = t
                                    in_period = True
                                elif not val and in_period:
                                    periods.append((period_start, t))
                                    in_period = False
                            if in_period:
                                periods.append((period_start, precip_series.index[-1] + pd.Timedelta(hours=1)))
                            precip_periods[ptype] = periods
    
    # Color background by precip_type (draw BEFORE plotting lines so lines are on top)
    if precip_periods:
        for ptype, periods in precip_periods.items():
            color = color_map.get(ptype, 'lightgray')
            for i, (period_start, period_end) in enumerate(periods):
                # Only add label for first span of each type
                ax.axvspan(period_start, period_end, alpha=0.3, color=color, zorder=0, 
                          edgecolor='none', label=ptype.capitalize() if i == 0 else None)
    
    # Plot ASOS accumulation (strong colors)
    colors_asos = plt.cm.tab10(np.linspace(0, 1, 10))
    if df_asos is not None and len(df_asos.columns) > 0:
        for idx, col in enumerate(df_asos.columns):
            # Calculate cumulative sum
            cumsum = df_asos[col].fillna(0).cumsum()
            all_max_values.append(cumsum.max())
            ax.plot(cumsum.index, cumsum.values, 
                   color=colors_asos[idx % len(colors_asos)],
                   label=f'ASOS {col}',
                   linewidth=2.5, alpha=1.0, zorder=5)
    
    # Plot PWS accumulation
    # Default color for PWS when plotting all stations without specific selection
    pws_default_color = 'steelblue'
    colors_pws = plt.cm.Pastel1(np.linspace(0, 1, 9))  # Lighter colors for individual stations
    
    # Reduce intensity of individual PWS lines when showing stats
    pws_alpha = 0.25 if stats else 0.5
    pws_linewidth = 1.0 if stats else 1.5
    
    if df_pws is not None and len(df_pws.columns) > 0:
        # Use single legend entry when no specific stations were requested
        pws_single_legend = (stations is None)
        
        for idx, col in enumerate(df_pws.columns):
            # Calculate cumulative sum
            cumsum = df_pws[col].fillna(0).cumsum()
            all_max_values.append(cumsum.max())
            
            if pws_single_legend:
                # Use same color for all, only first gets a label
                ax.plot(cumsum.index, cumsum.values,
                       color=pws_default_color,
                       label='PWS stations' if idx == 0 else None,
                       linewidth=pws_linewidth, alpha=pws_alpha, zorder=4)
            else:
                # Individual colors and labels when specific stations requested
                ax.plot(cumsum.index, cumsum.values,
                       color=colors_pws[idx % len(colors_pws)],
                       label=f'PWS {col}',
                       linewidth=pws_linewidth, alpha=pws_alpha, zorder=4)
        
        # Plot PWS mean and median if stats=True
        if stats:
            # Calculate cumulative sum for mean and median
            pws_mean = df_pws.mean(axis=1).fillna(0).cumsum()
            pws_median = df_pws.median(axis=1).fillna(0).cumsum()
            
            all_max_values.append(pws_mean.max())
            all_max_values.append(pws_median.max())
            
            ax.plot(pws_mean.index, pws_mean.values,
                   color='blue', linestyle='--', linewidth=2.5,
                   label='PWS Mean', alpha=0.8, zorder=6)
            ax.plot(pws_median.index, pws_median.values,
                   color='green', linestyle='--', linewidth=2.5,
                   label='PWS Median', alpha=0.8, zorder=6)
    
    # Set y-limit based on percentile to avoid outliers
    if all_max_values:
        all_max_values = [v for v in all_max_values if pd.notna(v) and v > 0]
        if all_max_values:
            if ylim_percentile == 'max' or ylim_percentile >= 100:
                y_upper = max(all_max_values)
            else:
                # Use percentile of max values
                y_upper = np.percentile(all_max_values, ylim_percentile)
                # Ensure we show at least the second-highest if percentile is too low
                if len(all_max_values) > 1:
                    sorted_maxes = sorted(all_max_values)
                    second_max = sorted_maxes[-2]
                    # Use whichever is higher: percentile or second-max
                    y_upper = max(y_upper, second_max)
            
            # Add 5% padding
            y_upper *= 1.05
            ax.set_ylim(0, y_upper)
    
    # Formatting
    ax.set_xlabel('Time', fontsize=14, fontweight='bold')
    ax.set_ylabel('Cumulative Rainfall (mm)', fontsize=14, fontweight='bold')
    ax.set_title('Rainfall Accumulation', fontsize=16, fontweight='bold')
    ax.grid(True, alpha=0.3, zorder=1)
    ax.tick_params(labelsize=12)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # Legend on the right side outside
    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=10, framealpha=0.9)
    
    plt.tight_layout()
    return fig, ax