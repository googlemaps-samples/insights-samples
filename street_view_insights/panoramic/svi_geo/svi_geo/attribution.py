"""Attribution for figures and maps built from Street View Insights imagery.

Every figure that shows imagery (or a crop rendered from it) must credit Google, and maps of
results derived from the imagery carry the same credit next to the base-map attribution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

IMAGERY_CREDIT = "Imagery © Google"
ATTRIBUTION_TEXT = IMAGERY_CREDIT
# folium replaces the base map's attribution when `attr=` is given, so keep OpenStreetMap's.
FOLIUM_ATTR = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    " | Street View Insights: " + IMAGERY_CREDIT
)


def add_to_axes(ax: Any, text: str = IMAGERY_CREDIT) -> Any:
    """Write the imagery credit in the lower-right corner of a matplotlib axes."""
    return ax.text(
        0.99, 0.01, text, transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
        color="white", bbox={"facecolor": "black", "alpha": 0.5, "pad": 2, "edgecolor": "none"},
    )  # fmt: skip


def save_figure(
    fig: Any,
    path: str | Path,
    *,
    text: str = IMAGERY_CREDIT,
    dpi: int = 140,
) -> Path:
    """Ensure `text` is stamped on `fig` (last axes or figure footer) and save as PNG."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    has_credit = any(text in t.get_text() for t in getattr(fig, "texts", ())) or any(
        text in t.get_text() for ax in getattr(fig, "axes", ()) for t in getattr(ax, "texts", ())
    )
    if not has_credit:
        axes = getattr(fig, "axes", ())
        if axes:
            add_to_axes(axes[-1], text=text)
        else:
            fig.text(0.99, 0.01, text, ha="right", va="bottom", fontsize=8)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    return out
