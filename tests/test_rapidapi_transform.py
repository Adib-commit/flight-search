import json
from pathlib import Path

from app.config import Settings
from app.output import build_response
from app.rapidapi_transform import transform_itineraries
from app.scoring import score_itineraries

FIX = Path(__file__).parent / "fixtures" / "rapidapi_tlv_clj.json"


def _load():
    payload = json.loads(FIX.read_text())
    return transform_itineraries(payload["data"]["itineraries"])


def test_transform_direct():
    direct = next(i for i in _load() if i.id == "direct-wizz")
    assert direct.stops_count == 0
    assert direct.carriers == ["W6"]
    assert direct.total_duration_min == 385
    assert direct.layover_min == 0
    assert direct.price_total == 320.0


def test_transform_onestop():
    st = next(i for i in _load() if i.id == "onestop-otp")
    assert st.stops_count == 2            # 1 per direction
    assert st.layover_min == 480          # 240 each way
    assert st.price_total == 250.0
    assert {s.carrier_code for s in st.segments} == {"W6"}


def test_direct_wins_best_value():
    scored = score_itineraries(_load(), Settings(provider="rapidapi"))
    resp = build_response(scored)
    assert resp.best_value[0].id == "direct-wizz"
    assert resp.cheapest.id == "onestop-otp"   # cheaper but worse value
    assert resp.fastest.id == "direct-wizz"
    assert len(resp.options) == 2              # feeds the cost chart
