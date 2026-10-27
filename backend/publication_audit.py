import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "node_modules", "data", "results", "cache", "logs", "models", "figures",
            ".aws", ".azure", ".ssh", ".kube", "__pycache__", ".pytest_cache"}
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".txt", ".css", ".html", ".yml", ".yaml"}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_id": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "provider_token": re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{24,}\b"),
    "credential_assignment": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|secret)[\"']?\]?\s*[:=]\s*[\"'][A-Za-z0-9_+/=-]{16,}[\"']"
    ),
    "credential_url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
    "local_path": re.compile(r"(?:[A-Z]:[\\/](?:Users|TrialLens-TNBC)[\\/]|/Users/|/home/)", re.I),
}


def excluded(path):
    name = path.name.lower()
    return (any(part.lower() in EXCLUDED or part.lower() == "authorizations" for part in path.parts)
            or name.startswith((".env", "credentials", "billing", "invoice"))
            or name in {".netrc", ".pypirc", ".npmrc", "raw_response.json"}
            or path.suffix.lower() in {".pem", ".key", ".pfx", ".p12", ".claim"})


def audit(root=ROOT):
    findings = []
    scanned = skipped = 0
    def visit(directory):
        nonlocal scanned, skipped
        for path in directory.iterdir():
            relative = path.relative_to(root)
            if path.is_symlink() or excluded(relative):
                skipped += 1
                continue
            if path.is_dir():
                visit(path)
            elif path.suffix.lower() in EXTENSIONS and path.stat().st_size < 5_000_000:
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
                scanned += 1
                for category, pattern in PATTERNS.items():
                    for match in pattern.finditer(content):
                        findings.append({"category": category, "path": relative.as_posix(),
                                         "line": content.count("\n", 0, match.start()) + 1})
    visit(root)
    git = ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root)]
    tracked = subprocess.run(git + ["ls-files", "-z"], capture_output=True, check=True).stdout
    history = subprocess.run(git + ["rev-list", "--all", "--count"], capture_output=True, check=True).stdout
    return {"scanned_files": scanned, "excluded_entries": skipped, "findings": findings,
            "tracked_files": len([name for name in tracked.split(b"\0") if name]),
            "commit_count": int(history or b"0"),
            "license_present": any((root / name).is_file() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt")),
            "scope": "Selected publication source and build text only. Credential files, private stores and logs excluded without reading. Pattern scan is not a complete secret or dependency audit."}


if __name__ == "__main__":
    destination = ROOT / "cache/publication-audit.json"
    destination.write_text(json.dumps(audit(), indent=2), encoding="utf-8")
    print(json.dumps({"report": destination.relative_to(ROOT).as_posix()}))
