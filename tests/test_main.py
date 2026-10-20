from fastapi.testclient import TestClient
from main import CATALOG, app, enrich, normalize


def test_known_normalization_and_unknown():
    assert normalize("SQ* CÁFÉ #123") == "cafe"
    merchant = CATALOG[0]
    assert enrich("POS* " + merchant["name"] + " #567")["id"] == merchant["id"]
    assert enrich("unlisted unrelated organization")["id"] is None


def test_api_empty_input_rejected_and_cached_lookup():
    enrich.cache_clear()
    enrich("UNLISTED")
    enrich("UNLISTED")
    assert enrich.cache_info().hits == 1
    with TestClient(app) as client:
        assert client.post("/enrich", json={"descriptor": ""}).status_code == 422
