import svi_geo


def test_import_and_version():
    assert isinstance(svi_geo.__version__, str)
    assert svi_geo.__version__.count(".") == 2
