"""Attribution for figures and maps built from Street View Insights imagery.

Every figure that shows imagery (or a crop rendered from it) must credit Google, and maps of
results derived from the imagery carry the same credit next to the base-map attribution.
"""

from __future__ import annotations

from typing import Any

IMAGERY_CREDIT = "Imagery © Google"
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
