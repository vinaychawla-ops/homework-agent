"""Tests for the Google ADK agent wiring (structure only, no live LLM calls)."""

from google.adk.agents import LlmAgent, SequentialAgent

from homework_agent import agent as agent_module
from homework_agent.agent import (
    grade_tool,
    grading_agent,
    intake_agent,
    intake_tool,
    report_email_tool,
    reporting_agent,
    root_agent,
)

from conftest import sample_path


def _tool_names(llm_agent: LlmAgent):
    return {t.name for t in llm_agent.tools}


def test_root_agent_is_sequential_with_three_stages():
    assert isinstance(root_agent, SequentialAgent)
    assert root_agent.name == "homework_grader"
    assert [a.name for a in root_agent.sub_agents] == [
        "intake_agent",
        "grading_agent",
        "reporting_agent",
    ]


def test_each_stage_has_its_tool():
    assert "intake_tool" in _tool_names(intake_agent)
    assert "grade_tool" in _tool_names(grading_agent)
    assert "report_email_tool" in _tool_names(reporting_agent)


def test_intake_tool_parses_text():
    answers = intake_tool(
        assignment_id="math-fractions-01",
        student_name="Alex",
        student_email="alex@x.edu",
        submission_format="text",
        content="Q1: 3/4\nQ2: 4",
    )
    assert answers == {"Q1": "3/4", "Q2": "4"}


def test_intake_tool_rejects_unknown_assignment():
    import pytest

    with pytest.raises(KeyError):
        intake_tool("nope", "A", "a@x.edu", "text", "Q1: 1")


def test_grade_tool_returns_verdicts():
    result = grade_tool("math-fractions-01", {"Q1": "3/4", "Q2": "5"})
    assert result["total_earned"] == 1.0
    by_id = {e["question_id"]: e for e in result["evaluations"]}
    assert by_id["Q1"]["is_correct"] is True
    assert by_id["Q2"]["is_correct"] is False
    assert by_id["Q2"]["explanation"] != ""


def test_report_email_tool_sends_two_mock_emails():
    grade_result = grade_tool("sci-water-cycle-01", {"Q1": "b", "Q3": "condensation"})
    out = report_email_tool(
        assignment_id="sci-water-cycle-01",
        student_name="Priya",
        student_email="priya@x.edu",
        grade_result=grade_result,
    )
    assert "student_email_subject" in out and "teacher_email_subject" in out
    assert out["score"].startswith("2")


def test_agent_module_exports_root_agent():
    assert agent_module.root_agent is root_agent
