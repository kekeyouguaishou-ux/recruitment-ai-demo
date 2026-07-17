from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .models import CandidateExtraction, InterviewInput, StageUpdate, now_iso


class RecruitmentStore:
    """SQLite-backed demo store that mirrors two Tencent Docs sheets plus an event log."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    target_position TEXT NOT NULL DEFAULT '',
                    education TEXT NOT NULL DEFAULT '',
                    school TEXT NOT NULL DEFAULT '',
                    major TEXT NOT NULL DEFAULT '',
                    years_experience REAL NOT NULL DEFAULT 0,
                    skills_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT '招聘网站',
                    stage TEXT NOT NULL DEFAULT '待二次筛选',
                    confidence REAL NOT NULL DEFAULT 0,
                    missing_fields_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    stage_changed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_followup_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_phone
                ON candidates(phone) WHERE phone != '';

                CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_email
                ON candidates(email) WHERE email != '';

                CREATE TABLE IF NOT EXISTS interviews (
                    interview_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    interviewer TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '待反馈',
                    score REAL,
                    feedback TEXT NOT NULL DEFAULT '',
                    feedback_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    candidate_id TEXT,
                    event_type TEXT NOT NULL,
                    from_stage TEXT,
                    to_stage TEXT,
                    operator TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    sync_target TEXT NOT NULL DEFAULT 'Mock Tencent Docs',
                    sync_status TEXT NOT NULL DEFAULT 'success',
                    synced_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_events_candidate_time
                ON events(candidate_id, event_time DESC);
                """
            )

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

    def _find_existing(self, connection: sqlite3.Connection, data: CandidateExtraction):
        matches = []
        if data.phone:
            row = connection.execute(
                "SELECT * FROM candidates WHERE phone = ?", (data.phone,)
            ).fetchone()
            if row:
                matches.append(row)
        if data.email:
            row = connection.execute(
                "SELECT * FROM candidates WHERE email = ?", (data.email,)
            ).fetchone()
            if row and all(item["candidate_id"] != row["candidate_id"] for item in matches):
                matches.append(row)
        if len(matches) > 1:
            raise ValueError("手机号和邮箱匹配到不同候选人，请人工核对")
        return matches[0] if matches else None

    def upsert_candidate(
        self,
        data: CandidateExtraction,
        *,
        operator: str = "AI简历解析助手",
        event_time: str | None = None,
    ) -> tuple[str, bool]:
        timestamp = event_time or now_iso()
        data = data.model_copy(
            update={
                "name": data.name.strip(),
                "phone": data.phone.strip(),
                "email": data.email.strip().lower(),
                "target_position": data.target_position.strip(),
            }
        )
        with self.connect() as connection:
            existing = self._find_existing(connection, data)
            if existing:
                candidate_id = existing["candidate_id"]
                connection.execute(
                    """
                    UPDATE candidates
                    SET name = ?, phone = ?, email = ?, target_position = ?,
                        education = ?, school = ?,
                        major = ?, years_experience = ?, skills_json = ?, source = ?,
                        confidence = ?, missing_fields_json = ?, updated_at = ?,
                        version = version + 1
                    WHERE candidate_id = ?
                    """,
                    (
                        data.name,
                        data.phone,
                        data.email,
                        data.target_position,
                        data.education,
                        data.school,
                        data.major,
                        data.years_experience,
                        json.dumps(data.skills, ensure_ascii=False),
                        data.source,
                        data.confidence,
                        json.dumps(data.missing_fields, ensure_ascii=False),
                        timestamp,
                        candidate_id,
                    ),
                )
                created = False
                event_type = "candidate_updated"
                from_stage = existing["stage"]
                to_stage = existing["stage"]
            else:
                candidate_id = self._new_id("C")
                connection.execute(
                    """
                    INSERT INTO candidates(
                        candidate_id, name, phone, email, target_position,
                        education, school, major, years_experience, skills_json,
                        source, stage, confidence, missing_fields_json,
                        created_at, stage_changed_at, updated_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        candidate_id,
                        data.name,
                        data.phone,
                        data.email,
                        data.target_position,
                        data.education,
                        data.school,
                        data.major,
                        data.years_experience,
                        json.dumps(data.skills, ensure_ascii=False),
                        data.source,
                        "待二次筛选",
                        data.confidence,
                        json.dumps(data.missing_fields, ensure_ascii=False),
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                created = True
                event_type = "candidate_created"
                from_stage = None
                to_stage = "待二次筛选"

            self._insert_event(
                connection,
                candidate_id=candidate_id,
                event_type=event_type,
                from_stage=from_stage,
                to_stage=to_stage,
                operator=operator,
                event_time=timestamp,
                payload=data.model_dump(),
            )
        return candidate_id, created

    def update_stage(self, update: StageUpdate, event_time: str | None = None) -> str:
        timestamp = event_time or now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT stage, next_followup_at FROM candidates WHERE candidate_id = ?",
                (update.candidate_id,),
            ).fetchone()
            if row is None:
                raise ValueError("候选人不存在")
            from_stage = row["stage"]
            stage_changed = from_stage != update.to_stage
            followup_changed = row["next_followup_at"] != update.next_followup_at
            if not stage_changed and not followup_changed:
                return "unchanged"

            if stage_changed:
                connection.execute(
                    """
                    UPDATE candidates
                    SET stage = ?, stage_changed_at = ?, updated_at = ?,
                        next_followup_at = ?, version = version + 1
                    WHERE candidate_id = ?
                    """,
                    (
                        update.to_stage,
                        timestamp,
                        timestamp,
                        update.next_followup_at,
                        update.candidate_id,
                    ),
                )
                event_type = "stage_changed"
            else:
                connection.execute(
                    """
                    UPDATE candidates
                    SET updated_at = ?, next_followup_at = ?, version = version + 1
                    WHERE candidate_id = ?
                    """,
                    (timestamp, update.next_followup_at, update.candidate_id),
                )
                event_type = "followup_updated"

            self._insert_event(
                connection,
                candidate_id=update.candidate_id,
                event_type=event_type,
                from_stage=from_stage,
                to_stage=update.to_stage,
                operator=update.operator,
                event_time=timestamp,
                payload={"next_followup_at": update.next_followup_at},
            )
        return event_type

    def save_interview(self, data: InterviewInput, event_time: str | None = None) -> str:
        timestamp = event_time or now_iso()
        interview_id = self._new_id("I")
        feedback_at = timestamp if data.result != "待反馈" else None
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO interviews(
                    interview_id, candidate_id, interviewer, scheduled_at,
                    result, score, feedback, feedback_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interview_id,
                    data.candidate_id,
                    data.interviewer,
                    data.scheduled_at,
                    data.result,
                    data.score,
                    data.feedback,
                    feedback_at,
                    timestamp,
                    timestamp,
                ),
            )
            self._insert_event(
                connection,
                candidate_id=data.candidate_id,
                event_type="interview_saved",
                from_stage=None,
                to_stage=None,
                operator=data.interviewer,
                event_time=timestamp,
                payload=data.model_dump(),
            )
        return interview_id

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        *,
        candidate_id: str | None,
        event_type: str,
        from_stage: str | None,
        to_stage: str | None,
        operator: str,
        event_time: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO events(
                event_id, candidate_id, event_type, from_stage, to_stage,
                operator, event_time, payload_json, sync_target,
                sync_status, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', ?)
            """,
            (
                self._new_id("E"),
                candidate_id,
                event_type,
                from_stage,
                to_stage,
                operator,
                event_time,
                json.dumps(payload, ensure_ascii=False, default=str),
                "Mock Tencent Docs",
                now_iso(),
            ),
        )

    def _rows(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def list_candidates(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM candidates ORDER BY updated_at DESC")

    def list_interviews(self) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT i.*, c.name, c.target_position
            FROM interviews i JOIN candidates c USING(candidate_id)
            ORDER BY i.scheduled_at DESC
            """
        )

    def list_events(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT e.*, c.name
            FROM events e LEFT JOIN candidates c USING(candidate_id)
            ORDER BY e.event_time DESC, e.rowid DESC LIMIT ?
            """,
            (limit,),
        )

    def clear(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM events")
            connection.execute("DELETE FROM interviews")
            connection.execute("DELETE FROM candidates")

    def seed_demo_data(self) -> None:
        if self.list_candidates():
            return
        now = datetime.now().astimezone()
        fixtures = [
            ("陈晨", "13800000001", "AI应用实习生", "武汉大学", "硕士", "Boss直聘", "待二次筛选", 5),
            ("李沐", "13800000002", "AI应用实习生", "湖南大学", "硕士", "校园招聘", "待面试", 2),
            ("王桐", "13800000003", "软件测试实习生", "中南大学", "本科", "内推", "面试中", 1),
            ("赵安", "13800000004", "产品运营实习生", "湘潭大学", "本科", "Boss直聘", "面试通过", 3),
            ("周可", "13800000005", "AI应用实习生", "华中科技大学", "硕士", "内推", "已发Offer", 7),
            ("孙雨", "13800000006", "软件测试实习生", "长沙理工大学", "本科", "校园招聘", "已淘汰", 4),
            ("何川", "13800000007", "数据分析实习生", "武汉理工大学", "硕士", "招聘网站", "待二次筛选", 3),
            ("林夏", "13800000008", "AI应用实习生", "武汉大学", "硕士", "校园招聘", "待面试", 1),
        ]
        for index, (name, phone, position, school, education, source, stage, age_days) in enumerate(fixtures):
            created = (now - timedelta(days=age_days + 2)).isoformat(timespec="seconds")
            candidate_id, _ = self.upsert_candidate(
                CandidateExtraction(
                    name=name,
                    phone=phone,
                    email=f"demo{index + 1}@example.com",
                    target_position=position,
                    education=education,
                    school=school,
                    major="计算机相关专业",
                    skills=["Python", "数据分析"],
                    source=source,
                    confidence=0.92,
                ),
                event_time=created,
            )
            followup = None
            if stage not in {"已发Offer", "已淘汰"}:
                followup_delta = -1 if age_days >= 3 else 1
                followup = (now + timedelta(days=followup_delta)).isoformat(timespec="seconds")
            if stage != "待二次筛选" or followup:
                changed = (now - timedelta(days=age_days)).isoformat(timespec="seconds")
                self.update_stage(
                    StageUpdate(
                        candidate_id=candidate_id,
                        to_stage=stage,
                        next_followup_at=followup,
                    ),
                    event_time=changed,
                )
            interview_results = {
                "面试中": ("待反馈", "等待面试官反馈"),
                "面试通过": ("通过", "专业基础扎实，沟通清晰"),
                "已发Offer": ("通过", "综合表现符合岗位要求"),
                "已淘汰": ("不通过", "本轮岗位匹配度不足"),
            }
            if stage in interview_results:
                result, feedback = interview_results[stage]
                scheduled_at = (now - timedelta(days=age_days + 1)).isoformat(
                    timespec="seconds"
                )
                self.save_interview(
                    InterviewInput(
                        candidate_id=candidate_id,
                        interviewer="业务面试官",
                        scheduled_at=scheduled_at,
                        result=result,
                        score=None if result == "待反馈" else (4.3 if result == "通过" else 2.8),
                        feedback=feedback,
                    ),
                    event_time=(now - timedelta(days=age_days)).isoformat(
                        timespec="seconds"
                    ),
                )
