"""Tests for citation validator reviewer."""
from __future__ import annotations

import pytest

from src.agent.reviewers.citation_validator import validate_citations, _validate_single_analysis


def _make_state(*, analyses=None, report="", claim_map=None):
    return {
        "topic": "concept drift",
        "planning": {"research_questions": [], "search_queries": [], "scope": {},
                      "budget": {}, "query_routes": {}, "_academic_queries": [], "_web_queries": []},
        "research": {"papers": [], "web_sources": [], "analyses": analyses or [],
                      "findings": [], "synthesis": "", "indexed_paper_ids": [],
                      "indexed_web_ids": [], "memory_summary": "",
                      "experiment_plan": {}, "experiment_results": {}},
        "evidence": {"gaps": [], "claim_evidence_map": claim_map or [], "evidence_audit_log": []},
        "review": {"retrieval_review": {}, "citation_validation": {},
                    "experiment_review": {}, "claim_verdicts": [], "reviewer_log": []},
        "report": {"report": report, "report_critic": {}, "repair_attempted": False,
                    "acceptance_metrics": {}},
        "_cfg": {},
    }


class TestSingleAnalysisValidation:
    def test_valid_arxiv_entry(self):
        a = {
            "uid": "arxiv:2401.00001",
            "title": "Test Paper",
            "year": 2024,
            "authors": ["Alice", "Bob"],
            "url": "https://arxiv.org/abs/2401.00001",
            "source": "arxiv",
        }
        entry = _validate_single_analysis(a)
        assert entry["doi_valid"] is True
        assert entry["year_valid"] is True
        assert entry["author_valid"] is True
        assert entry["url_reachable"] is True
        assert len(entry["issues"]) == 0

    def test_missing_url_flagged(self):
        a = {"uid": "", "title": "No URL", "year": 2024, "source": "web"}
        entry = _validate_single_analysis(a)
        assert entry["url_reachable"] is False
        assert any("missing_url" in i for i in entry["issues"])

    def test_invalid_year_flagged(self):
        a = {"uid": "arxiv:2401.00001", "year": 1800, "url": "https://arxiv.org/abs/2401.00001"}
        entry = _validate_single_analysis(a)
        assert entry["year_valid"] is False

    def test_malformed_doi(self):
        a = {"uid": "doi:invalid", "url": "https://doi.org/invalid", "year": 2024}
        entry = _validate_single_analysis(a)
        assert entry["doi_valid"] is False


class TestCitationValidator:
    def test_valid_citations_pass(self):
        analyses = [
            {
                "uid": "arxiv:2401.00001",
                "title": "Paper A",
                "year": 2024,
                "authors": ["Alice"],
                "url": "https://arxiv.org/abs/2401.00001",
                "source": "arxiv",
            },
            {
                "uid": "doi:10.1234/test",
                "title": "Paper B",
                "year": 2023,
                "authors": ["Bob"],
                "url": "https://doi.org/10.1234/test",
                "source": "openalex",
                "venue": "NeurIPS",
            },
        ]
        state = _make_state(analyses=analyses)
        result = validate_citations(state)
        review = result.get("review", {}).get("citation_validation", {})
        assert review["verdict"]["status"] == "pass"

    def test_phantom_refs_detected(self):
        analyses = [
            {
                "uid": "arxiv:2401.00001",
                "title": "Paper A",
                "url": "https://arxiv.org/abs/2401.00001",
                "year": 2024,
                "authors": ["Alice"],
                "source": "arxiv",
            },
        ]
        report = "## References\n- [Fake Paper](https://example.com/fake-paper)\n"
        state = _make_state(analyses=analyses, report=report)
        result = validate_citations(state)
        review = result.get("review", {}).get("citation_validation", {})
        assert review["verdict"]["status"] in ("warn", "fail")
        issues = review["verdict"]["issues"]
        assert any("phantom" in i for i in issues)
