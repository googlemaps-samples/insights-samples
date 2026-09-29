import numpy as np
import pytest

from svi_geo import images


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def download_as_bytes(self):
        self.store.downloads += 1
        return self.store.objects[self.name]

    def exists(self):
        return self.name in self.store.objects


class FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, name):
        return FakeBlob(self.store, name)


class FakeStorage:
    def __init__(self, objects):
        self.objects = objects
        self.downloads = 0

    def bucket(self, name):
        assert name == "b"
        return FakeBucket(self)


def _jpeg(h=40, w=30):
    rng = np.random.default_rng(0)
    return images.encode_jpeg(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))


def test_fetch_caches_on_disk(tmp_path):
    store = FakeStorage({"s/v0/o1:P_0:5001ee.jpg": b"abc"})
    f = images.GcsImageFetcher(store, cache_dir=tmp_path)
    uri = "gs://b/s/v0/o1:P_0:5001ee.jpg"
    assert f.fetch(uri) == b"abc"
    assert f.fetch(uri) == b"abc"
    assert store.downloads == 1
    assert f.exists(uri) and not f.exists("gs://b/nope.jpg")


def test_fetch_many_reports_errors(tmp_path):
    store = FakeStorage({"a.jpg": b"1"})
    f = images.GcsImageFetcher(store, cache_dir=None)
    out = f.fetch_many(["gs://b/a.jpg", "gs://b/missing.jpg"])
    assert out["gs://b/a.jpg"] == b"1"
    assert isinstance(out["gs://b/missing.jpg"], Exception)


def test_decode_scale_and_fit_within():
    img = images.decode(_jpeg(40, 30), scale=0.5)
    assert img.shape == (20, 15, 3)
    assert images.fit_within(np.zeros((3000, 2000, 3), np.uint8), 1536).shape[:2] == (1536, 1024)
    assert images.fit_within(np.zeros((100, 50, 3), np.uint8), 1536).shape[:2] == (100, 50)
    with pytest.raises(ValueError):
        images.decode(b"not a jpeg")


class FlakyStorage(FakeStorage):
    """Raises the given exception for the first `n_fail` downloads."""

    def __init__(self, objects, exc, n_fail):
        super().__init__(objects)
        self.exc, self.n_fail = exc, n_fail

    def bucket(self, name):
        store = self

        class _B:
            def blob(self, n):
                class _Blob(FakeBlob):
                    def download_as_bytes(self_inner):
                        store.downloads += 1
                        if store.downloads <= store.n_fail:
                            raise store.exc
                        return store.objects[n]

                return _Blob(store, n)

        return _B()


def test_fetch_many_retries_only_transient_and_skips_final_sleep(tmp_path):
    from google.api_core import exceptions as gexc

    sleeps = []
    store = FlakyStorage({"a.jpg": b"1"}, gexc.ServiceUnavailable("503"), n_fail=2)
    f = images.GcsImageFetcher(store, cache_dir=None, sleep=sleeps.append)
    assert f.fetch_many(["gs://b/a.jpg"], retries=3)["gs://b/a.jpg"] == b"1"
    assert store.downloads == 3 and len(sleeps) == 2

    sleeps.clear()
    store = FlakyStorage({"a.jpg": b"1"}, gexc.NotFound("404"), n_fail=5)
    f = images.GcsImageFetcher(store, cache_dir=None, sleep=sleeps.append)
    out = f.fetch_many(["gs://b/a.jpg"], retries=3)
    assert isinstance(out["gs://b/a.jpg"], gexc.NotFound)
    assert store.downloads == 1 and sleeps == []

    store = FlakyStorage({"a.jpg": b"1"}, gexc.TooManyRequests("429"), n_fail=5)
    f = images.GcsImageFetcher(store, cache_dir=None, sleep=sleeps.append)
    out = f.fetch_many(["gs://b/a.jpg"], retries=3)
    assert isinstance(out["gs://b/a.jpg"], gexc.TooManyRequests)
    assert store.downloads == 3 and len(sleeps) == 2  # no sleep after the last attempt
