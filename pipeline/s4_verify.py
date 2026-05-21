BLOCKED_SOURCE_CLASSES = {"ADVOCACY", "SELF_REPORTED", "UNVERIFIED"}

def run(bundle):
    facts = []
    for f in bundle.get("facts", []):
        f = dict(f)
        if f.get("source_class") in BLOCKED_SOURCE_CLASSES or f.get("confidence") in ("LOW", "NONE"):
            f["in_main_analysis"] = False
        facts.append(f)
    return {**bundle, "facts": facts}
