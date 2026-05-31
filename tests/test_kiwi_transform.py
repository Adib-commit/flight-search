import json
from pathlib import Path

from app.config import Settings
from app.kiwi_transform import transform_trips
from app.output import build_response
from app.scoring import score_itineraries

FIX = Path(__file__).parent / "fixtures" / "kiwi_tlv_clj.json"


def _load():
    payload = json.loads(FIX.read_text())
    return transform_trips(payload["data"], payload["currency"])


def test_kiwi_transform_direct():
    its = _load()
    direct = next(i for i in its if i.id == "direct-wizz")
    assert direct.stops_count == 0
    assert direct.carriers == ["W6"]          # Wizz
    assert direct.total_duration_min == 385    # 23100s
    assert direct.layover_min == 0
    assert direct.price_total == 320.0


def test_kiwi_transform_selftransfer():
    its = _load()
    st = next(i for i in its if i.id == "selftransfer-otp")
    # TLV-OTP-CLJ out + CLJ-OTP-TLV back = 2 transfers
    assert st.stops_count == 2
    assert st.layover_min == 480    # 4h each way
    assert st.price_total == 250.0


def test_direct_wizz_is_best_value_over_self_transfer():
    """The TLV->CLJ example: direct Wizz beats the cheaper via-OTP self-transfer.

    Self-transfer is $70 cheaper but adds 2 stops + 8h layover, so 'best value'
    (cost + stops + layover) correctly prefers the direct flight.
    """
    scored = score_itineraries(_load(), Settings(provider="kiwi"))
    resp = build_response(scored)
    assert resp.best_value[0].id == "direct-wizz"
    assert resp.cheapest.id == "selftransfer-otp"   # cheapest != best value
    assert resp.fastest.id == "direct-wizz"
