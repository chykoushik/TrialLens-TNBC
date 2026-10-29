import csv
import hashlib
import math
from pathlib import Path

import pytest

from scripts import public_release

ROOT = Path(__file__).resolve().parents[1]
HASHES = {
    'results/recomb/20261026-compiled-review-v2/benchmark_summary.csv': '42c582c6bdf4e3ca59cdcaf3919fc39a99d2534d136cdf0a2ffa1b8a0e18197d',
    'results/recomb/20261026-compiled-review-v2/paired_effects.csv': '080055b057b0a02f2c062df2f106de91e2d2f06143f0746297980e180f60fa18',
    'results/recomb/20261026-certified-review-v1/comparison.csv': 'e8c9f58d4e1de31dde68802b57e8cd3066fda2d0813b201e10452f348c05ceed',
    'results/recomb/20261026-certified-review-v1/paired_effects.csv': '23bb3b90295a80efc49e9422a4cd3514c83dee8293db3e1bd24e92c1a2f0bcfa',
    'research/metabric_realdata_v1/results/main_table.csv': '858bce261329eb8d1c907e89563ab48caeb9cbbee1b4a4b501acd16886ffc288',
    'research/metabric_risk_reconciliation_v1/results/cohort_transition.csv': '468cb5e8e05a20e22736d7bbf7db8975fd777eaa0eacb209a8a762d4fa99569e',
    'research/metabric_risk_reconciliation_v1/results/budget_error_tradeoffs.csv': '0fab8efc4565d578b88e7e078e393dc4b1116b503aa552acc522dd95c2b8c061',
    'research/metabric_risk_reconciliation_v1/results/paired_statistics.csv': 'e5ece7708cdc59a0b4afb40fe042dfe821721aae0aad2f8051b75be2a1f2c954',
    'research/matched_coverage_v1/results/primary_table.csv': 'a755fdb51c4d780f51442cbaaf0c49dc04d4db3dfd66252ed04def3e42165a4a',
    'research/matched_coverage_v1/results/primary_statistics.csv': 'cde7336e5ee82bd8faa7069101ab7d1ea0273290463caa53ed0237b0a54a2e46',
    'research/clinical_validation_v1/results/primary_operating_points.csv': 'd31887e3ee30e0d7a5d6d5a7ef5b2ae2510a06f2fd16bac733ee592f412cb8db',
    'research/clinical_validation_v1/results/primary_statistics.csv': '4df2343e4bb00d82c286ed774b7e61b5db560402ad20b53ad4f3aa84f1f95c63',
    'research/clinical_extraction_generalization_v1/results/method_metrics.csv': '6a19abb1b051da9b27f1a4f18864c2757e49b4b8724b6d4d3efef0106a461102',
    'research/clinical_extraction_generalization_v1/results/confidence_intervals.csv': 'd15d173edbe93f068b63a756ac135b53fd7c6bf9e695b19593bba2a9114e9937',
    'research/clinical_extraction_generalization_v1/results/withholding.csv': 'da441c21f4a80b8ec8b74356caa348e61706ea1f9471ac1de1b0a5d9d4efe9e5',
    'research/clinical_extraction_generalization_v1/results/field_metrics.csv': '7abbb4ce06bebe6c9b378102ec2298402adf66784203e7b7eb1b1b5a0cdd0bba',
    'research/clinical_extraction_generalization_v1/results/component_transitions.csv': 'd0c619cc8e70673708695a6faa9f8f9e932373b390749a963f956a2086061629',
}


def rows(name):
    with (ROOT/name).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize('name', sorted(HASHES))
def test_saved_aggregate_identity(name):
    digest = hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    allowed = {HASHES[name]}
    if name == 'results/recomb/20261026-certified-review-v1/comparison.csv':
        allowed.add('63b5dbc29d1df8465e199f107736d6aede797b27c727ebdf4634b72dea10efa7')
    assert digest in allowed


def test_result_allowlist_and_patient_columns():
    assert set(HASHES) == public_release.AGGREGATES
    assert not public_release.audit(public_release.inventory())
    for name in HASHES:
        assert public_release.eligible(name)
        fields = set(rows(name)[0])
        assert not fields & {'patient_id', 'patient_key', 'study_id', 'report_id', 'source_quote', 'raw_text'}


def test_release_audit_rejects_patient_level_columns(tmp_path, monkeypatch):
    name = sorted(HASHES)[0]
    target = tmp_path/name
    target.parent.mkdir(parents=True)
    target.write_text('patient_id,value\nsynthetic-test-only,1\n', encoding='utf-8')
    monkeypatch.setattr(public_release, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='patient_level_content'):
        public_release.audit([name])


@pytest.mark.parametrize('phase', ['metabric_risk_reconciliation_v1', 'matched_coverage_v1', 'clinical_validation_v1'])
def test_saved_holm_corrections(phase):
    name = 'paired_statistics.csv' if phase == 'metabric_risk_reconciliation_v1' else 'primary_statistics.csv'
    data = rows(f'research/{phase}/results/{name}')
    probabilities = [float(r['p_value']) if r['p_value'] else 1.0 for r in data]
    previous = 0.0
    for rank, index in enumerate(sorted(range(len(data)), key=probabilities.__getitem__)):
        previous = max(previous, min(1.0, probabilities[index]*(len(data)-rank)))
        if data[index]['p_holm']:
            assert float(data[index]['p_holm']) == pytest.approx(previous, abs=1e-12)


def test_extraction_denominators_and_abstention_cost():
    data = {r['method']: r for r in rows('research/clinical_extraction_generalization_v1/results/method_metrics.csv')}
    for r in data.values():
        assert int(r['known_references']) == 20
        assert int(r['primary_patients']) == 8
        assert float(r['audited_precision']) == pytest.approx(int(r['audited_supported'])/int(r['audited_accepted']))
        assert int(r['categorical_accepted_100']) + int(r['categorical_withheld_100']) == int(r['categorical_candidates_100'])
    assert float(data['corrected_context']['audited_precision']) < float(data['v2_context']['audited_precision'])
    withheld = rows('research/clinical_extraction_generalization_v1/results/withholding.csv')
    strict = next(r for r in withheld if r['method'] == 'selective_verification')
    assert int(strict['audited_correct_withheld']) == 10


def test_native_matching_failure_and_quota_scope():
    matched = rows('research/matched_coverage_v1/results/primary_statistics.csv')
    native = [r for r in matched if r['family'] == 'matched_coverage']
    assert not any(r['valid_matched_coverage'] == 'True' for r in native)
    quota = rows('research/clinical_validation_v1/results/primary_statistics.csv')
    assert all(r['valid_matching'] == 'True' for r in quota)
    contrast = next(r for r in quota if r['target'] == '0.7' and r['metric'] == 'proxy_error' and r['comparison'] == 'triallens_nominal_minus_unconstrained')
    assert float(contrast['estimate']) > 0


def test_final_synthetic_comparison_and_interval_bounds():
    comparison = rows('results/recomb/20261026-certified-review-v1/comparison.csv')
    assert {'final', 'ood'} <= {r['split'] for r in comparison}
    certified = {r['split']: r for r in comparison if r['method'] == 'bernstein_repair'}
    assert int(certified['final']['actual_violations']) == 0
    assert int(certified['ood']['actual_violations']) == 18
    effects = rows('results/recomb/20261026-certified-review-v1/paired_effects.csv')
    hull = next(r for r in effects if r['split'] == 'final' and r['candidate'] == 'finite_cg' and r['reference'] == 'library_hull' and r['metric'] == 'utility')
    assert float(hull['holm_p']) > .05
    for r in rows('research/clinical_extraction_generalization_v1/results/confidence_intervals.csv'):
        assert all(math.isfinite(float(r[k])) for k in ('estimate', 'lower95', 'upper95'))
        assert float(r['lower95']) <= float(r['estimate']) <= float(r['upper95'])
