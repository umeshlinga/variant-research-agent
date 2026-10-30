"""Evidence item schema: R2 (no source, no claim) is enforced by the
pydantic model itself."""
import pytest
from pydantic import ValidationError

from variant_research_agent.schema import Direction, EvidenceItem


def test_valid_item():
    item = EvidenceItem(source="ClinVar (frozen 2024-01)",
                        source_id="CLINVAR:allele15925",
                        detail="status at freeze: Pathogenic",
                        direction=Direction.PATHOGENIC)
    assert item.source_id == "CLINVAR:allele15925"
    assert item.live is False


def test_missing_source_id_rejected():
    with pytest.raises(ValidationError):
        EvidenceItem(source="ClinVar", source_id="", detail="a claim with no source")


def test_blank_source_id_rejected():
    with pytest.raises(ValidationError):
        EvidenceItem(source="ClinVar", source_id="   ", detail="blank id")


def test_missing_detail_rejected():
    with pytest.raises(ValidationError):
        EvidenceItem(source="ClinVar", source_id="CLINVAR:allele1", detail="")


def test_direction_must_be_valid():
    with pytest.raises(ValidationError):
        EvidenceItem(source="X", source_id="X:1", detail="d", direction="sideways")


def test_json_round_trip():
    item = EvidenceItem(source="gnomAD", source_id="GNOMAD:5:1:A>G",
                        detail="AF = 0.001", direction="neutral", live=True)
    back = EvidenceItem(**item.model_dump(mode="json"))
    assert back == item
