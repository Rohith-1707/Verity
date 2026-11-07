from datetime import date
from app import engine as E
from app.retrieval import KeywordRetriever

TODAY = date(2026, 11, 7)


def retr():
    r = KeywordRetriever()
    r.index("o", "w", "Warranty", "1", "approved", "2025-01-01", None, "All Aurora devices include a 3 year limited warranty. Warranty does not cover accidental damage.")
    r.index("o", "s", "Specs", "1", "approved", "2025-01-01", None, "The Aurora X1 battery lasts up to 12 hours. The Aurora X1 weighs 1.2 kg.")
    return r


def cls(claim, r=None, today=TODAY):
    r = r or retr()
    return E.classify_claim(claim, r.search("o", claim, "approved"), r.search("o", claim, "superseded"), today, r.min_score, r.strong)


def test_claim_extraction_skips_plain_sentences():
    cl = E.extract_claims("Welcome to our store. Our warranty covers 3 years. Free shipping on every order!")
    assert len(cl) == 2 and "Welcome" not in cl[0]


def test_number_words_equal_digits():
    assert E.numbers("a three year warranty") == ["3"]


def test_verified_claim_has_traceable_evidence():
    f = cls("Our warranty covers 3 years.")
    assert f["type"] == "verified" and f["evidence"]["title"] == "Warranty" and f["evidence"]["version"] == "1"
    assert "no effective or review date" not in f["why"]


def test_contradictory_claim_suggests_approved_wording():
    f = cls("Battery lasts up to 20 hours.")
    assert f["type"] == "contradictory" and "12 hours" in f["fix"]


def test_unsupported_claim_never_gets_invented_evidence():
    f = cls("Free shipping on every order!")
    assert f["type"] == "unsupported" and f["evidence"] is None


def test_expired_source_gives_freshness_warning():
    r = KeywordRetriever()
    r.index("o", "w", "Warranty", "1", "approved", "2024-01-01", "2025-06-01", "All devices include a 3 year limited warranty.")
    assert cls("Our warranty covers 3 years.", r)["type"] == "outdated"


def test_superseded_only_match_is_outdated():
    r = retr()
    r.set_status("o", "w", "superseded")
    f = cls("Our warranty covers 3 years.", r)
    assert f["type"] == "outdated" and "superseded" in f["why"]


def test_missing_dates_are_shown_as_uncertainty():
    r = KeywordRetriever()
    r.index("o", "w", "Warranty", "1", "approved", None, None, "All devices include a 3 year limited warranty.")
    assert "Uncertainty" in cls("Our warranty covers 3 years.", r)["why"]


def test_negation_mismatch_goes_to_human_review():
    assert cls("Warranty covers accidental damage.")["type"] == "review"


def test_guidelines_mandatory_rules_and_context():
    g = E.check_guidelines("The best laptop!", {"platform": "Website", "tone": "Formal"}, [{"value": "best", "reason": "needs proof"}], [{"value": "Terms apply", "platform": "Any"}])
    assert {f["type"] for f in g} == {"guideline", "required", "tone"}
    g2 = E.check_guidelines("Terms apply", {"platform": "Instagram", "tone": "Playful"}, [], [{"value": "Terms apply", "platform": "Website"}])
    assert g2 == []


def test_risk_levels_and_explanation():
    assert E.assess_risk([{"type": "contradictory"}])["level"] == "High"
    assert E.assess_risk([{"type": "unsupported"}, {"type": "tone"}])["level"] == "Medium"
    assert E.assess_risk([{"type": "verified"}])["level"] == "Low"
    assert "uncertain" in E.assess_risk([])["why"]
    assert E.assess_risk([{"type": "unsupported"}], {"unsupported": 40})["level"] == "High"


def test_diff_and_issue_tracking():
    ops = E.diff_words("warranty covers 3 years", "warranty covers 2 years")
    assert {"op": "removed", "text": "3"} in ops and {"op": "added", "text": "2"} in ops
    prev = [{"type": "unsupported", "claim": "A"}, {"type": "unsupported", "claim": "B"}]
    cur = [{"type": "unsupported", "claim": "B"}, {"type": "contradictory", "claim": "C"}]
    assert E.compare_versions(prev, cur) == {"resolved": ["A"], "unresolved": ["B"], "new": ["C"]}


def test_change_impact_finds_stale_warranty_text():
    hits = E.find_impacts("All devices include a 3 year limited warranty.", "All devices include a 2 year limited warranty.",
                          [{"id": "brochure", "text": "Welcome. Our warranty covers 3 years."}, {"id": "poster", "text": "Our warranty covers 2 years."}])
    assert [h["content_id"] for h in hits] == ["brochure"] and hits[0]["location"] == "sentence 2 of 2"
