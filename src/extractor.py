from __future__ import annotations

import io
import json
import re
from pathlib import Path

import httpx

from .models import CandidateExtraction, LLMConfig


SCHEMA_FIELDS = [
    "name",
    "phone",
    "email",
    "target_position",
    "education",
    "school",
    "major",
]


def extract_file_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        for encoding in ("utf-8", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("解析PDF需要安装pypdf") from exc
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ValueError("该PDF未提取到文字，可能是扫描件，建议转换为文本或接入VLM")
        return text
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("解析DOCX需要安装python-docx") from exc
        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    raise ValueError("当前支持PDF、DOCX、TXT和Markdown简历")


def _first_match(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def demo_extract(text: str) -> CandidateExtraction:
    """Deterministic fallback so the public preview remains runnable without secrets."""
    phone = _first_match([r"(?<!\d)(1[3-9]\d{9})(?!\d)"], text)
    email = _first_match([r"([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"], text)
    name = _first_match(
        [
            r"(?:姓名|Name)\s*[:：]\s*([\u4e00-\u9fff]{2,4})",
            r"^\s*([\u4e00-\u9fff]{2,4})\s*$",
        ],
        text,
    )
    position = _first_match(
        [r"(?:应聘岗位|目标岗位|求职意向)\s*[:：]\s*([^\n]+)"], text
    )
    school = _first_match(
        [r"(?:毕业院校|学校|院校)\s*[:：]\s*([^\n，,]+)"], text
    )
    major = _first_match([r"(?:专业)\s*[:：]\s*([^\n，,]+)"], text)
    education = _first_match([r"(博士|硕士|本科|大专|高中)"], text)

    skill_terms = [
        "Python",
        "SQL",
        "Java",
        "MATLAB",
        "RAG",
        "Agent",
        "LangGraph",
        "PyTorch",
        "TensorFlow",
        "数据分析",
        "软件测试",
    ]
    skills = [term for term in skill_terms if term.lower() in text.lower()]
    years_match = re.search(r"(\d+(?:\.\d+)?)\s*年(?:工作|项目)?经验", text)
    years = float(years_match.group(1)) if years_match else 0.0
    extracted = {
        "name": name,
        "phone": phone,
        "email": email,
        "target_position": position,
        "education": education,
        "school": school,
        "major": major,
        "years_experience": years,
        "skills": skills,
        "source": "简历上传",
    }
    missing = [field for field in SCHEMA_FIELDS if not extracted.get(field)]
    present_count = len(SCHEMA_FIELDS) - len(missing)
    return CandidateExtraction(
        **extracted,
        confidence=round(0.45 + 0.5 * present_count / len(SCHEMA_FIELDS), 2),
        missing_fields=missing,
    )


def _json_from_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("模型未返回JSON对象")
    return json.loads(cleaned[start : end + 1])


def llm_extract(text: str, config: LLMConfig) -> CandidateExtraction:
    if not config.api_key.strip():
        raise ValueError("真实大模型模式需要API Key")
    schema = CandidateExtraction.model_json_schema()
    prompt = f"""你是招聘简历信息抽取助手。请严格依据简历原文抽取信息，不要猜测。
返回一个JSON对象，字段必须符合下面的JSON Schema：
{json.dumps(schema, ensure_ascii=False)}

规则：
1. 没有的信息使用空字符串、0或空列表。
2. confidence取0到1，表示整体抽取把握。
3. missing_fields列出缺失的核心字段。
4. 只输出JSON，不要解释。

简历原文：
{text[:16000]}
"""
    endpoint = config.base_url.rstrip("/") + "/chat/completions"
    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {config.api_key}"},
        json={
            "model": config.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return CandidateExtraction.model_validate(_json_from_response(content))


def extract_candidate(text: str, config: LLMConfig) -> tuple[CandidateExtraction, str]:
    if config.enabled:
        return llm_extract(text, config), f"真实大模型：{config.model}"
    return demo_extract(text), "脱敏演示解析器"


def brief_metrics_payload(metrics: dict) -> dict:
    """Keep candidate-level and contact data out of external model requests."""
    allowed_fields = (
        "total_candidates",
        "pending_screening",
        "active_interviews",
        "offers",
        "overdue_count",
        "average_stage_hours",
        "stage_counts",
        "source_counts",
        "position_counts",
        "interview_rate",
        "interview_pass_rate",
    )
    return {field: metrics.get(field) for field in allowed_fields}


def generate_ai_brief(metrics: dict, config: LLMConfig) -> str:
    if not config.enabled or not config.api_key.strip():
        return _template_brief(metrics)
    safe_metrics = brief_metrics_payload(metrics)
    prompt = f"""你是招聘运营分析助手。根据以下已经计算好的指标，生成一段120字以内的招聘日报。
必须先陈述事实，再指出一个流程瓶颈，最后给出可执行建议。不要评价候选人个人能力。
指标：{json.dumps(safe_metrics, ensure_ascii=False, default=str)}
"""
    endpoint = config.base_url.rstrip("/") + "/chat/completions"
    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {config.api_key}"},
        json={
            "model": config.model,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _template_brief(metrics: dict) -> str:
    stage_counts = metrics.get("stage_counts", {})
    backlog_stage = max(stage_counts, key=stage_counts.get) if stage_counts else "暂无"
    overdue = metrics.get("overdue_count", 0)
    return (
        f"今日候选人共{metrics.get('total_candidates', 0)}人，当前人数最多的环节是"
        f"“{backlog_stage}”。共有{overdue}条记录超过跟进时间，建议HR优先处理超时"
        "候选人，并检查该环节的筛选标准和人员安排。"
    )
