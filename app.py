from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src.adapters import MockTencentDocsAdapter
from src.analytics import calculate_metrics
from src.extractor import extract_candidate, extract_file_text, generate_ai_brief
from src.models import CandidateExtraction, InterviewInput, LLMConfig, STAGES, StageUpdate


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / ".data"
DB_PATH_OVERRIDE = os.getenv("RECRUITMENT_DEMO_DB")
SAMPLE_RESUME = ROOT / "sample_data" / "sample_resume.txt"


st.set_page_config(
    page_title="AI招聘运营台",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

if DB_PATH_OVERRIDE:
    DB_PATH = Path(DB_PATH_OVERRIDE)
else:
    session_id = st.session_state.setdefault("demo_session_id", uuid.uuid4().hex)
    DB_PATH = DATA_DIR / f"recruitment_demo_{session_id}.db"

st.markdown(
    """
    <style>
    :root {
      --ink: #17212b;
      --muted: #68737d;
      --line: #dce2e7;
      --surface: #f5f7f8;
      --accent: #087e8b;
      --accent-dark: #08616a;
      --blue: #356b94;
      --warning: #a66a19;
      --danger: #a34b4b;
    }
    .stApp { background: #ffffff; color: var(--ink); }
    .block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1280px; }
    h1, h2, h3 { letter-spacing: 0 !important; color: var(--ink); }
    h1 { font-size: 1.85rem !important; line-height: 1.2 !important; }
    h2 { font-size: 1.3rem !important; }
    h3 { font-size: 1.02rem !important; }
    p { line-height: 1.6; }
    section[data-testid="stSidebar"] {
      background: #f7f9fa;
      border-right: 1px solid var(--line);
    }
    section[data-testid="stSidebar"] .block-container { padding-top: 1.25rem; }
    header[data-testid="stHeader"] { background: rgba(255,255,255,0.92); }
    [data-testid="stToolbar"] { visibility: hidden; }
    .app-header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 1.5rem;
      border-bottom: 1px solid var(--line);
      padding: 0.35rem 0 1rem;
      margin-bottom: 0.35rem;
    }
    .app-eyebrow, .section-kicker {
      color: var(--accent-dark);
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .app-header h1 { margin: 0.18rem 0 0.25rem; }
    .app-subtitle { color: var(--muted); font-size: 0.92rem; margin: 0; }
    .header-status { text-align: right; white-space: nowrap; }
    .status-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #2f8f63;
      margin-right: 0.4rem;
    }
    .header-status strong { font-size: 0.84rem; }
    .header-status span { color: var(--muted); font-size: 0.78rem; }
    .section-heading { margin: 1.15rem 0 0.85rem; }
    .section-heading h2 { margin: 0.15rem 0 0.2rem; }
    .section-heading p { color: var(--muted); font-size: 0.88rem; margin: 0; }
    .candidate-profile {
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 1rem 0;
      margin-bottom: 1rem;
    }
    .candidate-profile h3 { margin: 0 0 0.25rem; font-size: 1.2rem !important; }
    .candidate-profile p { margin: 0.2rem 0; color: var(--muted); font-size: 0.88rem; }
    .stage-label { color: var(--accent-dark); font-weight: 700; }
    .mono-note { color: var(--muted); font-size: 0.78rem; font-family: monospace; }
    .candidate-stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 1rem;
      padding: 0.15rem 0 0.9rem;
    }
    .candidate-stat span {
      display: block;
      color: var(--muted);
      font-size: 0.75rem;
      margin-bottom: 0.25rem;
    }
    .candidate-stat strong { font-size: 0.92rem; font-weight: 600; }
    [data-testid="stMetric"] {
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0.75rem 0.9rem;
      min-height: 92px;
    }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { font-size: 1.45rem; }
    [data-testid="stForm"] {
      border-radius: 6px;
    }
    .small-note { color: var(--muted); font-size: 0.88rem; }
    div.stButton > button, div.stDownloadButton > button { border-radius: 6px; }
    div[data-baseweb="tab-list"] {
      gap: 1.5rem;
      border-bottom: 1px solid var(--line);
    }
    button[data-baseweb="tab"] { padding-left: 0; padding-right: 0; }
    [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 6px; }
    [data-testid="stFileUploaderDropzone"] { background: #fbfcfc; border-color: var(--line); }
    div[data-testid="stExpander"] { border-color: var(--line); border-radius: 6px; }
    @media (max-width: 700px) {
      .block-container { padding: 0.8rem 1rem 2.5rem; }
      .app-header { align-items: flex-start; }
      .header-status { display: none; }
      div[data-baseweb="tab-list"] { gap: 1rem; overflow-x: auto; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_adapter(database_path: str) -> MockTencentDocsAdapter:
    adapter = MockTencentDocsAdapter(database_path)
    adapter.store.seed_demo_data()
    return adapter


def secret_or_env(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, os.getenv(name, default)))
    except FileNotFoundError:
        return os.getenv(name, default)


def mask_phone(value: str) -> str:
    if len(value) >= 7:
        return value[:3] + "****" + value[-4:]
    return value


def format_timestamp(value: str | None, include_date: bool = True) -> str:
    if not value:
        return "未设置"
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%m月%d日 %H:%M" if include_date else "%H:%M")
    except (TypeError, ValueError):
        return str(value)


def section_heading(kicker: str, title: str, subtitle: str = "") -> None:
    subtitle_html = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f"""
        <div class="section-heading">
          <div class="section-kicker">{escape(kicker)}</div>
          <h2>{escape(title)}</h2>
          {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def display_candidate_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["phone"] = frame["phone"].map(mask_phone)
    frame["skills"] = frame["skills_json"].map(
        lambda value: "、".join(json.loads(value or "[]"))
    )
    frame["stage_changed_at"] = frame["stage_changed_at"].map(format_timestamp)
    frame["next_followup_at"] = frame["next_followup_at"].map(format_timestamp)
    columns = {
        "candidate_id": "候选人编号",
        "name": "姓名",
        "target_position": "应聘岗位",
        "phone": "手机号（脱敏）",
        "source": "渠道",
        "stage": "当前阶段",
        "skills": "技能",
        "stage_changed_at": "阶段更新时间",
        "next_followup_at": "下次跟进时间",
        "version": "版本",
    }
    return frame[list(columns)].rename(columns=columns)


adapter = get_adapter(str(DB_PATH))
store = adapter.store

with st.sidebar:
    st.markdown("### AI招聘运营台")
    st.caption("Testin 招聘提效场景 Demo")
    st.divider()
    st.markdown("**运行环境**")
    st.success("模拟腾讯文档 · 已连接", icon=":material/check_circle:")
    st.caption("脱敏数据环境，适配层可替换为真实接口。")

    with st.expander("模型设置", icon=":material/model_training:"):
        llm_enabled = st.toggle("启用真实大模型", value=False)
        default_key = secret_or_env("LLM_API_KEY")
        api_key = st.text_input(
            "API Key",
            value=default_key,
            type="password",
            disabled=not llm_enabled,
            help="仅在当前会话使用，不写入数据库或日志。",
        )
        base_url = st.text_input(
            "兼容接口地址",
            value=secret_or_env("LLM_BASE_URL", "https://api.deepseek.com"),
            disabled=not llm_enabled,
        )
        model_name = st.text_input(
            "模型",
            value=secret_or_env("LLM_MODEL", "deepseek-chat"),
            disabled=not llm_enabled,
        )

    with st.expander("演示数据", icon=":material/database:"):
        st.caption("重置后恢复预置候选人与面试流水。")
        if st.button(
            "重置数据",
            icon=":material/restart_alt:",
            width="stretch",
        ):
            store.clear()
            store.seed_demo_data()
            st.session_state.pop("extracted_candidate", None)
            st.session_state.pop("resume_source_name", None)
            st.session_state.pop("resume_source_bytes", None)
            st.success("演示数据已重置")
            st.rerun()

llm_config = LLMConfig(
    enabled=llm_enabled,
    api_key=api_key,
    base_url=base_url,
    model=model_name,
)

st.markdown(
    f"""
    <div class="app-header">
      <div>
        <div class="app-eyebrow">Recruitment Operations</div>
        <h1>AI 招聘运营台</h1>
        <p class="app-subtitle">候选人信息、招聘进度与面试反馈统一协作</p>
      </div>
      <div class="header-status">
        <strong><span class="status-dot"></span>数据已同步</strong><br>
        <span>{datetime.now().strftime('%Y年%m月%d日')}</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_ingest, tab_workflow, tab_dashboard, tab_events, tab_design = st.tabs(
    ["候选人建档", "招聘流程", "运营看板", "同步记录", "项目说明"]
)

with tab_ingest:
    section_heading(
        "Candidate intake",
        "候选人建档",
        "上传脱敏简历，确认结构化字段后同步至候选人信息表。",
    )
    left, right = st.columns([1, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### 简历文件")
            st.caption("支持 PDF、DOCX、TXT 和 Markdown")
            uploaded = st.file_uploader(
                "上传候选人简历",
                type=["pdf", "docx", "txt", "md"],
                accept_multiple_files=False,
                label_visibility="collapsed",
            )
            sample_clicked = st.button(
                "加载脱敏示例",
                icon=":material/description:",
                width="stretch",
            )
            if uploaded is not None:
                st.session_state["resume_source_name"] = uploaded.name
                st.session_state["resume_source_bytes"] = uploaded.getvalue()
            elif sample_clicked:
                st.session_state["resume_source_name"] = SAMPLE_RESUME.name
                st.session_state["resume_source_bytes"] = SAMPLE_RESUME.read_bytes()

            source_name = st.session_state.get("resume_source_name")
            source_bytes = st.session_state.get("resume_source_bytes")

            if source_bytes is None:
                st.info("尚未选择简历文件", icon=":material/upload_file:")
            else:
                try:
                    resume_text = extract_file_text(source_name, source_bytes)
                    st.text_area(
                        "文本预览",
                        resume_text,
                        height=220,
                        disabled=True,
                    )
                    if st.button(
                        "结构化抽取",
                        type="primary",
                        icon=":material/auto_awesome:",
                        width="stretch",
                    ):
                        with st.spinner("正在解析并校验字段..."):
                            extraction, engine = extract_candidate(resume_text, llm_config)
                        st.session_state["extracted_candidate"] = extraction.model_dump()
                        st.session_state["extraction_engine"] = engine
                        st.rerun()
                except Exception as exc:
                    st.error(f"简历解析失败：{exc}")

    with right:
        with st.container(border=True):
            st.markdown("#### 字段确认")
            extracted_data = st.session_state.get("extracted_candidate")
            if not extracted_data:
                st.info("等待结构化抽取结果", icon=":material/pending_actions:")
                st.caption("抽取完成后，字段将在此处进入人工确认。")
            else:
                extracted = CandidateExtraction.model_validate(extracted_data)
                engine_name = st.session_state.get("extraction_engine", "未知")
                st.caption(f"抽取引擎：{engine_name} · 置信度 {extracted.confidence:.0%}")
                with st.form("candidate_confirm_form", border=False):
                    c1, c2 = st.columns(2)
                    name = c1.text_input("姓名", extracted.name)
                    target_position = c2.text_input("应聘岗位", extracted.target_position)
                    phone = c1.text_input("手机号", extracted.phone)
                    email = c2.text_input("邮箱", extracted.email)
                    education = c1.text_input("学历", extracted.education)
                    school = c2.text_input("学校", extracted.school)
                    major = c1.text_input("专业", extracted.major)
                    source = c2.selectbox(
                        "招聘渠道",
                        ["Boss直聘", "校园招聘", "内推", "招聘网站", "其他"],
                        index=3,
                    )
                    skills = st.text_input("技能", "、".join(extracted.skills))
                    confirmed = st.form_submit_button(
                        "确认并同步建档",
                        type="primary",
                        icon=":material/person_add:",
                        width="stretch",
                    )
                if confirmed:
                    normalized_skills = [
                        item.strip()
                        for item in skills.replace(",", "、").split("、")
                        if item.strip()
                    ]
                    core_values = {
                        "name": name,
                        "phone": phone,
                        "email": email,
                        "target_position": target_position,
                        "education": education,
                        "school": school,
                        "major": major,
                    }
                    missing = [key for key, value in core_values.items() if not value]
                    blocking_missing = [
                        label
                        for label, value in {
                            "姓名": name,
                            "应聘岗位": target_position,
                            "手机号或邮箱": phone.strip() or email.strip(),
                        }.items()
                        if not value.strip()
                    ]
                    if blocking_missing:
                        st.error(f"请补充：{'、'.join(blocking_missing)}")
                    else:
                        record = CandidateExtraction(
                            **core_values,
                            years_experience=extracted.years_experience,
                            skills=normalized_skills,
                            source=source,
                            confidence=extracted.confidence,
                            missing_fields=missing,
                        )
                        try:
                            result = adapter.upsert_candidate(record)
                        except ValueError as exc:
                            st.error(str(exc), icon=":material/error:")
                        else:
                            st.success(
                                f"{result.message} · {result.record_id}",
                                icon=":material/check_circle:",
                            )
                            st.caption(
                                f"{result.adapter} · {format_timestamp(result.synced_at)}"
                            )

    section_heading(
        "Candidate records",
        "候选人信息表",
        "模拟腾讯文档当前快照，联系方式已脱敏。",
    )
    candidate_rows = store.list_candidates()
    candidate_frame = display_candidate_frame(candidate_rows)
    st.dataframe(candidate_frame, width="stretch", hide_index=True, height=320)
    st.download_button(
        "导出 CSV",
        data=candidate_frame.to_csv(index=False).encode("utf-8-sig"),
        file_name="candidate_records.csv",
        mime="text/csv",
        icon=":material/download:",
    )

with tab_workflow:
    section_heading(
        "Workflow",
        "招聘流程",
        "模拟企业微信群中的二次筛选、阶段推进与面试反馈。",
    )
    candidates = store.list_candidates()
    candidate_options = {
        f"{row['name']}｜{row['target_position']}｜{row['stage']}": row for row in candidates
    }
    selected_label = st.selectbox(
        "当前候选人",
        list(candidate_options),
        label_visibility="collapsed",
    )
    selected = candidate_options[selected_label]

    info_col, action_col = st.columns([1.05, 1], gap="large")
    with info_col:
        with st.container(border=True):
            st.markdown("#### 候选人概览")
            st.markdown(
                f"""
                <div class="candidate-profile">
                  <h3>{escape(selected['name'])}</h3>
                  <p>{escape(selected['target_position'])} · {escape(selected['school'])} · {escape(selected['education'])}</p>
                  <p>当前阶段：<span class="stage-label">{escape(selected['stage'])}</span></p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div class="candidate-stats">
                  <div class="candidate-stat"><span>当前版本</span><strong>v{selected['version']}</strong></div>
                  <div class="candidate-stat"><span>阶段进入</span><strong>{escape(format_timestamp(selected['stage_changed_at']))}</strong></div>
                  <div class="candidate-stat"><span>下次跟进</span><strong>{escape(format_timestamp(selected['next_followup_at']))}</strong></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(
                f"候选人编号 {selected['candidate_id']} · 最近同步 {format_timestamp(selected['updated_at'])}"
            )
    with action_col:
        with st.container(border=True):
            st.markdown("#### 阶段更新")
            with st.form("stage_update_form", border=False):
                target_stage = st.selectbox(
                    "目标阶段",
                    STAGES,
                    index=STAGES.index(selected["stage"]),
                )
                operator = st.text_input("操作人", "HR-Demo")
                follow_col1, follow_col2 = st.columns(2)
                follow_date = follow_col1.date_input(
                    "跟进日期",
                    datetime.now().date() + timedelta(days=1),
                )
                follow_time = follow_col2.time_input(
                    "跟进时间",
                    datetime.now().replace(
                        hour=10,
                        minute=0,
                        second=0,
                        microsecond=0,
                    ).time(),
                )
                stage_submitted = st.form_submit_button(
                    "同步阶段",
                    type="primary",
                    icon=":material/sync:",
                    width="stretch",
                )
            if stage_submitted:
                followup = datetime.combine(follow_date, follow_time).astimezone().isoformat(timespec="seconds")
                result = adapter.update_stage(
                    StageUpdate(
                        candidate_id=selected["candidate_id"],
                        to_stage=target_stage,
                        operator=operator,
                        next_followup_at=followup,
                    )
                )
                st.success(result.message, icon=":material/check_circle:")
                st.rerun()

    section_heading(
        "Interview feedback",
        "面试反馈",
        f"当前候选人：{selected['name']} · {selected['target_position']}",
    )
    interviews = store.list_interviews()
    feedback_col, history_col = st.columns([1, 1.15], gap="large")
    with feedback_col:
        with st.form("interview_form"):
            c1, c2 = st.columns(2)
            interviewer = c1.text_input("面试官", "业务面试官")
            result_value = c2.selectbox("结果", ["待反馈", "通过", "不通过", "待定"])
            scheduled_date = c1.date_input("面试日期", datetime.now().date())
            scheduled_time = c2.time_input(
                "面试时间",
                datetime.now().replace(minute=0, second=0, microsecond=0).time(),
            )
            score = st.slider("综合评分", min_value=0.0, max_value=5.0, value=3.5, step=0.5)
            feedback = st.text_area("面试评价", "", height=100)
            interview_submitted = st.form_submit_button(
                "同步面试记录",
                type="primary",
                icon=":material/rate_review:",
                width="stretch",
            )
        if interview_submitted:
            scheduled_at = datetime.combine(scheduled_date, scheduled_time).astimezone().isoformat(timespec="seconds")
            sync_result = adapter.save_interview(
                InterviewInput(
                    candidate_id=selected["candidate_id"],
                    interviewer=interviewer,
                    scheduled_at=scheduled_at,
                    result=result_value,
                    score=score,
                    feedback=feedback,
                )
            )
            st.success(sync_result.message, icon=":material/check_circle:")

    with history_col:
        st.markdown("#### 面试记录")
        selected_interviews = [
            row for row in interviews if row["candidate_id"] == selected["candidate_id"]
        ]
        if selected_interviews:
            interview_frame = pd.DataFrame(selected_interviews)[
                ["scheduled_at", "interviewer", "result", "score", "feedback_at"]
            ]
            interview_frame.columns = ["面试时间", "面试官", "结果", "评分", "反馈时间"]
            st.dataframe(interview_frame, width="stretch", hide_index=True, height=280)
        else:
            st.info("暂无面试记录", icon=":material/event_busy:")

with tab_dashboard:
    candidates = store.list_candidates()
    interviews = store.list_interviews()
    metrics = calculate_metrics(candidates, interviews)
    section_heading(
        "Operations overview",
        "运营看板",
        "招聘进度、流程效率与超时任务的实时快照。",
    )
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("候选人总数", metrics["total_candidates"])
    m2.metric("待二次筛选", metrics["pending_screening"])
    m3.metric("面试推进中", metrics["active_interviews"])
    m4.metric("已发Offer", metrics["offers"])
    m5.metric("超时待办", metrics["overdue_count"])

    section_heading("Pipeline", "招聘漏斗与岗位分布")
    chart_left, chart_right = st.columns([1.2, 1], gap="large")
    with chart_left:
        stage_data = pd.DataFrame(
            {
                "招聘阶段": list(metrics["stage_counts"].keys()),
                "人数": list(metrics["stage_counts"].values()),
            }
        )
        funnel = px.funnel(
            stage_data,
            x="人数",
            y="招聘阶段",
            color="招聘阶段",
            color_discrete_sequence=["#087e8b", "#356b94", "#5f7e61", "#a66a19", "#6d6188", "#a34b4b"],
        )
        funnel.update_layout(
            showlegend=False,
            margin=dict(l=10, r=10, t=20, b=10),
            height=320,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(funnel, width="stretch")
    with chart_right:
        position_data = pd.DataFrame(
            {
                "岗位": list(metrics["position_counts"].keys()),
                "人数": list(metrics["position_counts"].values()),
            }
        ).sort_values("人数", ascending=True)
        position_chart = px.bar(
            position_data,
            x="人数",
            y="岗位",
            orientation="h",
            color="人数",
            color_continuous_scale=["#d9ecee", "#087e8b"],
        )
        position_chart.update_layout(
            coloraxis_showscale=False,
            margin=dict(l=10, r=10, t=20, b=10),
            height=320,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(position_chart, width="stretch")

    section_heading("Efficiency", "流程效率")
    k1, k2, k3 = st.columns(3)
    k1.metric("进入面试比例", f"{metrics['interview_rate']}%")
    k2.metric("面试通过率", f"{metrics['interview_pass_rate']}%")
    k3.metric("平均阶段停留", f"{metrics['average_stage_hours']}小时")

    action_left, action_right = st.columns([1.45, 1], gap="large")
    with action_left:
        section_heading("Attention", "超时待办")
        overdue_rows = metrics["overdue_candidates"]
        if overdue_rows:
            overdue_frame = display_candidate_frame(overdue_rows)
            compact_columns = [
                "候选人编号",
                "姓名",
                "应聘岗位",
                "当前阶段",
                "下次跟进时间",
            ]
            st.dataframe(
                overdue_frame[compact_columns],
                width="stretch",
                hide_index=True,
                height=230,
            )
        else:
            st.success("当前没有超时任务", icon=":material/task_alt:")

    with action_right:
        section_heading("Daily brief", "AI 招聘日报")
        if st.button(
            "生成今日分析",
            type="primary",
            icon=":material/analytics:",
            width="stretch",
        ):
            try:
                with st.spinner("正在分析招聘指标..."):
                    brief = generate_ai_brief(metrics, llm_config)
                st.session_state["daily_brief"] = brief
            except Exception as exc:
                st.error(f"日报生成失败：{exc}")
        st.info(
            st.session_state.get(
                "daily_brief",
                "今日分析尚未生成。",
            ),
            icon=":material/summarize:",
        )

with tab_events:
    section_heading(
        "Audit trail",
        "同步记录",
        "建档、阶段变化和面试反馈的不可变事件流水。",
    )
    events = store.list_events()
    if events:
        event_frame = pd.DataFrame(events)[
            [
                "event_id",
                "candidate_id",
                "name",
                "event_type",
                "from_stage",
                "to_stage",
                "operator",
                "event_time",
                "sync_target",
                "sync_status",
                "synced_at",
            ]
        ]
        event_frame.columns = [
            "事件编号",
            "候选人编号",
            "姓名",
            "事件类型",
            "原阶段",
            "新阶段",
            "操作人",
            "业务发生时间",
            "同步目标",
            "同步状态",
            "同步完成时间",
        ]
        event_frame["事件类型"] = event_frame["事件类型"].map(
            {
                "candidate_created": "候选人建档",
                "candidate_updated": "候选人资料更新",
                "stage_changed": "招聘阶段更新",
                "followup_updated": "跟进时间更新",
                "interview_saved": "面试反馈同步",
            }
        ).fillna(event_frame["事件类型"])
        event_frame["同步状态"] = event_frame["同步状态"].replace(
            {"success": "成功", "failed": "失败", "pending": "等待同步"}
        )
        event_frame["同步目标"] = event_frame["同步目标"].replace(
            {"Mock Tencent Docs": "脱敏模拟腾讯文档"}
        )
        event_frame["业务发生时间"] = event_frame["业务发生时间"].map(
            format_timestamp
        )
        event_frame["同步完成时间"] = event_frame["同步完成时间"].map(
            format_timestamp
        )
        filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])
        event_type_options = ["全部"] + sorted(event_frame["事件类型"].dropna().unique().tolist())
        status_options = ["全部"] + sorted(event_frame["同步状态"].dropna().unique().tolist())
        selected_event_type = filter_col1.selectbox("事件类型", event_type_options)
        selected_status = filter_col2.selectbox("同步状态", status_options)
        filter_col3.metric(
            "最近同步",
            format_timestamp(events[0]["synced_at"]),
        )
        filtered_events = event_frame.copy()
        if selected_event_type != "全部":
            filtered_events = filtered_events[
                filtered_events["事件类型"] == selected_event_type
            ]
        if selected_status != "全部":
            filtered_events = filtered_events[
                filtered_events["同步状态"] == selected_status
            ]
        st.dataframe(filtered_events, width="stretch", hide_index=True, height=420)
        st.download_button(
            "导出当前记录",
            data=filtered_events.to_csv(index=False).encode("utf-8-sig"),
            file_name="recruitment_sync_events.csv",
            mime="text/csv",
            icon=":material/download:",
        )
    else:
        st.info("暂无同步事件", icon=":material/history:")

with tab_design:
    section_heading(
        "Solution design",
        "项目说明",
        "最小成本完成招聘数据自动记录、实时同步与运营分析。",
    )
    design_left, design_right = st.columns([1.2, 1], gap="large")
    with design_left:
        st.markdown("#### 业务链路")
        st.code(
            """简历文件
  → 文档解析与结构化抽取
  → 人工确认与候选人去重
  → 腾讯文档适配层
  → 状态事件与面试反馈
  → 实时看板与招聘日报""",
            language=None,
        )
        st.markdown("#### 更新机制")
        st.write(
            "当前快照保存候选人最新状态，事件流水追加每次业务变化。"
            "时间节点、同步结果和版本号共同支持追踪、超时提醒与失败重试。"
        )
    with design_right:
        st.markdown("#### AI 与程序边界")
        st.write(
            "大模型负责非结构化简历理解和日报表达；候选人编号、去重、"
            "阶段更新、时间记录、同步和指标计算由确定性程序完成。"
        )
        st.markdown("#### 接口与隐私")
        st.write(
            "当前使用招聘方认可的脱敏模拟接口。获得企业权限后仅替换适配器，"
            "界面和业务流程无需改动。公开环境不保存真实简历与模型密钥，"
            "AI 不直接作出录用决定。"
        )
