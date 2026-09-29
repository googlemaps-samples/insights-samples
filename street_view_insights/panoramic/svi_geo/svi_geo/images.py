"""Frame download + decoding helpers (user credentials, local disk cache).

Frames are always downloaded with the caller's own credentials (`download_as_bytes`) and
later sent to Gemini inline; nothing here grants or relies on service-agent bucket access.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
from google.api_core import exceptions as gexc

from svi_geo.data import split_gcs_uri

DEFAULT_FRAME_CACHE = Path.home() / ".cache" / "svi_geo" / "frames"

_TRANSIENT = (
    gexc.ServiceUnavailable,
    gexc.TooManyRequests,
    gexc.InternalServerError,
    gexc.GatewayTimeout,
    # Observed spuriously when many threads refresh a gcloud-token credential at once.
    gexc.Unauthorized,
    ConnectionError,
    TimeoutError,
)


def is_transient(e: BaseException) -> bool:
    """Errors worth retrying (5xx, 429, connection resets); 404/403 are not."""
    if isinstance(e, _TRANSIENT):
        return True
    name = type(e).__name__
    return name in {"ConnectionError", "Timeout", "ReadTimeout", "ChunkedEncodingError"}


class ImageFetcher(Protocol):
    def fetch(self, uri: str) -> bytes: ...


class GcsImageFetcher:
    """Download `gs://` objects as bytes with the user's credentials, caching on disk."""

    def __init__(
        self,
        storage_client: Any,
        cache_dir: str | Path | None = DEFAULT_FRAME_CACHE,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client = storage_client
        self._sleep = sleep
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.n_downloads = 0
        self.bytes_downloaded = 0

    def _cache_path(self, uri: str) -> Path | None:
        if self.cache_dir is None:
            return None
        bucket, name = split_gcs_uri(uri)
        safe = name.replace("/", "__").replace(":", "_")
        h = hashlib.sha1(uri.encode()).hexdigest()[:8]
        return self.cache_dir / f"{h}_{safe}"

    def fetch(self, uri: str) -> bytes:
        path = self._cache_path(uri)
        if path is not None and path.exists():
            return path.read_bytes()
        bucket, name = split_gcs_uri(uri)
        data = self.client.bucket(bucket).blob(name).download_as_bytes()
        self.n_downloads += 1
        self.bytes_downloaded += len(data)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        return data

    def fetch_many(
        self, uris: list[str], max_workers: int = 8, retries: int = 3
    ) -> dict[str, bytes | Exception]:
        out: dict[str, bytes | Exception] = {}

        def one(u):
            err: Exception | None = None
            for attempt in range(retries):
                try:
                    return u, self.fetch(u)
                except Exception as e:  # noqa: BLE001 - reported per item
                    err = e
                    if not is_transient(e) or attempt == retries - 1:
                        break
                    self._sleep(0.5 * 2**attempt)
            return u, err

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for u, r in ex.map(one, uris):
                out[u] = r
        return out

    def exists(self, uri: str) -> bool:
        bucket, name = split_gcs_uri(uri)
        return bool(self.client.bucket(bucket).blob(name).exists())


_REDUCED = {
    (0.5, False): cv2.IMREAD_REDUCED_COLOR_2,
    (0.5, True): cv2.IMREAD_REDUCED_GRAYSCALE_2,
    (0.25, False): cv2.IMREAD_REDUCED_COLOR_4,
    (0.25, True): cv2.IMREAD_REDUCED_GRAYSCALE_4,
}


def decode(data: bytes, scale: float = 1.0, gray: bool = False) -> np.ndarray:
    """JPEG bytes -> BGR (or gray) uint8 array, optionally resized by `scale`.

    Scales 0.5 / 0.25 use libjpeg's DCT-domain reduction (fast); others use INTER_AREA.
    """
    flag = _REDUCED.get((scale, gray))
    buf = np.frombuffer(data, np.uint8)
    if flag is not None:
        img = cv2.imdecode(buf, flag)
        if img is None:
            raise ValueError("could not decode image bytes")
        return img
    img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image bytes")
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return img


def encode_jpeg(img: np.ndarray, quality: int = 90) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise ValueError("jpeg encode failed")
    return buf.tobytes()


def fit_within(img: np.ndarray, max_side: int) -> np.ndarray:
    """Downscale so the longest side is <= max_side (never upscales)."""
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s >= 1.0:
        return img
    return cv2.resize(
        img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA
    )
