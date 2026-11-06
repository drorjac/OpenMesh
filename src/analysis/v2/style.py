"""Plot style and colours shared by the notebooks."""
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
BANDS = ["V60", "K24", "C5"]
# Colours: 5 GHz blue, 24 GHz green, the V band orange to red (higher is redder).
# For maps and link features the V band is split at 63 GHz into its lower (58-63 GHz) and upper (64-70 GHz) half.
SPLIT = ["V60 upper", "V60 lower", "K24", "C5"]
SPLIT_COLOR = {"V60 upper": "#d62728", "V60 lower": "#ff7f0e", "K24": "#2ca02c", "C5": "#1f77b4"}
SPLIT_LABEL = {"V60 upper": "V60 upper (64–70 GHz)", "V60 lower": "V60 lower (58–63 GHz)", "K24": "K24 (24 GHz)",
               "C5": "C5 (5–6 GHz)"}
BAND_COLOR = {"V60": SPLIT_COLOR["V60 upper"], "K24": SPLIT_COLOR["K24"], "C5": SPLIT_COLOR["C5"]}


def style():
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 110, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titlesize": 11,
        "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.labelsize": 9,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.6, "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "legend.frameon": False, "legend.fontsize": 8, "lines.linewidth": 2, "font.size": 9,
        "axes.prop_cycle": mpl.cycler(color=SLOT),
    })
