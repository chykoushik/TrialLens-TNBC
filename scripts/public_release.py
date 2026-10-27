import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = {'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.txt', '.gitignore', '.dockerignore', '.env.example',
       'Dockerfile', 'render.yaml', 'requirements.txt', 'requirements-demo.lock.txt'}
HELPERS = {'public_demo.py', 'serve_public.py', 'readiness.py', 'demo_smoke.py', 'publication_audit.py',
           'nebius_check.py', 'extraction_authorization.py', 'extract_criteria.py', 'recover_extraction.py',
           'benchmark_eligibility.py', 'verify_offline_workflow.py', 'prioritization_experiment.py'}
PRIVATE_TESTS = {'test_recomb_evaluation.py', 'test_prioritization_followup.py', 'test_prioritization_sensitivity.py',
                 'test_prioritization_validation.py', 'test_reliability_model.py', 'test_release_preparation.py'}
FRONTEND = {'package.json', 'package-lock.json', 'index.html', 'tsconfig.json', 'vite.config.ts', 'playwright.config.mjs'}
MARKERS = {'cache/.gitkeep', 'data/raw/.gitkeep', 'data/synthetic/.gitkeep', 'data/processed/.gitkeep', 'results/.gitkeep'}
FIXTURES = {'synthetic_criteria.json', 'extraction_snapshot.json', 'extraction_mock.json', 'eligibility_benchmark_case.json'}
PATTERNS = {
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'provider_token': r'\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{24,}\b',
    'aws_access_id': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'credential_url': r'https?://[^\s/:]+:[^\s/@]+@',
    'personal_path': r'[A-Z]:[\\/]Users[\\/][^\s]+',
}


def eligible(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts:
        return False
    value = path.as_posix()
    if any(p.lower() in {'node_modules', '__pycache__', '.git', 'dist', 'authorizations'} for p in path.parts):
        return False
    if path.suffix.lower() in {'.md', '.markdown', '.pdf', '.zip', '.log', '.claim', '.key', '.pem'}:
        return value == 'README.md'
    if value in TOP | MARKERS | {'scripts/public_release.py', 'benchmarks/eligibility/annotation.schema.json'}:
        return True
    if path.parent.as_posix() == 'backend' and path.name in HELPERS:
        return True
    if value.startswith('backend/app/') and path.suffix == '.py':
        return True
    if path.parent.as_posix() == 'backend/tests' and path.suffix == '.py':
        return path.name not in PRIVATE_TESTS
    if path.parent.as_posix() == 'backend/tests/fixtures':
        return path.name in FIXTURES
    if path.parent.as_posix() == 'frontend':
        return path.name in FRONTEND
    if value.startswith('frontend/src/'):
        return path.suffix in {'.ts', '.tsx', '.css'} or value in {
            'frontend/src/fixtures/tnbc_demo.json', 'frontend/src/fixtures/research_showcase.json'}
    if path.parent.as_posix() == 'frontend/e2e':
        return path.suffix == '.mjs'
    if path.parent.as_posix() == 'third_party/licenses':
        return path.suffix == '.txt'
    return value in {'assets/screenshots/demo-desktop.png', 'assets/screenshots/home-mobile.png'}


def inventory():
    candidates = [ROOT/p for p in TOP | MARKERS]
    for folder in ('backend', 'frontend/src', 'frontend/e2e', 'third_party/licenses', 'assets/screenshots'):
        candidates.extend((ROOT/folder).rglob('*'))
    candidates.extend(ROOT/'frontend'/p for p in FRONTEND)
    candidates.extend([Path(__file__), ROOT/'benchmarks/eligibility/annotation.schema.json'])
    paths = sorted({p.relative_to(ROOT).as_posix() for p in candidates
                    if p.is_file() and not p.is_symlink() and eligible(p.relative_to(ROOT))})
    missing = [p for p in TOP | MARKERS if not (ROOT/p).is_file()]
    if missing:
        raise FileNotFoundError(', '.join(sorted(missing)))
    return paths


def audit(paths):
    findings = []
    for name in paths:
        path = ROOT/name
        if path.suffix == '.png':
            continue
        text = path.read_text(encoding='utf-8')
        if name in MARKERS and text.strip():
            raise ValueError(f'Nonempty marker: {name}')
        for category, pattern in PATTERNS.items():
            if category == 'credential_url' and name.startswith('backend/tests/'):
                continue
            for match in re.finditer(pattern, text, re.I if category == 'personal_path' else 0):
                findings.append(dict(path=name, category=category, line=text.count('\n', 0, match.start())+1))
    assert [p for p in paths if p.lower().endswith('.md')] == ['README.md']
    if findings:
        raise ValueError(json.dumps(findings))
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path)
    args = parser.parse_args()
    paths = inventory()
    audit(paths)
    report = dict(retained_files=len(paths), files={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
                  excluded=['AGENTS.md and internal prompts', 'docs/', 'research/', 'results/ except empty marker',
                            'data/ except empty markers', 'cache/ except empty marker', 'logs/', 'models/',
                            'figures/', 'scripts/paper_figures/', 'archives, PDFs, private Markdown and credentials',
                            'historical experiment-only CLI/tests', 'virtual environments, node_modules and build outputs'],
                  license='MPL-2.0; ownership confirmation required before publication.',
                  ownership_confirmed=False,
                  markdown=['README.md'], findings=[])
    if args.stage:
        target = (ROOT/args.stage).resolve()
        if not target.is_relative_to((ROOT/'cache').resolve()) or target.exists():
            raise ValueError('Fresh cache directory required')
        target.mkdir(parents=True)
        for name in paths:
            destination = target/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, destination)
        report['stage'] = target.relative_to(ROOT).as_posix()
    (ROOT/'cache').mkdir(exist_ok=True)
    (ROOT/'cache/public-release-inventory.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(f'Retained files: {len(paths)}')
    print('Inventory: cache/public-release-inventory.json')
    print('License: MPL-2.0; rights unconfirmed')


if __name__ == '__main__':
    main()
