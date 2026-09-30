"""Print the versions that matter for Colab compatibility, and check the APIs svi_geo uses.

Run inside a Colab-equivalent venv by check_colab_compat.py (a script file, not `python -c`).
Exits non-zero if google-genai lacks an API svi_geo relies on or OpenCV has no LSD detector.
"""

import sys
from importlib.metadata import version

import cv2
import numpy as np
from google.genai import types


def main() -> int:
    missing = [
        name
        for name in ("HttpRetryOptions", "AutomaticFunctionCallingConfig", "GenerateContentConfig")
        if not hasattr(types, name)
    ]
    fields = types.GenerateContentConfig.model_fields
    missing += [
        f"GenerateContentConfig.{f}" for f in ("response_schema", "seed") if f not in fields
    ]
    lines = cv2.createLineSegmentDetector().detect(np.pad(np.full((40, 4), 255, np.uint8), 30))[0]
    if lines is None or len(lines) == 0:
        missing.append("cv2 LSD found no line on a synthetic bar")
    names = ["python", "numpy", "pandas", "scipy", "scikit-learn", "pyarrow"]
    names += ["google-genai", "opencv-python-headless"]
    vers = [f"python={sys.version.split()[0]}"] + [f"{n}={version(n)}" for n in names[1:]]
    print(" ".join(vers))
    if missing:
        print("MISSING:", missing)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
