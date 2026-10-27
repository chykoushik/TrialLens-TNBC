from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_TESTS = {
    'test_five_genuine_studies_deduplicated_and_reproducible',
    'test_complete_offline_dependency_chain',
    'test_readiness_is_offline_secret_safe_and_optional_files_are_nonblocking',
    'test_smoke_exercises_real_fictional_calculations_without_external_requests',
    'test_first_public_trial_prompt_contains_only_the_selected_study',
    'test_real_candidates_are_exact_nonoverlapping_drafts',
}


def pytest_collection_modifyitems(items):
    if not any((ROOT/'data/raw/trials').glob('*/response.json')):
        for item in items:
            source_integration = item.path.name == 'test_annotation_api.py' and item.originalname != 'test_unknown_study_and_wrong_api_prefix'
            if item.originalname in SOURCE_TESTS or source_integration:
                item.add_marker(pytest.mark.skip(reason='Optional private saved-source integration data is not distributed'))
    if not (ROOT/'results/extraction/20261026T001316900955Z_91c45c376f604f17a6a2bdc48dce58f2').is_dir():
        for item in items:
            if item.originalname == 'test_saved_third_extraction_only_recovers_five_source_valid_entries':
                item.add_marker(pytest.mark.skip(reason='Optional private provider artifact is not distributed'))
    if not (ROOT/'backend/research_prioritization_experiment.py').is_file():
        for item in items:
            if item.originalname == 'test_research_artifacts_reproducibility_and_gap_labels':
                item.add_marker(pytest.mark.skip(reason='Internal historical experiment driver is not distributed'))


@pytest.fixture(scope='session', autouse=True)
def workspace_directories():
    for name in ('cache', 'data/raw/trials', 'data/synthetic'):
        (ROOT/name).mkdir(parents=True, exist_ok=True)
