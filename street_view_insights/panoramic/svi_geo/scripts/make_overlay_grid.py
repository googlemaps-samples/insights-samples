#!/usr/bin/env python3
"""Render a visual QA overlay grid for an SVI panoramic notebook (U12 / §4.4).

Delegates to `svi_geo.maps.render_overlay_grid` so notebooks and CLI scripts share a single
source of truth.
"""

from __future__ import annotations

from svi_geo.maps import _draw_overlay_panel as _draw_panel
from svi_geo.maps import render_overlay_grid

__all__ = ["_draw_panel", "render_overlay_grid"]
