"""Imagery attribution on figures and maps."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from svi_geo import attribution  # noqa: E402


def test_add_to_axes_writes_the_imagery_credit():
    fig, ax = plt.subplots()
    attribution.add_to_axes(ax)
    texts = [t.get_text() for t in ax.texts]
    assert attribution.IMAGERY_CREDIT in texts
    assert "Imagery © Google" in attribution.IMAGERY_CREDIT
    plt.close(fig)


def test_folium_attribution_is_non_empty():
    assert attribution.FOLIUM_ATTR.strip()
    assert "Google" in attribution.FOLIUM_ATTR
