from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


STAGES = ["待二次筛选", "待面试", "面试中", "面试通过", "已发Offer", "已淘汰"]


class CandidateExtraction(BaseModel):
    name: str = Field(default="", description="候选人姓名")
    phone: str = Field(default="", description="手机号")
    email: str = Field(default="", description="邮箱")
    target_position: str = Field(default="", description="应聘岗位")
    education: str = Field(default="", description="最高学历")
    school: str = Field(default="", description="毕业院校")
    major: str = Field(default="", description="专业")
    years_experience: float = Field(default=0, ge=0, description="工作年限")
    skills: list[str] = Field(default_factory=list, description="技能关键词")
    source: str = Field(default="招聘网站", description="招聘渠道")
    confidence: float = Field(default=0.0, ge=0, le=1, description="抽取置信度")
    missing_fields: list[str] = Field(default_factory=list, description="缺失字段")


class SyncResult(BaseModel):
    success: bool
    adapter: str
    record_id: str
    synced_at: str
    message: str


class LLMConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


class StageUpdate(BaseModel):
    candidate_id: str
    to_stage: str
    operator: str = "HR-Demo"
    next_followup_at: str | None = None


class InterviewInput(BaseModel):
    candidate_id: str
    interviewer: str
    scheduled_at: str
    result: Literal["待反馈", "通过", "不通过", "待定"] = "待反馈"
    score: float | None = Field(default=None, ge=0, le=5)
    feedback: str = ""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

