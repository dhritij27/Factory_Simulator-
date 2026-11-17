"""Check that every number and date in an agent's answer came from a tool result.

Allowed values are collected from every tool result (recursively) and from the
user's question. IDs such as CM2-L3-ST02, CLR-CM2-0123 or P1 are stripped
before numbers are extracted, so their digits don't count. A number matches an
allowed value if it equals that value rounded to the precision it was written at.

Known limitation: integers 0-9 are exempt, because counts ("two findings",
"3 windows") are derived rather than looked up. A fabricated single-digit value
would therefore pass.
"""
from __future__ import annotations

import json
import re

ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-_][A-Z0-9.]+)+\b|\bP[1-3]\b|\b[A-Z]{2,}\d+\b")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
NUM_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")


def _walk(x, out: list[str]) -> None:
    if isinstance(x, dict):
        for v in x.values():
            _walk(v, out)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _walk(v, out)
    elif x is not None:
        out.append(str(x))


def allowed_values(tool_results: list[dict], question: str) -> tuple[set[str], list[float], set[str]]:
    texts: list[str] = [question]
    for r in tool_results:
        _walk(r, texts)
    blob = "\n".join(texts)
    dates = set(DATE_RE.findall(blob))
    # also allow the date part and the HH:MM part of any datetime
    for d in list(dates):
        if "T" in d:
            dates.add(d.split("T")[0])
    times = set(TIME_RE.findall(blob))
    clean = DATE_RE.sub(" ", ID_RE.sub(" ", blob))
    nums = []
    for t in NUM_RE.findall(clean):
        try:
            nums.append(float(t))
        except ValueError:
            pass
    return dates, nums, times


def check(answer: str, tool_results: list[dict], question: str) -> dict:
    dates, nums, times = allowed_values(tool_results, question)
    bad: list[str] = []
    for d in DATE_RE.findall(answer):
        if d not in dates and d.split("T")[0] not in dates:
            bad.append(d)
    rest = DATE_RE.sub(" ", answer)
    for t in TIME_RE.findall(rest):
        if t not in times and t.zfill(5) not in times:
            bad.append(t)
    rest = TIME_RE.sub(" ", ID_RE.sub(" ", rest))
    for tok in NUM_RE.findall(rest):
        v = float(tok)
        if tok.lstrip("+-").isdigit() and 0 <= abs(v) <= 9:
            continue
        decimals = len(tok.split(".")[1]) if "." in tok else 0
        if not any(abs(round(a, decimals) - v) < 10 ** (-decimals) / 2 + 1e-12 or abs(abs(round(a, decimals)) - abs(v)) < 1e-12
                   for a in nums):
            bad.append(tok)
    return {"grounded": not bad, "ungrounded": bad}


def tool_results_from_transcript(transcript: list[dict]) -> list[dict]:
    out = []
    for step in transcript:
        if step.get("type") == "tool_result":
            r = step["result"]
            out.append(r if isinstance(r, dict) else json.loads(r))
    return out
