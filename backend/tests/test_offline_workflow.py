from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.extraction_source import ROOT
from backend.verify_offline_workflow import verify


def test_complete_offline_dependency_chain():
    with TemporaryDirectory(dir=ROOT / "cache") as temporary:
        report = verify(Path(temporary) / "workflow")
    assert len(report["sources"]) == 5
    assert report["transitions"][3]["uncertainty"] == "0"
