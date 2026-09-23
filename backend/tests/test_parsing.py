from app.analysis.structure import to_nominative
from app.parsing.parse import extract_abbreviations
from app.parsing.segment import RawPara, segment


def test_numbering_letters_and_actor():
    paras = [
        RawPara("ПОЛОЖЕНИЕ", style="Title"),
        RawPara("5. Права и обязанности", style="Heading 1"),
        RawPara("5.4. Директор департамента непрерывного мониторинга:"),
        RawPara("5.4.1. организует работу ДНМ;"),
        RawPara("5.4.2. взаимодействует с субъектами СВК в части:"),
        RawPara("а. использования результатов работы;"),
        RawPara("5.6. Директоры департаментов обязаны обеспечить выполнение задач, имеют право:"),
        RawPara("5.6.1. вести переписку с Руководителями Общества;"),
    ]
    clauses, _ = segment(paras)
    by_ref = {c.ref: c for c in clauses}
    assert by_ref["5.4.1"].actor.startswith("Директор департамента непрерывного")
    assert by_ref["5.4.1"].kind == "duty"
    assert by_ref["5.4.2.а"].ref_display == "пп. «а» п. 5.4.2"
    assert by_ref["5.6.1"].kind == "right"
    assert by_ref["5.6.1"].actor == "Директоры департаментов"


def test_embedded_clause_split_and_heading():
    paras = [RawPara("3. Структура", style="Heading 1"),
             RawPara("3.9. Рабочие места работников могут располагаться в филиалах. 3.10.Работники могут работать удаленно.")]
    clauses, _ = segment(paras)
    refs = [c.ref for c in clauses]
    assert "3.9" in refs and "3.10" in refs


def test_restarted_autonumber_list_stays_in_section():
    paras = [RawPara("3. Функции", style="Heading 1"), RawPara("Департамент осуществляет следующие функции:")]
    paras += [RawPara(f"функция номер {i};", label=f"{i}.") for i in range(1, 5)]
    paras += [RawPara("4. Права", style="Heading 1"), RawPara("4.1. запрашивать информацию;")]
    clauses, _ = segment(paras)
    fn = [c for c in clauses if c.text.startswith("функция")]
    assert len(fn) == 4 and all(c.kind == "function" and c.section.startswith("3.") for c in fn)
    assert next(c for c in clauses if c.ref == "4.1").kind == "right"


def test_abbreviations():
    ab = extract_abbreviations([
        "работников Блока внутреннего аудита Общества (далее - БВА).",
        "Оценка эффективности системы управления рисками (далее - СУР):",
        "Юридический департамент (далее – ЮД) является подразделением",
    ])
    assert ab["БВА"]["full"] == "Блок внутреннего аудита" and ab["БВА"]["is_unit"]
    assert ab["СУР"]["full"] == "системы управления рисками" and not ab["СУР"]["is_unit"]
    assert ab["ЮД"]["is_unit"]


def test_nominative():
    assert to_nominative("Юридическом департаменте") == "Юридический департамент"
    assert to_nominative("департамента непрерывного мониторинга") == "Департамент непрерывного мониторинга"
    assert to_nominative("Кадровой службе") == "Кадровая служба"


def test_compare_departments_compat():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("structure_matcher", Path(__file__).resolve().parents[2] / "structure_matcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.compare_departments(
        {"name": "Департамент закупок", "functions": ["организация и проведение закупок товаров и услуг",
                                                     "ведение реестра договоров о закупках"]},
        {"name": "Департамент закупок", "functions": ["организация и проведение закупок товаров, работ и услуг",
                                                     "ведение реестра договоров о закупках",
                                                     "мониторинг исполнения договоров поставщиками"]},
    )
    assert res["status"] == "deviations_found"
    assert any(d["type"] == "missing_function" and "мониторинг" in d["message"] for d in res["deviations"])
    assert 0.5 < res["coverage"] < 1
