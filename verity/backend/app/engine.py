"""Pure verification logic. No I/O, so every rule is unit-testable and explainable."""
from __future__ import annotations
import re
from datetime import date
from difflib import SequenceMatcher

DEFAULT_WEIGHTS = {"contradictory": 30, "outdated": 20, "unsupported": 15, "guideline": 12,
                   "required": 10, "review": 8, "ai": 5, "tone": 3}
_NUMW = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
_NW = "|".join(list(_NUMW)[1:])
_STOP = set("the and our you your for with are was were has have will can all more than this that from its not any".split())
_CLAIM = re.compile(r"guarantee|best|leading|only|first|proven|certified|award|safest|fastest|free|warranty|lifetime|never|always|\d|\b(?:%s)\b" % _NW, re.I)
_NEG = re.compile(r"\b(not|no|never|without)\b", re.I)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 3]


def tokens(text: str) -> set[str]:
    return {w[:-1] if w.endswith("s") else w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOP}


def numbers(text: str) -> list[str]:
    t = re.sub(r"\b(%s)\b" % _NW, lambda m: _NUMW[m.group(1)], text.lower())
    return re.findall(r"\d+(?:\.\d+)?", t)


def extract_claims(text: str) -> list[str]:
    return [s for s in sentences(text) if _CLAIM.search(s) and tokens(s)]


def _d(x):
    return date.fromisoformat(x) if isinstance(x, str) and x else x or None


def _ev(h: dict) -> dict:
    return {"title": h["title"], "version": h["version"], "effective": str(h.get("effective") or ""),
            "review": str(h.get("review") or ""), "passage": h["text"]}


def classify_claim(claim, current, superseded, today=None, min_score=0.3, strong=0.5) -> dict:
    """current/superseded: retrieval hits sorted best-first, each {text,title,version,effective,review,score}."""
    today = today or date.today()
    nums = numbers(claim)
    f = {"type": "unsupported", "claim": claim, "evidence": None, "fix": None,
         "why": "No approved passage supports this claim. No evidence was invented: add approved evidence or remove the claim."}
    cur = current[0] if current and current[0]["score"] >= min_score else None
    old = superseded[0] if superseded and superseded[0]["score"] >= min_score else None
    if cur:
        f["evidence"] = _ev(cur)
        pn = numbers(cur["text"])
        if nums and pn and not all(n in pn for n in nums):
            f.update(type="contradictory", why=f"The numbers in the claim ({', '.join(nums)}) differ from the approved source ({', '.join(pn)}).",
                     fix=f"Replace with the approved wording: \"{cur['text']}\"")
        elif (nums and not pn) or bool(_NEG.search(claim)) != bool(_NEG.search(cur["text"])) or (not nums and cur["score"] < strong):
            f.update(type="review", why="A related approved passage exists but the match is weak or its meaning may differ. A human must confirm.")
        else:
            rd, eff = _d(cur.get("review")), _d(cur.get("effective"))
            f.update(type="verified", why="Wording and figures agree with an approved passage.")
            if rd and rd < today:
                f.update(type="outdated", why=f"Supported by a source whose review date ({rd}) has passed. Confirm it is still valid.")
            elif not rd and not eff:
                f["why"] += " Uncertainty: the source has no effective or review date."
    elif old:
        f.update(type="outdated", evidence=_ev(old), fix=f"Check the current version of \"{old['title']}\".",
                 why=f"Only matches a superseded version (v{old['version']}) of \"{old['title']}\". The claim may reflect old information.")
    return f


def check_guidelines(text: str, ctx: dict, banned: list[dict], required: list[dict]) -> list[dict]:
    out = []
    for b in banned:
        n = len(re.findall(r"\b%s\b" % re.escape(b["value"]), text, re.I))
        if n:
            out.append({"type": "guideline", "claim": f"Term \"{b['value']}\" used {n}x", "evidence": None, "fix": f"Remove or reword \"{b['value']}\".",
                        "why": f"Mandatory guideline: {b.get('reason') or 'this term is not allowed'}. Context cannot override it."})
    for r in required:
        if r.get("platform", "Any") in ("Any", ctx.get("platform")) and r["value"].lower() not in text.lower():
            out.append({"type": "required", "claim": f"Missing required text: \"{r['value']}\"", "evidence": None,
                        "fix": f"Add \"{r['value']}\".", "why": f"Mandatory guideline for {r.get('platform', 'Any')} content."})
    if ctx.get("tone") == "Formal" and re.search(r"!|[\U0001F300-\U0001FAFF]", text):
        out.append({"type": "tone", "claim": "Informal punctuation or emoji", "evidence": None, "fix": None,
                    "why": f"Advisory: formal tone selected for {ctx.get('audience', 'this audience')}. Never replaces factual checks."})
    return out


def assess_risk(findings: list[dict], weights: dict | None = None) -> dict:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    rows, score = [], 0
    for t in w:
        n = sum(1 for f in findings if f["type"] == t)
        if n:
            rows.append({"factor": t, "count": n, "weight": w[t], "points": n * w[t]})
            score += n * w[t]
    contradictory = any(f["type"] == "contradictory" for f in findings)
    level = "High" if contradictory or score >= 30 else "Medium" if score >= 10 else "Low"
    why = ("A contradictory claim forces High risk. " if contradictory else "") + \
          f"Weighted total {score} (High >= 30, Medium >= 10). A triage aid, not a guarantee of factual correctness."
    if not findings:
        why += " No checkable claims were found, so this result is uncertain."
    return {"level": level, "score": score, "rows": rows, "why": why}


def diff_words(a: str, b: str) -> list[dict]:
    x, y = a.split(), b.split()
    ops = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append({"op": "same", "text": " ".join(x[i1:i2])})
            continue
        if i2 > i1:
            ops.append({"op": "removed", "text": " ".join(x[i1:i2])})
        if j2 > j1:
            ops.append({"op": "added", "text": " ".join(y[j1:j2])})
    return ops


def compare_versions(prev: list[dict], cur: list[dict]) -> dict:
    key = lambda f: (f["type"], f["claim"])
    p = {key(f) for f in prev if f["type"] != "verified"}
    c = {key(f) for f in cur if f["type"] != "verified"}
    fmt = lambda s: sorted(k[1] for k in s)
    return {"resolved": fmt(p - c), "unresolved": fmt(p & c), "new": fmt(c - p)}


def find_impacts(old_text: str, new_text: str, contents: list[dict]) -> list[dict]:
    """contents: [{id, text}]. Flags sentences that still resemble passages removed or changed in the new version."""
    kept = {s.lower() for s in sentences(new_text)}
    changed = [s for s in sentences(old_text) if s.lower() not in kept]
    hits = []
    for c in contents:
        ss = sentences(c["text"])
        for i, s in enumerate(ss, 1):
            st = tokens(s)
            for p in changed:
                pt, pn = tokens(p), numbers(p)
                shared = len(pt & st)
                if shared >= 2 and shared / min(len(pt), len(st)) >= 0.6 and (not pn or set(numbers(s)) & set(pn)):
                    hits.append({"content_id": c["id"], "old_text": p, "sentence": s, "location": f"sentence {i} of {len(ss)}"})
                    break
    return hits
