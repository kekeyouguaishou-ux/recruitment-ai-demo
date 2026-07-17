from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.analytics import calculate_metrics
from src.models import CandidateExtraction, InterviewInput, StageUpdate
from src.store import RecruitmentStore


def candidate(phone: str = "13900000000") -> CandidateExtraction:
    return CandidateExtraction(
        name="测试候选人",
        phone=phone,
        email="candidate@example.com",
        target_position="AI应用实习生",
        education="硕士",
        school="测试大学",
        major="计算数学",
        skills=["Python", "RAG"],
        source="校园招聘",
        confidence=0.95,
    )


def test_upsert_deduplicates_and_increments_version(tmp_path):
    store = RecruitmentStore(tmp_path / "demo.db")
    candidate_id, created = store.upsert_candidate(candidate())
    assert created is True

    updated = candidate()
    updated.school = "更新后的大学"
    updated.email = "updated@example.com"
    same_id, created_again = store.upsert_candidate(updated)

    assert same_id == candidate_id
    assert created_again is False
    row = store.list_candidates()[0]
    assert row["version"] == 2
    assert row["school"] == "更新后的大学"
    assert row["email"] == "updated@example.com"
    assert len(store.list_events()) == 2


def test_upsert_rejects_conflicting_phone_and_email_matches(tmp_path):
    store = RecruitmentStore(tmp_path / "demo.db")
    first = candidate("13900000001")
    first.email = "first@example.com"
    store.upsert_candidate(first)
    second = candidate("13900000002")
    second.email = "second@example.com"
    store.upsert_candidate(second)

    conflicting = candidate("13900000001")
    conflicting.email = "second@example.com"
    with pytest.raises(ValueError, match="匹配到不同候选人"):
        store.upsert_candidate(conflicting)


def test_stage_update_writes_timestamps_version_and_event(tmp_path):
    store = RecruitmentStore(tmp_path / "demo.db")
    candidate_id, _ = store.upsert_candidate(candidate())
    followup = (datetime.now().astimezone() + timedelta(days=1)).isoformat(timespec="seconds")

    store.update_stage(
        StageUpdate(
            candidate_id=candidate_id,
            to_stage="待面试",
            operator="HR-01",
            next_followup_at=followup,
        )
    )

    row = store.list_candidates()[0]
    assert row["stage"] == "待面试"
    assert row["stage_changed_at"]
    assert row["updated_at"]
    assert row["next_followup_at"] == followup
    assert row["version"] == 2
    event = store.list_events()[0]
    assert event["event_type"] == "stage_changed"
    assert event["from_stage"] == "待二次筛选"
    assert event["to_stage"] == "待面试"
    assert event["sync_status"] == "success"
    assert event["synced_at"]


def test_followup_update_does_not_reset_stage_timer_or_write_noop(tmp_path):
    store = RecruitmentStore(tmp_path / "demo.db")
    candidate_id, _ = store.upsert_candidate(candidate())
    original = store.list_candidates()[0]
    followup = (datetime.now().astimezone() + timedelta(days=2)).isoformat(
        timespec="seconds"
    )

    update = StageUpdate(
        candidate_id=candidate_id,
        to_stage="待二次筛选",
        operator="HR-01",
        next_followup_at=followup,
    )
    assert store.update_stage(update) == "followup_updated"
    changed = store.list_candidates()[0]
    assert changed["stage_changed_at"] == original["stage_changed_at"]
    assert changed["next_followup_at"] == followup
    assert changed["version"] == 2
    assert store.list_events()[0]["event_type"] == "followup_updated"

    event_count = len(store.list_events())
    assert store.update_stage(update) == "unchanged"
    assert store.list_candidates()[0]["version"] == 2
    assert len(store.list_events()) == event_count


def test_interview_and_dashboard_metrics(tmp_path):
    store = RecruitmentStore(tmp_path / "demo.db")
    candidate_id, _ = store.upsert_candidate(candidate())
    store.save_interview(
        InterviewInput(
            candidate_id=candidate_id,
            interviewer="业务负责人",
            scheduled_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            result="通过",
            score=4.5,
            feedback="逻辑清晰",
        )
    )

    metrics = calculate_metrics(store.list_candidates(), store.list_interviews())
    assert metrics["total_candidates"] == 1
    assert metrics["interview_rate"] == 100.0
    assert metrics["interview_pass_rate"] == 100.0


def test_seed_data_has_consistent_interview_metrics(tmp_path):
    store = RecruitmentStore(tmp_path / "demo.db")
    store.seed_demo_data()

    metrics = calculate_metrics(store.list_candidates(), store.list_interviews())
    assert len(store.list_interviews()) == 4
    assert metrics["interview_rate"] == 50.0
    assert metrics["interview_pass_rate"] == 50.0
