import json

from src.extractor import brief_metrics_payload, demo_extract


def test_demo_extractor_returns_structured_candidate():
    text = """
姓名：李明
手机号：13912345678
邮箱：liming@example.com
求职意向：AI应用实习生
毕业院校：武汉大学
学历：硕士
专业：计算数学
技能：Python、SQL、RAG、LangGraph
"""
    result = demo_extract(text)
    assert result.name == "李明"
    assert result.phone == "13912345678"
    assert result.target_position == "AI应用实习生"
    assert result.school == "武汉大学"
    assert "Python" in result.skills
    assert result.confidence > 0.8


def test_brief_metrics_payload_excludes_candidate_level_data():
    metrics = {
        "total_candidates": 1,
        "overdue_count": 1,
        "stage_counts": {"待面试": 1},
        "overdue_candidates": [
            {"name": "张三", "phone": "13900000000", "email": "private@example.com"}
        ],
    }

    payload = brief_metrics_payload(metrics)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "overdue_candidates" not in payload
    assert "张三" not in serialized
    assert "13900000000" not in serialized
