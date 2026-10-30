"""Live gatherer functions with the HTTP layer mocked — tests must
never touch the network."""
import variant_research_agent.gatherers as g
from variant_research_agent.schema import VariantRecord

REC = VariantRecord(allele_id=15925, gene="ARSB",
                    name="NM_000046.5(ARSB):c.1178A>C (p.His393Pro)",
                    chrom="5", pos=78839391, ref="T", alt="G")


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_gnomad_live_parsing(monkeypatch):
    payload = {"data": {"variant": {"genome": {"af": 0.02}, "exome": {"af": 0.03}}}}
    monkeypatch.setattr(g.requests, "post", lambda *a, **k: FakeResp(payload))
    item = g.fetch_gnomad_live(REC)
    assert item is not None and item.live is True
    assert item.source_id == "GNOMAD:5:78839391:T>G"
    assert item.direction.value == "benign"  # AF 0.03 >= 0.01


def test_gnomad_live_not_observed(monkeypatch):
    payload = {"data": {"variant": None}}
    monkeypatch.setattr(g.requests, "post", lambda *a, **k: FakeResp(payload))
    item = g.fetch_gnomad_live(REC)
    assert item is not None and "not observed" in item.detail


def test_gnomad_live_failure_returns_none(monkeypatch):
    def boom(*a, **k):
        raise g.requests.ConnectionError("down")
    monkeypatch.setattr(g.requests, "post", boom)
    assert g.fetch_gnomad_live(REC) is None


def test_pubmed_live_parsing(monkeypatch):
    responses = [
        FakeResp({"esearchresult": {"idlist": ["12345"]}}),
        FakeResp({"result": {"12345": {"title": "ARSB variant study", "pubdate": "2023 May"}}}),
    ]
    monkeypatch.setattr(g.requests, "get", lambda *a, **k: responses.pop(0))
    items = g.fetch_pubmed_live(REC)
    assert len(items) == 1
    assert items[0].source_id == "PMID:12345"
    assert items[0].direction.value == "neutral"  # literature is context, not direction


def test_pubmed_offline_returns_nothing():
    notes = []
    assert g.gather_pubmed(REC, live=False, notes=notes) == []
    assert notes and "offline" in notes[0]
