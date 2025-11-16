"""
NOAA ASOS Plotting Functions
=============================

Visualization functions for ASOS weather data.

Author: OpenMesh Project  
Date: 2025-11-16
"""

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from pathlib import Path


def plot_precipitation_timeseries(processed_data, stations_config, start_date, end_date,
                                  resolution='5min', output_path=None, show=True):
    """Plot precipitation rate time series"""
    fig, ax = plt.subplots(figsize=(16, 6))
    
    for station_id, df in processed_data.items():
        if 'precip_mm' in df.columns:
            df_plot = df[df['precip_mm'].notna()].copy()
            
            ax.plot(df_plot['datetime'], df_plot['precip_mm'],
                    label=f"{station_id} - {stations_config[station_id]['name']}",
                    linewidth=1.5, alpha=0.8,
                    color=stations_config[station_id]['color'],
                    linestyle=stations_config[station_id]['linestyle'])
    
    ax.set_xlabel('Date (UTC)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Precipitation (mm)', fontsize=12, fontweight='bold')
    ax.set_title(f'Precipitation Rate - {resolution}\\n{start_date.date()} to {end_date.date()}',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✓ Saved: {Path(output_path).name}")
    
    if show:
        plt.show()
    else:
        plt.close()


def plot_accumulated_rainfall(accumulated_data, stations_config, start_date, end_date,
                              resolution='5min', output_path=None, show=True):
    """Plot cumulative precipitation"""
    fig, ax = plt.subplots(figsize=(16, 7))
    
    for station_id, df_accum in accumulated_data.items():
        ax.plot(df_accum['datetime'], df_accum['accumulated_mm'],
                label=f"{station_id} - {stations_config[station_id]['name']}",
                linewidth=2.5, alpha=0.85,
                color=stations_config[station_id]['color'],
                linestyle=stations_config[station_id]['linestyle'])
        
        # Add final value
        final_value = df_accum['accumulated_mm'].iloc[-1]
        final_time = df_accum['datetime'].iloc[-1]
        ax.annotate(f'{final_value:.1f} mm', 
                    xy=(final_time, final_value),
                    xytext=(10, 0), textcoords='offset points',
                    fontsize=11, fontweight='bold',
                    color=stations_config[station_id]['color'])
    
    ax.set_xlabel('Date (UTC)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Accumulated Precipitation (mm)', fontsize=12, fontweight='bold')
    ax.set_title(f'Cumulative Precipitation - {resolution}\\n{start_date.date()} to {end_date.date()}',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✓ Saved: {Path(output_path).name}")
    
    if show:
        plt.show()
    else:
        plt.close()


def plot_variable(processed_data, stations_config, variable, ylabel, title,
                 start_date, end_date, resolution='5min', ylim_bottom=None,
                 output_path=None, show=True):
    """Generic plot for any variable"""
    fig, ax = plt.subplots(figsize=(16, 6))
    
    for station_id, df in processed_data.items():
        if variable in df.columns:
            df_plot = df[df[variable].notna()].copy()
            
            ax.plot(df_plot['datetime'], df_plot[variable],
                    label=f"{station_id} - {stations_config[station_id]['name']}",
                    linewidth=1.5, alpha=0.8,
                    color=stations_config[station_id]['color'],
                    linestyle=stations_config[station_id]['linestyle'])
    
    ax.set_xlabel('Date (UTC)', fontsize=12, fontweight='bold')
    ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')
    ax.set_title(f'{title} - {resolution}\\n{start_date.date()} to {end_date.date()}',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)
    
    if ylim_bottom is not None:
        ax.set_ylim(bottom=ylim_bottom)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✓ Saved: {Path(output_path).name}")
    
    if show:
        plt.show()
    else:
        plt.close()
