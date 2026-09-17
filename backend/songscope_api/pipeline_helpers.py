from songscope_engine.pipeline import STAGES, overall_progress


def loading_overall(fraction: float) -> float:
    return overall_progress("loading", fraction)


def stage_list(current: str | None, status: str) -> list[dict]:
    keys = [k for k, _, _ in STAGES]
    idx = keys.index(current) if current in keys else -1
    out = []
    for i, (k, label, _) in enumerate(STAGES):
        if status == "completed":
            state = "done"
        elif i < idx:
            state = "done"
        elif i == idx:
            state = "active" if status in ("processing", "queued") else ("failed" if status == "failed" else "active")
        else:
            state = "pending"
        out.append({"key": k, "label": label, "state": state})
    return out
