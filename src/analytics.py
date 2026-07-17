from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .models import STAGES


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def calculate_metrics(
    candidates: list[dict[str, Any]], interviews: list[dict[str, Any]]
) -> dict[str, Any]:
    stage_counts = Counter(row["stage"] for row in candidates)
    source_counts = Counter(row["source"] for row in candidates)
    position_counts = Counter(row["target_position"] for row in candidates)
    now = datetime.now().astimezone()
    overdue = []
    stage_hours = []
    for row in candidates:
        followup = _parse_time(row.get("next_followup_at"))
        if followup and followup < now and row["stage"] not in {"已发Offer", "已淘汰"}:
            overdue.append(row)
        changed = _parse_time(row.get("stage_changed_at"))
        if changed:
            stage_hours.append(max(0.0, (now - changed).total_seconds() / 3600))

    interviewed_ids = {row["candidate_id"] for row in interviews}
    passed_ids = {
        row["candidate_id"] for row in interviews if row["result"] == "通过"
    }
    return {
        "total_candidates": len(candidates),
        "pending_screening": stage_counts.get("待二次筛选", 0),
        "active_interviews": stage_counts.get("待面试", 0) + stage_counts.get("面试中", 0),
        "offers": stage_counts.get("已发Offer", 0),
        "overdue_count": len(overdue),
        "average_stage_hours": round(sum(stage_hours) / len(stage_hours), 1)
        if stage_hours
        else 0,
        "stage_counts": {stage: stage_counts.get(stage, 0) for stage in STAGES},
        "source_counts": dict(source_counts),
        "position_counts": dict(position_counts),
        "interview_rate": round(len(interviewed_ids) / len(candidates) * 100, 1)
        if candidates
        else 0,
        "interview_pass_rate": round(len(passed_ids) / len(interviewed_ids) * 100, 1)
        if interviewed_ids
        else 0,
        "overdue_candidates": overdue,
    }

