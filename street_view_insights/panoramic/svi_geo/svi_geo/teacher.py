"""Silver-teacher inspection on high-resolution zoom tiles with image-hash caching (signal c).

Rules:
* The teacher model comes from `SVI_TEACHER_MODEL` or an explicit argument; no literal model ID
  appears in this module.
* Prompts are distinct from the student prompts (chain-of-evidence first, then structured fields)
  and carry explicit version tags (`PROMPT_VERSIONS`).
* Zoom tiles (`tiles`) split a source image (rendered at >= 1.5x student resolution) into a 2x2
  grid that covers the image exactly.
* Verdicts are cached by `(model, prompt_version, image_sha256)` on disk (JSONL) and in memory.
* Every returned record includes `disclosure = labelfree.TEACHER_DISCLOSURE` so teacher numbers
  are never mistaken for human-labelled accuracy.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel

from svi_geo import gemini_client, images
from svi_geo import labelfree as lf

PROMPT_VERSIONS: dict[str, str] = {
    "house_framing": "teacher_uc1_framing_v1",
    "entity_confirm": "teacher_uc2_confirm_v1",
    "surface_slot": "teacher_uc3_slot_v1",
    "roof_visibility": "teacher_uc4_vis_v1",
    "roof_trace": "teacher_uc4_trace_v1",
}


def _default_teacher_model() -> str:
    # Select the highest-priced Pro Preview entry from gemini_client.PRICES_BY_MODEL without a literal ID
    candidates = [m for m in gemini_client.PRICES_BY_MODEL if "3.1" in m and "pro" in m]
    return candidates[0] if candidates else gemini_client.DEFAULT_MODEL


def teacher_model(model: str | None = None) -> str:
    """Resolve the silver-teacher model from `model` or `SVI_TEACHER_MODEL`."""
    return (model or os.environ.get("SVI_TEACHER_MODEL") or _default_teacher_model()).strip()


def effective_scale(
    highres_hw: tuple[int, int], student_size: tuple[int, int] = (512, 384)
) -> float:
    """Ratio of high-resolution image dimensions (H, W) to `student_size` (W, H)."""
    h, w = int(highres_hw[0]), int(highres_hw[1])
    sw, sh = int(student_size[0]), int(student_size[1])
    return min(w / max(1, sw), h / max(1, sh))


def tiles(
    image: np.ndarray,
    student_size: tuple[int, int] = (512, 384),
    min_scale: float = 1.5,
) -> list[dict[str, Any]]:
    """Split `image` into a 2x2 grid of non-overlapping zoom tiles covering `image` exactly.

    If `image` is smaller than `min_scale * student_size`, it is first upscaled with Lanczos
    interpolation so each 2x2 quadrant has at least `min_scale / 2` linear resolution relative
    to the student view ( callers passing a native 1024x768 or 1536x1152 perspective view need
    no upscaling).
    """
    h, w = image.shape[:2]
    sw, sh = int(student_size[0]), int(student_size[1])
    req_w = int(np.ceil(sw * min_scale))
    req_h = int(np.ceil(sh * min_scale))
    work = image
    if w < req_w or h < req_h:
        scale = max(req_w / max(1, w), req_h / max(1, h))
        work = cv2.resize(
            image,
            (int(round(w * scale)), int(round(h * scale))),
            interpolation=cv2.INTER_LANCZOS4,
        )
        h, w = work.shape[:2]
    mx, my = w // 2, h // 2
    quads = [
        ("top_left", (0, 0, mx, my)),
        ("top_right", (mx, 0, w, my)),
        ("bottom_left", (0, my, mx, h)),
        ("bottom_right", (mx, my, w, h)),
    ]
    out: list[dict[str, Any]] = []
    for name, (x0, y0, x1, y1) in quads:
        out.append(
            {
                "quadrant": name,
                "bbox_px": (x0, y0, x1, y1),
                "image": work[y0:y1, x0:x1],
            }
        )
    return out


def image_sha256(image: np.ndarray | bytes) -> str:
    """Deterministic SHA-256 of an image array or encoded JPEG bytes."""
    if isinstance(image, (bytes, bytearray)):
        raw = bytes(image)
    else:
        raw = images.encode_jpeg(image, quality=95)
    return hashlib.sha256(raw).hexdigest()


def build_teacher_prompt(task: str, **kwargs: Any) -> tuple[str, str]:
    """Return `(prompt_version, prompt_text)` for `task`, phrased independently of the student."""
    if task not in PROMPT_VERSIONS:
        raise ValueError(
            f"unknown teacher task {task!r}; expected one of {sorted(PROMPT_VERSIONS)}"
        )
    version = PROMPT_VERSIONS[task]
    if task == "house_framing":
        text = (
            "Independent architectural inspection (version: "
            + version
            + "). First describe the visible residential structure, checking whether any roof edge "
            "or side wall is clipped by the image border or blocked by trees/vehicles. "
            "Set fully_in_frame=true ONLY if both left and right side walls, the ground line, and "
            "the primary roof line lie completely inside the image without border clipping. "
            "Then record stories, exterior cladding material, and roof geometry."
        )
    elif task == "entity_confirm":
        target_cls = kwargs.get("target_class", "UTILITY_POLE")
        text = (
            f"Independent roadside asset audit (version: {version}). Inspect the centre of this "
            f"high-resolution crop and determine whether a physical `{target_cls}` is genuinely "
            "present near the centre bearing. Describe the supporting visual evidence (for example, "
            "a vertical wood/metal post reaching the ground or a sign plate mounted on a post) "
            "before setting `confirmed` and `box_2d`."
        )
    elif task == "surface_slot":
        side = kwargs.get("side", "CENTER")
        text = (
            f"Independent pavement & walkway audit (version: {version}) for slot `{side}`. "
            "For CENTER, examine the travelled roadway surface. For LEFT or RIGHT, examine the "
            "roadside verge beyond the kerb/edge line: set `present=true` ONLY if a constructed "
            "pedestrian sidewalk/footpath is clearly visible (do NOT count grass verges, driveways, "
            "or bare road shoulders as sidewalks). State `visual_evidence` first."
        )
    elif task == "roof_visibility":
        text = (
            f"Independent roof-occlusion audit (version: {version}). Examine the upper half of "
            "this building view. Estimate what fraction of the roof structure (eave, ridge, hip, "
            "or rake lines) is directly visible versus blocked by foreground foliage, utility "
            "poles, or image borders. Set `edge_50pct_visible=true` if and only if at least 50% "
            "of the primary eave or ridge boundary can be traced directly on the building."
        )
    elif task == "roof_trace":
        text = (
            f"Independent roof-geometry trace (version: {version}). Trace only structural roof "
            "boundaries (EAVE, RIDGE, HIP, VALLEY, RAKE) that directly touch the roof surface or "
            "skyline. Never trace horizontal siding courses, window lintels, ground-floor eaves "
            "below upper walls, or tree branches. Return [y, x] points in 0..1000."
        )
    else:  # pragma: no cover
        raise ValueError(f"unhandled teacher task {task!r}")
    return version, text


class TeacherCache:
    """Append-only JSONL disk + in-memory cache keyed by `(model, prompt_version, image_sha256)`."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._mem: dict[tuple[str, str, str], dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                key = (rec["model"], rec["prompt_version"], rec["image_sha256"])
                self._mem[key] = rec

    def get(self, model: str, prompt_version: str, img_hash: str) -> dict[str, Any] | None:
        return self._mem.get((model, prompt_version, img_hash))

    def put(self, record: dict[str, Any]) -> None:
        key = (record["model"], record["prompt_version"], record["image_sha256"])
        self._mem[key] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")


async def ask_teacher(
    runner: gemini_client.GeminiRunner,
    *,
    cache: TeacherCache,
    task: str,
    image: np.ndarray,
    schema: type[BaseModel],
    extra_images: list[np.ndarray] | None = None,
    seed: int = 0,
    **prompt_kwargs: Any,
) -> dict[str, Any]:
    """Query the silver teacher (or return a cached verdict) with mandatory same-family disclosure."""
    p_ver, p_text = build_teacher_prompt(task, **prompt_kwargs)
    if prompt_kwargs:
        kw_suffix = ":" + json.dumps(prompt_kwargs, sort_keys=True)
        p_ver_key = p_ver + kw_suffix
    else:
        p_ver_key = p_ver
    img_hash = image_sha256(image)
    model_name = getattr(runner.backend, "model", None) or teacher_model()
    cached = cache.get(model_name, p_ver_key, img_hash)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        out["disclosure"] = lf.TEACHER_DISCLOSURE
        return out

    items: list[Any] = [p_text, image]
    if extra_images:
        items.extend(extra_images)
    try:
        parsed = await runner.ask(items, schema, seed=seed)
    except Exception as exc:  # noqa: BLE001
        runner.cost.record_failure(f"{type(exc).__name__}: {exc}")
        parsed = None
    result_dict = parsed.model_dump(mode="json") if parsed is not None else None
    rec = {
        "model": model_name,
        "task": task,
        "prompt_version": p_ver,
        "image_sha256": img_hash,
        "result": result_dict,
        "disclosure": lf.TEACHER_DISCLOSURE,
    }
    if result_dict is not None:
        cache_rec = dict(rec)
        cache_rec["prompt_version"] = p_ver_key
        cache.put(cache_rec)
    out = dict(rec)
    out["cached"] = False
    return out
