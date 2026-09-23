"""Документы организатора: Положение о внутреннем аудите, ред. № 8 (до) → ред. № 9 (после).

Проверяются выводы, упомянутые в README (раздел «Как проверить решение»).
"""
from pathlib import Path

import pytest

from app.analysis.compare import Comparator
from app.analysis.structure import build_structure
from app.analysis.text import Similarity
from app.parsing.parse import parse_file
from app.services.settings_store import ANALYSIS_DEFAULTS

ORG = Path(__file__).resolve().parents[2] / "samples" / "organizer"


@pytest.fixture(scope="module")
def result():
    docs = {}
    for i, side in enumerate(("before", "after"), start=1):
        f = next((ORG / side).glob("*.docx"))
        docs[side] = [{"id": i, "filename": f.name, "title": f.stem, "parsed": parse_file(f)}]
    kinds = ANALYSIS_DEFAULTS["function_kinds"]
    before = build_structure("before", docs["before"], kinds)
    after = build_structure("after", docs["after"], kinds)
    return Comparator(before, after, ANALYSIS_DEFAULTS, Similarity(), {1: "ред. 8", 2: "ред. 9"}).run()


def test_units(result):
    created = {a["short"] for u in result["units"] if u["status"] == "created" for a in u["after"]}
    assert {"ДИТААД", "ДОА"} <= created
    direction = [u for u in result["units"] if u["before"] and u["before"]["name"] == "Направление внутреннего аудита"]
    assert direction and direction[0]["status"] in ("split", "reorganized", "abolished")
    preserved = {u["before"]["short"] for u in result["units"] if u["status"] == "preserved" and u["before"]}
    assert {"БВА", "ДНМ", "ДККМ"} <= preserved


def test_lost_rights(result):
    lost_refs = {f["evidence"][0]["ref"] for f in result["findings"] if f["type"] == "loss"}
    assert {"5.6.2", "5.6.3", "5.7.2"} <= lost_refs


def test_duplication_general_vs_specific(result):
    dups = [f for f in result["findings"] if f["type"] == "duplication"]
    assert dups and all("общей и частной" in f["title"] for f in dups)


def test_conflicts_and_resolved_dual_subordination(result):
    declared = [f for f in result["findings"] if f.get("subtype") == "declared"]
    assert declared and any(e["ref"].startswith("4.4") for e in declared[0]["evidence"])
    resolved = [f["title"] for f in result["findings"] if f.get("subtype") == "dual_subordination_resolved"]
    assert any("Директор проектов ДККМ" in t for t in resolved)
    assert any(f.get("subtype") == "sod" for f in result["findings"])
