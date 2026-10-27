import re

from pydantic import BaseModel


class Trial(BaseModel):
    nct_id: str | None
    title: str | None
    recruitment_status: str | None
    conditions: list[str]
    eligibility_criteria: str | None
    source_url: str | None


def parse_trials(payload: object) -> list[Trial]:
    if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
        raise ValueError("Invalid studies response")

    trials = []
    for study in payload["studies"]:
        if not isinstance(study, dict):
            raise ValueError("Invalid study record")
        protocol = study.get("protocolSection") or {}
        identification = protocol.get("identificationModule") or {}
        nct_id = identification.get("nctId")
        source_url = None
        if isinstance(nct_id, str) and re.fullmatch(r"NCT\d{8}", nct_id):
            source_url = f"https://clinicaltrials.gov/study/{nct_id}"
        trials.append(Trial(
            nct_id=nct_id,
            title=identification.get("briefTitle"),
            recruitment_status=(protocol.get("statusModule") or {}).get("overallStatus"),
            conditions=(protocol.get("conditionsModule") or {}).get("conditions") or [],
            eligibility_criteria=(protocol.get("eligibilityModule") or {}).get("eligibilityCriteria"),
            source_url=source_url,
        ))
    return trials
