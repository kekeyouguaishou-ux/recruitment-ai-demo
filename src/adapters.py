from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .models import CandidateExtraction, InterviewInput, StageUpdate, SyncResult, now_iso
from .store import RecruitmentStore


class RecruitmentDocumentAdapter(ABC):
    """Stable contract for the demo and a future Tencent Docs integration."""

    @abstractmethod
    def upsert_candidate(self, data: CandidateExtraction) -> SyncResult: ...

    @abstractmethod
    def update_stage(self, update: StageUpdate) -> SyncResult: ...

    @abstractmethod
    def save_interview(self, data: InterviewInput) -> SyncResult: ...


class MockTencentDocsAdapter(RecruitmentDocumentAdapter):
    """A runnable, transparent stand-in approved for this assignment."""

    name = "脱敏模拟腾讯文档"

    def __init__(self, database_path: str | Path):
        self.store = RecruitmentStore(database_path)

    def upsert_candidate(self, data: CandidateExtraction) -> SyncResult:
        candidate_id, created = self.store.upsert_candidate(data)
        return SyncResult(
            success=True,
            adapter=self.name,
            record_id=candidate_id,
            synced_at=now_iso(),
            message="新增候选人记录" if created else "根据手机号或邮箱更新已有记录",
        )

    def update_stage(self, update: StageUpdate) -> SyncResult:
        update_kind = self.store.update_stage(update)
        messages = {
            "stage_changed": f"候选人阶段已更新为：{update.to_stage}",
            "followup_updated": "下次跟进时间已更新",
            "unchanged": "阶段和跟进时间没有变化",
        }
        return SyncResult(
            success=True,
            adapter=self.name,
            record_id=update.candidate_id,
            synced_at=now_iso(),
            message=messages[update_kind],
        )

    def save_interview(self, data: InterviewInput) -> SyncResult:
        interview_id = self.store.save_interview(data)
        return SyncResult(
            success=True,
            adapter=self.name,
            record_id=interview_id,
            synced_at=now_iso(),
            message="面试记录已同步",
        )


class TencentDocsAdapter(RecruitmentDocumentAdapter):
    """Production adapter boundary.

    The assignment owner approved a mock integration because no enterprise test
    account is available. These methods intentionally fail fast until official
    credentials, document identifiers and endpoint mappings are supplied.
    """

    def __init__(self, access_token: str, candidate_doc_id: str, interview_doc_id: str):
        self.access_token = access_token
        self.candidate_doc_id = candidate_doc_id
        self.interview_doc_id = interview_doc_id

    def _not_configured(self) -> None:
        raise RuntimeError("腾讯文档企业版API尚未配置，请使用脱敏模拟适配器")

    def upsert_candidate(self, data: CandidateExtraction) -> SyncResult:
        self._not_configured()

    def update_stage(self, update: StageUpdate) -> SyncResult:
        self._not_configured()

    def save_interview(self, data: InterviewInput) -> SyncResult:
        self._not_configured()
