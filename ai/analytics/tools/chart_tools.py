"""Chart generation utilities — return base64-encoded PNG strings for email embedding."""
from __future__ import annotations

import base64
import io
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


def _b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    # dpi=55 keeps each chart ~5-7KB base64. A DevOps report with 6 charts
    # totals ~45KB incl. HTML, comfortably under Gmail's 102KB clip limit.
    fig.savefig(buf, format="png", dpi=55, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def make_line_chart(
    rows: list[dict[str, Any]],
    date_key: str,
    value_key: str,
    title: str,
    ylabel: str = "",
    color: str = "#2563EB",
) -> str:
    """
    Create a line chart from a list of dicts with date and value keys.
    Returns a base64-encoded PNG string.
    """
    dates = [row[date_key] for row in rows if row.get(date_key) and row.get(value_key) is not None]
    values = [float(row[value_key]) for row in rows if row.get(date_key) and row.get(value_key) is not None]
    if not dates:
        return ""

    # Parse dates if they're strings
    if dates and isinstance(dates[0], str):
        dates = [datetime.strptime(d, "%Y-%m-%d") for d in dates]

    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    ax.plot(dates, values, color=color, linewidth=2, marker="o", markersize=4)
    ax.fill_between(dates, values, alpha=0.1, color=color)
    ax.set_title(title, fontsize=12, fontweight="bold", pad=8)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=30)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _b64(fig)


def make_dual_line_chart(
    rows: list[dict[str, Any]],
    date_key: str,
    value_keys: list[str],
    labels: list[str],
    title: str,
    colors: list[str] | None = None,
) -> str:
    """Create a dual-line chart comparing two metrics over time. Returns base64 PNG."""
    if not colors:
        colors = ["#2563EB", "#DC2626"]

    dates = [row[date_key] for row in rows if row.get(date_key)]
    if isinstance(dates[0], str):
        dates = [datetime.strptime(d, "%Y-%m-%d") for d in dates]

    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    for key, label, color in zip(value_keys, labels, colors):
        vals = [float(row.get(key) or 0) for row in rows]
        ax.plot(dates, vals, color=color, linewidth=2, marker="o", markersize=4, label=label)

    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=30)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _b64(fig)


def make_bar_chart(
    labels: list[str],
    values: list[float],
    title: str,
    xlabel: str = "",
    color: str = "#2563EB",
    horizontal: bool = True,
) -> str:
    """Create a bar chart. Returns a base64-encoded PNG string."""
    if not labels:
        return ""
    # Truncate long labels
    labels = [str(l)[:35] + "…" if len(str(l)) > 35 else str(l) for l in labels]

    fig, ax = plt.subplots(figsize=(6.5, max(2.5, len(labels) * 0.35 + 0.8)))
    if horizontal:
        bars = ax.barh(labels[::-1], values[::-1], color=color, height=0.65)
        ax.set_xlabel(xlabel or "Count", fontsize=10)
        for bar, val in zip(bars, values[::-1]):
            ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"{val:,.0f}", va="center", fontsize=9)
    else:
        bars = ax.bar(labels, values, color=color, width=0.65)
        ax.set_ylabel(xlabel or "Count", fontsize=10)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
                    f"{val:,.0f}", ha="center", fontsize=9)
        fig.autofmt_xdate(rotation=30)

    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _b64(fig)


def make_pie_chart(labels: list[str], values: list[float], title: str) -> str:
    """Create a pie chart for distributions. Returns base64 PNG."""
    if not labels:
        return ""
    colors = ["#2563EB", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899"]
    fig, ax = plt.subplots(figsize=(5, 4))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        colors=colors[:len(labels)], startangle=140,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    plt.tight_layout()
    return _b64(fig)


def img_tag(b64: str) -> str:
    """Wrap a base64 PNG in an <img> HTML tag."""
    if not b64:
        return ""
    return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;border-radius:6px;margin:8px 0">'
