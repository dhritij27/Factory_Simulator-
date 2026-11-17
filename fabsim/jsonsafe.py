"""Write JSON that browsers can parse: NaN and +/-Infinity become null.

Python's json module writes NaN/Infinity by default, which JSON.parse rejects.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime


def clean(x):
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):      # numpy scalars
        return clean(x.item())
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    return x


def dumps(x, **kw) -> str:
    return json.dumps(clean(x), allow_nan=False, default=str, **kw)
