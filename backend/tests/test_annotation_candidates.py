import pytest
from backend.app.annotation_candidates import candidate_clauses
from backend.app.benchmark_models import ReferenceAnnotation, ReferenceCriterion, validate_reference
from backend.app.annotation_api import source_for


def test_unicode_wrapping_headers_and_exact_quotes():
    text = 'Inclusion Criteria:\r\n* ECOG 🧬 ≤ 1\r\n  wrapped qualifier\r\n* Age ≥ 18\r\nExclusion Criteria:\r\n* Prior therapy'
    result = candidate_clauses(text)
    assert len(result) == 3
    assert result[0]['original']['text'] == '* ECOG 🧬 ≤ 1\r\n  wrapped qualifier'
    assert result[0]['suggested_polarity'] == 'inclusion'
    assert result[2]['suggested_polarity'] == 'exclusion'
    for item in result:
        q = item['original']
        assert text[q['span']['start']:q['span']['end']] == q['text']


def test_inline_nested_numbered_and_uncertain_boundaries():
    text = 'Inclusion Criteria:\n* First * Second\n* Parent:\n  * Child\n  * Except this\n* 1) A or 2) B\nExclusion Criteria:\nUnformatted text\ncontinued text'
    items = candidate_clauses(text)
    assert len(items) == 5
    assert items[0]['original']['text'] == '* First'
    assert items[1]['original']['text'] == '* Second'
    assert 'Inline bullets: check boundaries' in items[1]['warnings']
    assert '* Child\n  * Except this' in items[2]['original']['text']
    assert 'Nested clauses retained together' in items[2]['warnings']
    assert 'Numbered subclauses retained together' in items[3]['warnings']
    assert items[4]['warnings']


def test_context_and_escaped_bullets_are_preserved():
    text = 'Inclusion Criteria:\nCohort A:\n\\- Condition\n* Exception applies unless otherwise stated'
    items = candidate_clauses(text)
    assert len(items) == 2
    assert items[0]['context']['text'] == 'Cohort A:'
    assert items[0]['original']['text'] == '\\- Condition'


@pytest.mark.parametrize('nct', ['NCT01770353', 'NCT02648477'])
def test_real_candidates_are_exact_nonoverlapping_drafts(nct):
    source = source_for(nct)
    items = candidate_clauses(source.text)
    ecog = [item for item in items if 'ECOG' in item['original']['text']]
    assert len(ecog) == 1
    assert len(ecog[0]['original']['text']) < 300
    reference = ReferenceAnnotation(nct_id=nct, snapshot_sha256=source.sha256,
        criteria=[ReferenceCriterion(reference_id=item['id'], original=item['original']) for item in items])
    validate_reference(reference, source.text)
    assert reference.inventory_review.status == 'unreviewed'
    assert all(item.boundary_review.status == 'unreviewed' for item in reference.criteria)


def test_nested_unbulleted_subheading_stays_with_parent_and_unicode_bullets_split():
    text = 'Inclusion Criteria:\n• First • Second\n* Parent\n  Nested heading:\n  * Child\n* Next'
    items = candidate_clauses(text)
    assert len(items) == 4
    assert items[0]['original']['text'] == '• First'
    assert items[1]['original']['text'] == '• Second'
    assert 'Nested heading:\n  * Child' in items[2]['original']['text']
