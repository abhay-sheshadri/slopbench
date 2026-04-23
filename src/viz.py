from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

# Set global font settings for better aesthetics
plt.rcParams["font.size"] = 11
plt.rcParams["axes.labelsize"] = 12
plt.rcParams["axes.titlesize"] = 14
plt.rcParams["xtick.labelsize"] = 10
plt.rcParams["ytick.labelsize"] = 10
plt.rcParams["legend.fontsize"] = 10

# =============================================================================
# Anthropic Brand Colors (from go/brand)
# =============================================================================

# Primary Brand Colors
ANTHRO_SLATE = "#141413"
ANTHRO_IVORY = "#FAF9F5"
ANTHRO_CLAY = "#C0392B"

# Secondary Brand Colors
ANTHRO_OAT = "#E3DACC"
ANTHRO_CORAL = "#EBCECE"
ANTHRO_FIG = "#C46686"
ANTHRO_SKY = "#6A9BCC"
ANTHRO_OLIVE = "#788C5D"
ANTHRO_HEATHER = "#CBCADB"
ANTHRO_CACTUS = "#BCD1CA"

# Grayscale System
ANTHRO_GRAY_700 = "#3D3D3A"
ANTHRO_GRAY_600 = "#5E5D59"
ANTHRO_GRAY_550 = "#73726C"
ANTHRO_GRAY_500 = "#87867F"
ANTHRO_GRAY_400 = "#B0AEA5"
ANTHRO_GRAY_300 = "#D1CFC5"
ANTHRO_GRAY_200 = "#E8E6DC"

# Tertiary Colors - Reds
ANTHRO_RED_700 = "#8A2424"
ANTHRO_RED_600 = "#B53333"
ANTHRO_RED_500 = "#E04343"
ANTHRO_RED_400 = "#E86B6B"
ANTHRO_RED_300 = "#F09595"
ANTHRO_RED_200 = "#F7C1C1"

# Tertiary Colors - Oranges
ANTHRO_ORANGE_700 = "#8C3619"
ANTHRO_ORANGE_600 = "#BA4C27"
ANTHRO_ORANGE_500 = "#E86235"
ANTHRO_ORANGE_400 = "#ED8461"

# Tertiary Colors - Blues
ANTHRO_BLUE_700 = "#0F4B87"
ANTHRO_BLUE_600 = "#1B67B2"
ANTHRO_BLUE_500 = "#2C84DB"
ANTHRO_BLUE_400 = "#599EE3"
ANTHRO_BLUE_300 = "#86B8EB"
ANTHRO_BLUE_200 = "#BAD7F5"

# Tertiary Colors - Greens
ANTHRO_GREEN_700 = "#386910"
ANTHRO_GREEN_600 = "#568C1C"
ANTHRO_GREEN_500 = "#76AD2A"

# Tertiary Colors - Violets
ANTHRO_VIOLET_700 = "#383182"
ANTHRO_VIOLET_600 = "#4D44AB"
ANTHRO_VIOLET_500 = "#6258D1"
ANTHRO_VIOLET_400 = "#827ADE"

# Tertiary Colors - Aquas
ANTHRO_AQUA_700 = "#0E6B54"
ANTHRO_AQUA_600 = "#188F6B"
ANTHRO_AQUA_500 = "#24B283"

# Custom Colors - True Cyan
CYAN_500 = "#00BCD4"

# Tertiary Colors - Yellows
ANTHRO_YELLOW_600 = "#C77F1A"
ANTHRO_YELLOW_500 = "#FAA72A"

# Tertiary Colors - Magentas
ANTHRO_MAGENTA_600 = "#B54369"
ANTHRO_MAGENTA_500 = "#E05A87"

# Common plot accent colors
SALMON = "#E8927C"
PURPLE = "#9B72CF"


# =============================================================================
# Utilities
# =============================================================================


# Pre-computed bar statistic: (mean, ci_lo, ci_hi).
# Plotting functions expect this — all statistics should be computed by callers.
BarStat = Tuple[float, float, float]


def _style_ax(ax, ylim=None, grid=True):
    """Apply standard axis styling: remove top/right spines, add grid."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if grid:
        ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    if ylim:
        ax.set_ylim(ylim)


def _save_fig(fig, save_path, dpi=300):
    """Save figure with standard settings."""
    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight", facecolor="white")


def _apply_row_labels(
    fig,
    row_labels: Optional[List[str]] = None,
    row_colors: Optional[List[str]] = None,
    row_ylabel: Optional[str] = None,
    remove_legends: bool = True,
    keep_first_legend: bool = False,
    remove_split_labels: bool = True,
    label_offset: int = -60,
    ylabel_offset: int = -38,
):
    """Apply row labels, row colors, and cleanup to a multi-row hierarchical bar chart.

    Args:
        fig: matplotlib Figure returned by plot_hierarchical_bars
        row_labels: Left-side labels for each row (e.g., ["Base Models", "Chat"])
        row_colors: If provided, recolor all bars in row i to row_colors[i].
        row_ylabel: Secondary ylabel text placed closer to axis (e.g., "Accuracy (%)")
        remove_legends: Remove legends from all axes
        keep_first_legend: If True, keep the legend on the first axis
        remove_split_labels: Remove the split labels below x-axis
        label_offset: Horizontal offset for row labels in points
        ylabel_offset: Horizontal offset for secondary ylabel in points
    """
    axes = fig.get_axes()
    for i, ax in enumerate(axes):
        if remove_legends and ax.get_legend():
            if not (keep_first_legend and i == 0):
                ax.get_legend().remove()
        if remove_split_labels:
            for txt in ax.texts[:]:
                if txt.get_position()[1] < 0:
                    txt.remove()
        if row_labels and i < len(row_labels):
            ax.set_ylabel("")
            ax.annotate(
                row_labels[i],
                xy=(0, 0.5),
                xycoords="axes fraction",
                xytext=(label_offset, 0),
                textcoords="offset points",
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                rotation=90,
            )
            if row_ylabel:
                ax.annotate(
                    row_ylabel,
                    xy=(0, 0.5),
                    xycoords="axes fraction",
                    xytext=(ylabel_offset, 0),
                    textcoords="offset points",
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="normal",
                    rotation=90,
                )
        if row_colors and i < len(row_colors):
            for patch in ax.patches:
                if patch is not None:
                    patch.set_facecolor(row_colors[i])
                    patch.set_alpha(0.85)


# =============================================================================
# Hierarchical bar chart
# =============================================================================


def _plot_single_row(
    ax,
    data: Dict[str, Dict[str, Dict[str, BarStat]]],
    splits: List[str],
    all_groups: List[str],
    all_categories: List[str],
    colors: List[str],
    bar_width: float,
    split_spacing: float,
    split_label_offset: float,
    rotate_xticks: Optional[float],
    show_values: bool,
    ylabel: str,
    ylim: Optional[Tuple[float, float]],
    show_legend: bool,
    legend_loc: str,
):
    """Helper function to plot a single row of the hierarchical bar chart."""
    num_categories = len(all_categories)

    # Calculate positions with spacing between splits
    x_positions = []
    x_labels = []
    current_x = 0
    split_positions = {}
    split_group_order = {}
    split_boundaries = []

    for split_idx, split in enumerate(splits):
        split_group_positions = []
        split_groups = [g for g in all_groups if g in data[split]]
        split_group_order[split] = split_groups

        for group in split_groups:
            x_positions.append(current_x)
            x_labels.append(group)
            split_group_positions.append(current_x)
            current_x += 1

        if split_group_positions:
            split_positions[split] = (
                min(split_group_positions),
                max(split_group_positions),
            )

        # Add spacing between splits
        if split_idx < len(splits) - 1:
            split_boundaries.append(current_x - 0.5 + split_spacing / 2)
            current_x += split_spacing

    x_positions = np.array(x_positions)

    # Plot bars
    for cat_idx, category in enumerate(all_categories):
        offset = (cat_idx - num_categories / 2 + 0.5) * bar_width
        means = []
        err_lo = []
        err_hi = []

        for split in splits:
            for group in split_group_order[split]:
                stat = data[split][group].get(category, (0.0, 0.0, 0.0))
                mean, ci_lo, ci_hi = stat
                means.append(mean)
                err_lo.append(mean - ci_lo)
                err_hi.append(ci_hi - mean)

        bars = ax.bar(
            x_positions + offset,
            means,
            bar_width,
            label=category if show_legend else None,
            color=colors[cat_idx % len(colors)],
            yerr=[err_lo, err_hi],
            capsize=4,
            error_kw={"linewidth": 1.5, "capthick": 1.5},
            alpha=0.85,
            zorder=3,
        )

        if show_values:
            n_cats = len(all_categories)
            val_fontsize = 9 if n_cats <= 1 else max(6, 10 - n_cats)
            for bar, mean, ehi in zip(bars, means, err_hi):
                y_pad = ehi + (ylim[1] - ylim[0]) * 0.01 if ylim else ehi + 0.01
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    bar.get_height() + y_pad,
                    f"{mean:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=val_fontsize,
                )

    # Add vertical separators between splits
    for boundary_x in split_boundaries:
        ax.axvline(
            x=boundary_x, color=ANTHRO_GRAY_400, linestyle="-", linewidth=1, zorder=2
        )

    # Add split labels
    for split, (start_pos, end_pos) in split_positions.items():
        split_center = (start_pos + end_pos) / 2
        ax.text(
            split_center,
            split_label_offset,
            split,
            ha="center",
            va="top",
            fontsize=11,
            fontweight="bold",
            transform=ax.get_xaxis_transform(),
        )

    # Styling
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xticks(x_positions)

    if rotate_xticks is not None:
        ax.set_xticklabels(x_labels, rotation=rotate_xticks, ha="right")
    else:
        ax.set_xticklabels(x_labels)

    _style_ax(ax, ylim=ylim)


def plot_hierarchical_bars(
    data: Dict[str, Dict[str, Dict[str, BarStat]]],
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    colors: Optional[List[str]] = None,
    figsize: Tuple[int, int] = (10, 5),
    bar_width: float = 0.35,
    ylim: Optional[Tuple[float, float]] = (0, 10.5),
    save_path: Optional[str] = None,
    legend_loc: str = "upper right",
    category_order: Optional[List[str]] = None,
    group_order: Optional[List[str]] = None,
    rotate_xticks: Optional[float] = 15,
    show_values: bool = True,
    split_spacing: float = 0.8,
    split_label_offset: float = -0.2,
    splits_per_row: Optional[int] = None,
    n_cols: int = 1,
    row_labels: Optional[List[str]] = None,
    row_colors: Optional[List[str]] = None,
    row_ylabel: Optional[str] = None,
    hlines: Optional[List[Dict]] = None,
    keep_first_legend: bool = False,
):
    """
    Create a grouped bar chart with error bars.

    Args:
        data: Three-level dict: ``{split: {group: {category: (mean, ci_lo, ci_hi)}}}``.
              Each leaf is a ``BarStat`` tuple of pre-computed statistics.
              Use ``bootstrap_ci`` from ``src.utils`` to compute these.
        title: Chart title
        xlabel: X-axis label
        ylabel: Y-axis label
        colors: Optional list of colors for categories
        figsize: Figure size (width, height) - height is per row if splits_per_row is set
        bar_width: Width of individual bars
        ylim: Optional y-axis limits (min, max)
        save_path: Optional path to save figure
        legend_loc: Location of legend
        category_order: Explicit order for categories (legend/bars)
        group_order: Explicit order for groups (x-axis)
        rotate_xticks: Optional rotation angle for x-axis labels
        show_values: Whether to show value labels on bars
        split_spacing: Spacing between splits
        split_label_offset: Vertical offset for split labels
        splits_per_row: If set, splits data across multiple rows with this many splits per row
        row_labels: Left-side labels for each row (replaces ylabel, removes split labels)
        row_colors: Recolor bars in each row
        row_ylabel: Secondary ylabel text next to row labels (e.g., "Accuracy (%)")
        hlines: List of dicts for horizontal reference lines on all axes.
                Each dict: {"y": value, "color": ..., "linestyle": ..., "linewidth": ..., "alpha": ...}
        keep_first_legend: If True, keep the legend on the first axis when row_labels removes others
    """
    if colors is None:
        colors = [
            ANTHRO_BLUE_500,
            ANTHRO_RED_500,
            ANTHRO_GREEN_500,
            ANTHRO_YELLOW_500,
            ANTHRO_VIOLET_500,
            ANTHRO_AQUA_500,
        ]

    # Extract structure
    splits = list(data.keys())
    all_groups = []
    all_categories = set()

    for split_data in data.values():
        for group, categories in split_data.items():
            if group not in all_groups:
                all_groups.append(group)
            all_categories.update(categories.keys())

    # Apply ordering
    if category_order is not None:
        ordered = [c for c in category_order if c in all_categories]
        remaining = [c for c in all_categories if c not in category_order]
        all_categories = ordered + remaining
    else:
        all_categories = sorted(list(all_categories))

    if group_order is not None:
        all_groups = [g for g in group_order if g in all_groups]

    # Determine number of rows
    if splits_per_row is None or len(splits) <= splits_per_row:
        n_rows = 1
        split_chunks = [splits]
    else:
        n_rows = (len(splits) + splits_per_row - 1) // splits_per_row
        split_chunks = [
            splits[i : i + splits_per_row]
            for i in range(0, len(splits), splits_per_row)
        ]

    # Create figure
    n_grid_rows = (n_rows + n_cols - 1) // n_cols
    fig_height = figsize[1] * n_grid_rows
    fig, axes = plt.subplots(
        n_grid_rows,
        n_cols,
        figsize=(figsize[0] * n_cols, fig_height),
        dpi=150,
        squeeze=False,
    )
    fig.patch.set_facecolor("white")

    # Plot each row
    for row_idx, row_splits in enumerate(split_chunks):
        grid_row, grid_col = divmod(row_idx, n_cols)
        ax = axes[grid_row, grid_col]
        _plot_single_row(
            ax=ax,
            data=data,
            splits=row_splits,
            all_groups=all_groups,
            all_categories=list(all_categories),
            colors=colors,
            bar_width=bar_width,
            split_spacing=split_spacing,
            split_label_offset=split_label_offset,
            rotate_xticks=rotate_xticks,
            show_values=show_values,
            ylabel=ylabel,
            ylim=ylim,
            show_legend=(row_idx == 0),  # Only show legend on first row
            legend_loc=legend_loc,
        )

    # Hide unused axes in the last row
    for unused in range(n_rows, n_grid_rows * n_cols):
        grid_row, grid_col = divmod(unused, n_cols)
        axes[grid_row, grid_col].set_visible(False)

    # Add title to figure
    if title:
        fig.suptitle(title, fontsize=14, fontweight="bold", color="#1a1a1a", y=1.02)

    plt.tight_layout()

    # Place legend below the plot (skip if only one entry)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    if len(handles) > 1:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.02),
            ncol=min(len(handles), 5),
            frameon=True,
            fontsize=10,
        )

    # Apply horizontal reference lines
    if hlines:
        for ax_obj in fig.get_axes():
            for hl in hlines:
                ax_obj.axhline(
                    y=hl["y"],
                    color=hl.get("color", "red"),
                    linestyle=hl.get("linestyle", "--"),
                    linewidth=hl.get("linewidth", 1.5),
                    alpha=hl.get("alpha", 0.5),
                    zorder=2,
                )

    # Apply row labels and row colors if provided
    if row_labels or row_colors:
        _apply_row_labels(
            fig,
            row_labels=row_labels,
            row_colors=row_colors,
            row_ylabel=row_ylabel,
            remove_legends=row_labels is not None,
            keep_first_legend=keep_first_legend,
            remove_split_labels=row_labels is not None,
        )

    _save_fig(fig, save_path)

    return fig


# =============================================================================
# Scatter plot with trend line
# =============================================================================


def plot_scatter_with_trend(
    x: np.ndarray,
    y: np.ndarray,
    groups: Optional[Dict[str, np.ndarray]] = None,
    group_colors: Optional[Dict[str, str]] = None,
    xlabel: str = "",
    ylabel: str = "",
    title: str = "",
    reference_lines: Optional[List[Dict]] = None,
    jitter: Tuple[float, float] = (0.0, 0.0),
    alpha: float = 0.25,
    point_size: int = 18,
    trend_color: str = ANTHRO_CLAY,
    figsize: Tuple[float, float] = (6, 5),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """Scatter plot with OLS trend line and optional group coloring.

    Args:
        x, y: Data arrays (same length).
        groups: Optional dict {label: boolean_mask} for coloring subsets.
        group_colors: Dict {label: color_hex} for each group.
        reference_lines: List of dicts with keys "x" (value), "color", "label",
                         "linestyle" (default ":") for vertical reference lines.
        jitter: (jitter_x_std, jitter_y_std) for adding random noise.
        ax: If provided, plot on this axes instead of creating a new figure.
    """
    from scipy import stats as sp_stats

    own_fig = ax is None
    if own_fig:
        fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=150)
        fig.patch.set_facecolor("white")
    else:
        fig = ax.get_figure()

    rng = np.random.default_rng(42)
    jx = rng.normal(0, jitter[0], len(x)) if jitter[0] else 0
    jy = rng.normal(0, jitter[1], len(y)) if jitter[1] else 0

    # Plot groups or all points
    if groups and group_colors:
        for label, mask in groups.items():
            color = group_colors.get(label, ANTHRO_BLUE_500)
            ax.scatter(
                x[mask] + (jx[mask] if isinstance(jx, np.ndarray) else 0),
                y[mask] + (jy[mask] if isinstance(jy, np.ndarray) else 0),
                alpha=alpha,
                s=point_size,
                color=color,
                edgecolors="none",
                label=f"{label} (n={mask.sum()})",
            )
    else:
        ax.scatter(
            x + jx,
            y + jy,
            alpha=alpha,
            s=point_size,
            color=ANTHRO_BLUE_500,
            edgecolors="none",
            label=f"n={len(x)}",
        )

    # OLS trend line
    slope, intercept, r_value, _, _ = sp_stats.linregress(x, y)
    x_line = np.linspace(x.min(), x.max(), 100)
    ax.plot(
        x_line,
        slope * x_line + intercept,
        color=trend_color,
        linewidth=2.5,
        linestyle="--",
        label=f"OLS (r={r_value:.2f})",
    )

    # Spearman for title
    rho, rho_p = sp_stats.spearmanr(x, y)

    # Reference lines
    if reference_lines:
        for ref in reference_lines:
            ax.axvline(
                ref["x"],
                color=ref.get("color", ANTHRO_GRAY_500),
                linewidth=1.5,
                linestyle=ref.get("linestyle", ":"),
                alpha=0.8,
                label=ref.get("label", ""),
            )

    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    full_title = title or "Scatter"
    ax.set_title(
        f"{full_title}\nSpearman {chr(961)}={rho:.3f} (p={rho_p:.3f})",
        fontsize=11,
        color=ANTHRO_CLAY,
    )
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) > 1:
        ax.legend(
            fontsize=8,
            frameon=True,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.08),
            ncol=min(len(handles), 5),
        )
    _style_ax(ax)

    if own_fig:
        plt.tight_layout()
        _save_fig(fig, save_path)
    return fig


# =============================================================================
# Binned bar chart (percentile bins)
# =============================================================================


def plot_binned_bars(
    x: np.ndarray,
    y: np.ndarray,
    percentiles: List[float] = [0, 15, 35, 55, 75, 90, 100],
    xlabel: str = "",
    ylabel: str = "",
    title: str = "",
    gradient_colors: Tuple[str, str] = (ANTHRO_BLUE_200, ANTHRO_BLUE_700),
    figsize: Tuple[float, float] = (6, 5),
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """Bar chart with percentile-based bins showing mean y per bin of x.

    Args:
        x, y: Data arrays (same length).
        percentiles: Percentile edges for binning x values.
        gradient_colors: (light, dark) hex colors for gradient from low to high bins.
    """
    own_fig = ax is None
    if own_fig:
        fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=150)
        fig.patch.set_facecolor("white")
    else:
        fig = ax.get_figure()

    bin_edges = np.percentile(x, percentiles)
    bin_edges = sorted(set(bin_edges))
    if len(bin_edges) < 3:
        bin_edges = np.linspace(x.min() - 0.01, x.max() + 0.01, 8)

    bin_labels, bin_means, bin_cis, bin_counts = [], [], [], []

    for i in range(len(bin_edges) - 1):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (x >= lo) & (x <= hi) if i == 0 else (x > lo) & (x <= hi)
        if mask.sum() < 3:
            continue
        vals = y[mask]
        arr_vals = vals.astype(float)
        mean = float(np.mean(arr_vals))
        std_err = float(np.std(arr_vals, ddof=1) / np.sqrt(len(arr_vals)))
        ci = 1.96 * std_err
        bin_labels.append(f"{lo:.2f}\u2013{hi:.2f}")
        bin_means.append(mean)
        bin_cis.append(ci)
        bin_counts.append(int(mask.sum()))

    x_pos = np.arange(len(bin_labels))
    n = len(bin_labels)
    cmap = LinearSegmentedColormap.from_list("", list(gradient_colors))
    bar_colors = [cmap(i / max(n - 1, 1)) for i in range(n)]

    bars = ax.bar(
        x_pos,
        bin_means,
        yerr=bin_cis,
        capsize=4,
        width=0.7,
        color=bar_colors,
        alpha=0.9,
        error_kw={"linewidth": 1.5, "capthick": 1.5, "color": ANTHRO_SLATE},
    )

    for i, (bar, count) in enumerate(zip(bars, bin_counts)):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + bin_cis[i] + 0.008,
            f"n={count}",
            ha="center",
            va="bottom",
            fontsize=8,
            color=ANTHRO_GRAY_400,
        )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(bin_labels, rotation=25, ha="right", fontsize=9)
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    if title:
        ax.set_title(title, fontsize=11, color=ANTHRO_CLAY)
    _style_ax(ax)

    if own_fig:
        plt.tight_layout()
        _save_fig(fig, save_path)
    return fig


# =============================================================================
# Line series
# =============================================================================

# Default line series palette — visually distinct brand colors
LINE_COLORS = [
    ANTHRO_BLUE_500,
    ANTHRO_RED_500,
    ANTHRO_GREEN_600,
    ANTHRO_VIOLET_500,
    ANTHRO_YELLOW_500,
    ANTHRO_AQUA_500,
    ANTHRO_ORANGE_500,
    ANTHRO_FIG,
]

LINE_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "h"]


def plot_line_series(
    panels: List[Dict],
    series_labels: List[str],
    title: str = "",
    colors: Optional[List[str]] = None,
    markers: Optional[List[str]] = None,
    figsize: Tuple[int, int] = (14, 5.5),
    ylim: Optional[Tuple[float, float]] = None,
    legend_loc: str = "best",
    dodge: float = 0.0,
    save_path: Optional[str] = None,
):
    """Plot multiple line series across one or more side-by-side panels.

    Args:
        panels: List of panel dicts, each with:
            - "title": str — panel title
            - "xlabel": str — x-axis label
            - "ylabel": str — y-axis label
            - "series": list of dicts, one per series (same order as series_labels):
                - "x": list of x values
                - "y": list of y values
        series_labels: Display labels for the legend (one per series).
        title: Overall figure suptitle.
        colors: Optional color list (one per series). Defaults to brand palette.
        markers: Optional marker list (one per series). Defaults to built-in set.
        figsize: Figure (width, height).
        ylim: Optional (min, max) for the y-axis on all panels.
        legend_loc: Matplotlib legend location string.
        dodge: Horizontal offset between overlapping series (in x-axis
            data units). Each series is shifted by
            ``(i - (n-1)/2) * dodge`` so they fan out symmetrically.
            Set to 0 for no dodging.
        save_path: If given, save the figure to this path.

    Returns:
        The matplotlib Figure.
    """
    if colors is None:
        colors = LINE_COLORS
    if markers is None:
        markers = LINE_MARKERS

    n_panels = len(panels)
    n_series = len(series_labels)

    fig, axes = plt.subplots(1, n_panels, figsize=figsize, dpi=150, squeeze=False)
    fig.patch.set_facecolor("white")

    for panel_idx, panel in enumerate(panels):
        ax = axes[0, panel_idx]

        for s_idx, (s_data, label) in enumerate(zip(panel["series"], series_labels)):
            x_raw = np.array(s_data["x"], dtype=float)
            y = s_data["y"]

            # Apply dodge: shift each series symmetrically around 0
            offset = (s_idx - (n_series - 1) / 2) * dodge
            x = x_raw + offset

            ax.plot(
                x,
                y,
                label=label,
                color=colors[s_idx % len(colors)],
                marker=markers[s_idx % len(markers)],
                markersize=7,
                linewidth=2.2,
                zorder=3,
            )

        ax.set_title(panel.get("title", ""), fontsize=13, fontweight="bold")
        ax.set_xlabel(panel.get("xlabel", ""), fontsize=11)
        ax.set_ylabel(panel.get("ylabel", ""), fontsize=11)
        if ylim is not None:
            ax.set_ylim(ylim)
        # Use the raw (un-dodged) x ticks
        raw_x = panel["series"][0]["x"]
        ax.set_xticks(raw_x)
        ax.set_xticklabels([str(v) for v in raw_x])
        _style_ax(ax)

    # Legend below the plot (skip if only one entry)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    if len(handles) > 1:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.02),
            ncol=min(len(handles), 5),
            frameon=True,
            fontsize=10,
        )

    if title:
        fig.suptitle(title, fontsize=15, fontweight="bold", color="#1a1a1a", y=1.01)

    plt.tight_layout()
    _save_fig(fig, save_path)

    return fig


# =============================================================================
# Confusion heatmaps
# =============================================================================


def plot_confusion_heatmaps(
    matrices: List[Dict],
    title: str = "",
    figsize: Tuple[int, int] = (6, 5),
    cmap: str = "Blues",
    vmin: float = 0.0,
    vmax: float = 1.0,
    vertical: bool = False,
    save_path: Optional[str] = None,
):
    """Plot one or more confusion matrices as heatmaps.

    Parameters
    ----------
    matrices : list of dict
        Each dict must contain:
        - "title": str — subplot title
        - "labels": list[str] — class labels (rows = true, cols = predicted)
        - "matrix": 2-D array-like — confusion counts or probabilities
        - "normalize": bool — if True, row-normalize before plotting
    title : str
        Figure suptitle.
    figsize : tuple
        Per-panel figure size (width, height).
    cmap : str
        Matplotlib colormap name.
    vmin, vmax : float
        Color scale bounds.
    vertical : bool
        If True, stack panels vertically instead of horizontally.
    save_path : str or None
        If given, save the figure to this path.
    """
    import numpy as np

    n = len(matrices)
    if vertical:
        nrows, ncols = n, 1
        total_w, total_h = figsize[0], figsize[1] * n
    else:
        nrows, ncols = 1, n
        total_w, total_h = figsize[0] * n, figsize[1]

    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(total_w, total_h),
        squeeze=False,
        facecolor="white",
        constrained_layout=True,
    )
    axes_flat = axes[:, 0] if vertical else axes[0]

    for ax, panel in zip(axes_flat, matrices):
        mat = np.array(panel["matrix"], dtype=float)
        labels = panel["labels"]
        if panel.get("normalize", False):
            row_sums = mat.sum(axis=1, keepdims=True)
            row_sums[row_sums == 0] = 1
            mat = mat / row_sums

        im = ax.imshow(mat, cmap=cmap, vmin=vmin, vmax=vmax, aspect="equal")
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax.set_yticklabels(labels, fontsize=7)
        ax.set_xlabel("Predicted", fontsize=9)
        ax.set_ylabel("True", fontsize=9)
        ax.set_title(panel["title"], fontsize=10, fontweight="bold", pad=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # Shared colorbar
    cbar = fig.colorbar(im, ax=axes_flat.tolist(), fraction=0.02, pad=0.04)
    cbar.ax.tick_params(labelsize=8)

    if title:
        # Center title over the heatmap axes, not the full figure (colorbar shifts it)
        ax0 = axes_flat[0]
        bbox = ax0.get_position()
        title_x = (bbox.x0 + bbox.x1) / 2
        fig.suptitle(
            title,
            fontsize=14,
            fontweight="bold",
            color="#1a1a1a",
            x=title_x,
            ha="center",
        )

    _save_fig(fig, save_path)

    return fig


# =============================================================================
# Scaling curves (e.g. best-of-N)
# =============================================================================


def plot_scaling_curves(
    scaling_by_series: Dict[str, Dict[int, Dict[str, float]]],
    panels: List[Dict[str, str]],
    reference_lines: Optional[Dict[str, List[Dict]]] = None,
    title: str = "",
    figsize: Optional[Tuple[float, float]] = None,
    colors: Optional[Dict[str, str]] = None,
    labels: Optional[Dict[str, str]] = None,
    log_x: bool = True,
    legend_loc: str = "best",
    dodge: float = 0.0,
    save_path: Optional[str] = None,
):
    """Plot scaling curves across one or more metric panels.

    Args:
        scaling_by_series: {series_name: {n: {metric: val, metric_ci: (lo, hi), ...}}}
        panels: List of panel specs, each with keys:
            - "metric": key in the scaling dicts
            - "ylabel": y-axis label
            - "ci_key": optional key for (lo, hi) CI tuples
        reference_lines: {metric: [{label, value, color?, linestyle?}, ...]}
        title: Overall figure title.
        colors: {series_name: color} override.
        labels: {series_name: display_label} override.
        log_x: Use log2 x-axis.
        legend_loc: Legend location string.
        save_path: Path to save figure.
    """
    n_panels = len(panels)
    if figsize is None:
        figsize = (7 * n_panels, 5.5)

    series_colors = colors or {}
    series_labels = labels or {}
    default_colors = LINE_COLORS
    markers = LINE_MARKERS
    refs = reference_lines or {}

    fig, axes = plt.subplots(1, n_panels, figsize=figsize, dpi=150, squeeze=False)
    fig.patch.set_facecolor("white")

    for panel_idx, panel in enumerate(panels):
        ax = axes[0, panel_idx]
        metric = panel["metric"]
        ci_key = panel.get("ci_key")

        # Reference lines (behind curves)
        for ref in refs.get(metric, []):
            ax.axhline(
                ref["value"],
                color=ref.get("color", ANTHRO_GRAY_500),
                linestyle=ref.get("linestyle", "--"),
                linewidth=1.5,
                alpha=0.6,
                label=ref["label"],
                zorder=1,
            )

        # Scaling curves
        all_ns: set = set()
        n_series = len(scaling_by_series)
        for s_idx, (series_name, scaling) in enumerate(scaling_by_series.items()):
            ns = sorted(scaling.keys())
            all_ns.update(ns)
            vals = [scaling[n][metric] for n in ns]
            color = series_colors.get(
                series_name, default_colors[s_idx % len(default_colors)]
            )
            label = series_labels.get(series_name, series_name)
            marker = markers[s_idx % len(markers)]

            # Apply dodge: shift each series symmetrically
            offset = (s_idx - (n_series - 1) / 2) * dodge
            ns_dodged = (
                [n * (2**offset) for n in ns]
                if log_x and dodge
                else [n + offset for n in ns]
            )

            yerr = None
            if ci_key:
                lo = [scaling[n].get(ci_key, (v, v))[0] for n, v in zip(ns, vals)]
                hi = [scaling[n].get(ci_key, (v, v))[1] for n, v in zip(ns, vals)]
                if any(l != h for l, h in zip(lo, hi)):
                    yerr = [
                        [v - l for v, l in zip(vals, lo)],
                        [h - v for v, h in zip(vals, hi)],
                    ]

            # Plot line + markers first, then error bars separately with lower alpha
            ax.plot(
                ns_dodged,
                vals,
                color=color,
                marker=marker,
                linewidth=2.2,
                markersize=7,
                label=label,
                zorder=4,
            )
            if yerr is not None:
                ax.errorbar(
                    ns_dodged,
                    vals,
                    yerr=yerr,
                    fmt="none",
                    ecolor=color,
                    capsize=4,
                    capthick=1.5,
                    elinewidth=1.5,
                    alpha=0.4,
                    zorder=3,
                )

        ax.set_title(panel.get("title", ""), fontsize=13, fontweight="bold")
        ax.set_xlabel(panel.get("xlabel", "N (samples)"), fontsize=11)
        ax.set_ylabel(panel["ylabel"], fontsize=11)
        if log_x:
            ax.set_xscale("log", base=2)
        ns_sorted = sorted(all_ns)
        ax.set_xticks(ns_sorted)
        ax.set_xticklabels([str(n) for n in ns_sorted])
        if "ylim" in panel:
            ax.set_ylim(panel["ylim"])
        _style_ax(ax)

    # Legend below the plot (skip if only one entry)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    if len(handles) > 1:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.02),
            ncol=min(len(handles), 5),
            frameon=True,
            fontsize=10,
        )

    if title:
        fig.suptitle(title, fontsize=15, fontweight="bold", color="#1a1a1a", y=1.01)

    plt.tight_layout()
    _save_fig(fig, save_path)
    return fig
