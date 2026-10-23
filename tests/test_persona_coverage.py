from __future__ import annotations

import datetime as dt

from twin.persona.coverage import CHECKED_LABEL, LEVEL_LABELS, coverage_report, facet_coverage, report_markdown
from twin.persona.dimensions import FACETS
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, ReviewStatus, SourceKind

D = dt.date
AS_OF = D(2026, 10, 3)
ALL = frozenset(f.facet_id for f in FACETS if not f.facet_id.startswith("9."))


def ev(source: str, kind: SourceKind, date: dt.date | None) -> PEvidence:
    klass = (
        EvidenceClass.SELF_REPORT
        if kind in (SourceKind.QUESTIONNAIRE, SourceKind.INTERVIEW)
        else EvidenceClass.BEHAVIOR
    )
    return PEvidence(
        expression_id=f"{source}#{date}", source_id=source, source_kind=kind, evidence_class=klass, date=date, quote="q"
    )


def item(facet: str, *evidence: PEvidence, conflict: str = "") -> PersonaItem:
    return PersonaItem(
        item_id=f"pi_{facet}_{len(evidence)}", facet_id=facet, statement="s", evidence=list(evidence), conflict=conflict
    )


def test_levels_follow_occasions_source_variety_conflicts_and_probes() -> None:
    assert facet_coverage("3.1", [], AS_OF, True).level == 0
    one = facet_coverage("3.1", [item("3.1", ev("q", SourceKind.QUESTIONNAIRE, D(2026, 9, 1)))], AS_OF, True)
    assert (one.level, one.sufficiency, one.behavior) == (1, 0.167, False)
    rich = [
        item(
            "3.1",
            ev("q", SourceKind.QUESTIONNAIRE, D(2026, 9, 1)),
            ev("c", SourceKind.CHAT, D(2026, 9, 2)),
            ev("c", SourceKind.CHAT, D(2026, 9, 2)),  # the same occasion counts once
            ev("c", SourceKind.CHAT, D(2026, 9, 3)),
        )
    ]
    full = facet_coverage("3.1", rich, AS_OF, True)
    assert (full.occasions, full.sufficiency, full.level, full.checked) == (3, 1.0, 3, False)
    assert full.by_kind == {SourceKind.CHAT: 2, SourceKind.QUESTIONNAIRE: 1}
    assert facet_coverage("3.1", rich, AS_OF, True, [1.0, 0.5]).accuracy is None  # too few probes
    # Right answers are a mark beside "a good deal", not a level above it.
    checked = facet_coverage("3.1", rich, AS_OF, True, [1.0, 0.5, 1.0])
    assert (checked.level, checked.checked) == (3, True)
    wrong = facet_coverage("3.1", rich, AS_OF, True, [0.5, 0.5, 0.5])
    assert (wrong.level, wrong.checked) == (3, False)
    capped = facet_coverage("3.1", [rich[0].model_copy(update={"conflict": "自述看数据，行为凭直觉"})], AS_OF, True)
    assert (capped.sufficiency, capped.level, capped.conflicts) == (0.5, 2, 1)


def test_the_four_levels_say_how_much_the_twin_knows() -> None:
    chat = [ev("c", SourceKind.CHAT, D(2026, 9, 2)), ev("c", SourceKind.CHAT, D(2026, 9, 3))]
    # 还不了解: nothing at all.
    assert facet_coverage("3.1", [], AS_OF, True).level == 0
    # 提到过: one occasion, however well it is put.
    assert facet_coverage("3.1", [item("3.1", chat[0])], AS_OF, True).level == 1
    # 提到过: many occasions, but only what others said of the person, never their own words or their confirmation.
    others = [e.model_copy(update={"own_words": False}) for e in [*chat, ev("d", SourceKind.CHAT, D(2026, 9, 4))]]
    said = facet_coverage("3.1", [item("3.1", *others)], AS_OF, True)
    assert (said.occasions, said.trusted, said.level) == (3, False, 1)
    # ... until the person confirms what was said: then it is known as far as the evidence goes.
    confirmed = item("3.1", *others).model_copy(update={"review": ReviewStatus.CONFIRMED})
    assert facet_coverage("3.1", [confirmed], AS_OF, True).level == 3
    # 了解一些: two occasions in the person's words, not yet enough for a good deal (0.58 of 0.7).
    some = facet_coverage("3.1", [item("3.1", *chat)], AS_OF, True)
    assert (some.occasions, some.sufficiency, some.level, some.checked) == (2, 0.583, 2, False)
    # 了解较多: sufficiency reaches 0.7 on the person's own words.
    more = facet_coverage("3.1", [item("3.1", *chat, ev("q", SourceKind.QUESTIONNAIRE, D(2026, 9, 1)))], AS_OF, True)
    assert (more.occasions, more.sufficiency, more.level) == (3, 1.0, 3)
    assert (
        LEVEL_LABELS == {0: "还不了解", 1: "提到过", 2: "了解一些", 3: "了解较多"} and CHECKED_LABEL == "回答经过检查"
    )


def test_fast_dimension_counts_only_recent_evidence() -> None:
    old = item("8.1", ev("c", SourceKind.CHAT, D(2026, 5, 1)))
    assert facet_coverage("8.1", [old], AS_OF, True).level == 0
    assert facet_coverage("8.1", [old], D(2026, 6, 1), True).level == 1


def test_report_summarises_dimensions_matrix_and_suggestions() -> None:
    items = [
        item("2.1", ev("q", SourceKind.QUESTIONNAIRE, D(2026, 9, 1))),
        item("6.1", ev("c", SourceKind.CHAT, D(2026, 9, 2)), conflict="说法与做法不一"),
    ]
    report = coverage_report(items, ALL, AS_OF)
    dims = {d.dimension_id: d for d in report.dimensions}
    assert dims["D2"].covered == 0.25 and dims["D2"].sufficient == 0.0 and dims["D6"].conflicts == 1
    assert dims["D9"].consented == 0 and dims["D9"].covered is None  # nothing consented, nothing to measure
    first = report.suggestions[0]
    assert first.facet_id == "6.1" and first.sources == [SourceKind.INTERVIEW]  # conflicts first
    q = next(s for s in report.suggestions if s.facet_id == "2.1")
    assert q.reason == "只在一个场合提到过" and SourceKind.QUESTIONNAIRE not in q.sources
    assert not any(s.facet_id.startswith("9.") for s in report.suggestions)
    md = report_markdown(report)
    assert "| D2 看重什么 | 4/4 | 25% | 0% | 0% | 0 |" in md
    assert "| 6.1 用词与口头禅（矛盾） | 提到过 | 0.42 |" in md and "| 9.1 兴趣爱好 | 未授权 |" in md
