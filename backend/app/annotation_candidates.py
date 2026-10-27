import re


HEADER = re.compile(r"^(inclusion|exclusion) criteria\s*:?$", re.I)
BULLET = re.compile(r"^(\s*)(?:\\?[-*+\u2022]|\d+[.)])\s+")
INLINE = re.compile(r"\s+(?=[*\u2022]\s+)")


def candidate_clauses(text):
    candidates = []
    section = heading = context = pending = None

    def quote(start, end):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return {"span": {"start": start, "end": end}, "text": text[start:end]}

    def flush():
        nonlocal pending
        if pending:
            original = quote(pending["start"], pending["end"])
            if original["text"] and not (pending.get("context_only") and context and original["text"] == context["text"]):
                warnings = pending["warnings"]
                if re.search(r"\b1[.)].*\b2[.)]", original["text"], re.S):
                    warnings.add("Numbered subclauses retained together")
                if len(original["text"]) > 1200:
                    warnings.add("Long clause: check boundaries")
                candidates.append({
                    "id": f"clause-{original['span']['start']}", "original": original,
                    "suggested_polarity": section, "heading": heading,
                    "context": context, "warnings": sorted(warnings),
                })
            pending = None

    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        header = HEADER.fullmatch(stripped)
        if header:
            flush()
            section = header.group(1).lower()
            heading = quote(offset, offset + len(line))
            context = None
        elif stripped and stripped.endswith(":") and not line[0].isspace() and not BULLET.match(line):
            flush()
            context = quote(offset, offset + len(line))
            pending = {"start": offset, "end": offset + len(line), "indent": -1,
                       "warnings": {"Context heading: check scope manually"}, "context_only": True}
        elif stripped:
            bullet = BULLET.match(line)
            indent = len(bullet.group(1).expandtabs(4)) if bullet else None
            if bullet and (pending is None or pending["indent"] == -1 or indent <= pending["indent"]):
                flush()
                parts = list(INLINE.finditer(line)) if indent == 0 else []
                starts = [0] + [match.end() for match in parts]
                for index, start in enumerate(starts):
                    if index:
                        flush()
                    end = starts[index + 1] if index + 1 < len(starts) else len(line)
                    pending = {"start": offset + start, "end": offset + end, "indent": indent,
                               "warnings": {"Inline bullets: check boundaries"} if parts else set()}
            elif pending:
                pending["end"] = offset + len(line)
                if bullet:
                    pending["warnings"].add("Nested clauses retained together")
            else:
                pending = {"start": offset, "end": offset + len(line), "indent": -1,
                           "warnings": {"Unbulleted text: check boundaries manually"}}
        offset += len(line)
    flush()
    return candidates
