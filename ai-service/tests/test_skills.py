from app.skills.registry import SkillRegistry


def test_builtin_skills_loaded():
    registry = SkillRegistry()
    names = registry.names()
    assert "summarize" in names
    assert "translate" in names

    detail = registry.detail("summarize")
    assert detail["title"] == "结构化摘要"
    assert "一句话结论" in detail["content"]
    assert detail["references"], "summarize should expose reference documents"

    reference = registry.reference("summarize", detail["references"][0]["file"])
    assert "示例" in reference["content"]
