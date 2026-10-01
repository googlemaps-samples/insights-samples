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


# ----------------------------------------------------------------------------- Task 10

from svi_geo.data import gcs_uri_for  # noqa: E402


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


URI0 = gcs_uri_for("b", "s", "o1:P_0:5001ee")
URI1 = gcs_uri_for("b", "s", "o1:P_1:5001ee")


def _store():
    return FakeStorage({"s/v0/o1:P_0:5001ee.jpg": b"abc", "s/v0/o1:P_1:5001ee.jpg": b"de"})


def test_frame_cache_is_opt_in():
    store = _store()
    f = images.GcsImageFetcher(store)
    assert f.cache_dir is None
    f.fetch(URI0)
    f.fetch(URI0)
    assert store.downloads == 2


def test_cached_frame_older_than_ttl_is_downloaded_again(tmp_path):
    store = _store()
    clock = Clock()
    f = images.GcsImageFetcher(store, cache_dir=tmp_path, cache_ttl_s=100, clock=clock)
    f.fetch(URI0)
    clock.t += 50
    f.fetch(URI0)
    assert store.downloads == 1
    clock.t += 51  # 101 s after the download
    assert f.fetch(URI0) == b"abc"
    assert store.downloads == 2


def test_purge_expired_deletes_only_stale_files(tmp_path):
    store = _store()
    clock = Clock()
    f = images.GcsImageFetcher(store, cache_dir=tmp_path, cache_ttl_s=100, clock=clock)
    f.fetch(URI0)
    clock.t += 80
    f.fetch(URI1)
    clock.t += 30  # first file is 110 s old, second 30 s
    assert f.purge_expired() == 1
    assert len(list(tmp_path.iterdir())) == 1
    f.fetch(URI1)
    assert store.downloads == 2


# ----------------------------------------------------------------------------- F8
def test_dark_pixel_fraction_counts_near_black_pixels_not_dark_grey():
    img = np.full((100, 200, 3), 120, np.uint8)
    img[:5, :] = 0  # rendered no-coverage border: 5 %
    img[50:60, 50:70] = (3, 5, 2)  # a near-black redaction blob after JPEG: 1 %
    img[80:90, :] = 40  # dark shadow, not near-black
    assert images.dark_pixel_fraction(img) == pytest.approx(0.06)
    assert images.dark_pixel_fraction(img, max_value=0) == pytest.approx(0.05)


# ----------------------------------------------------------------------------- U6: scale choice, CLAHE, content-hash cache


def test_decode_scale_choice_from_px_per_deg():
    # A 1024px 70 deg view is ~14.6 px/deg vs sensor ~36.5 px/deg -> 1.2 * 14.6 / 36.5 = 0.48 <= 0.5
    assert images.decode_scale_for_view(1024, 70.0) == 0.5
    assert images.decode_scale_for_view(1280, 70.0) == 0.5
    # A narrow 20 deg zoom view at 1024 px is ~51.2 px/deg -> needs full-res (1.0)
    assert images.decode_scale_for_view(1024, 20.0) == 1.0
    # A tiny thumbnail 256 px over 80 deg -> 3.2 px/deg -> 0.25
    assert images.decode_scale_for_view(256, 80.0) == 0.25


def test_clahe_lab_enhances_low_contrast_without_changing_shape():
    rng = np.random.default_rng(7)
    low_contrast = rng.integers(90, 130, (64, 80, 3), dtype=np.uint8)
    out = images.clahe_lab(low_contrast, clip=2.0, tile=8)
    assert out.shape == low_contrast.shape and out.dtype == np.uint8
    assert float(out.std()) > float(low_contrast.std())


def test_frame_cache_invalidates_on_content_hash(tmp_path):
    store = FakeStorage({"s/v0/o1:P_0:5001ee.jpg": b"version_1_bytes"})
    f = images.GcsImageFetcher(store, cache_dir=tmp_path)
    assert f.fetch(URI0) == b"version_1_bytes"
    # Sidecar records sha256(bytes)[:16]
    assert f.cached_content_hash(URI0) is not None
    # When expected_sha256 mismatches cached bytes, it re-downloads
    store.objects["s/v0/o1:P_0:5001ee.jpg"] = b"version_2_bytes"
    assert f.fetch(URI0, expected_sha256="deadbeef00000000") == b"version_2_bytes"
    assert store.downloads == 2
