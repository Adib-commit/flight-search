import json
from pathlib import Path

from app.transform import parse_iso_duration, transform_offers

FIX = Path(__file__).parent / "fixtures" / "jfk_cdg.json"


def test_parse_iso_duration():
    assert parse_iso_duration("PT7H30M") == 450
    assert parse_iso_duration("PT55M") == 55
    assert parse_iso_duration("PT2H") == 120
    assert parse_iso_duration("") == 0
    assert parse_iso_duration("garbage") == 0


def test_transform_offers():
    offers = json.loads(FIX.read_text())
    its = transform_offers(offers)
    assert len(its) == 3

    direct = next(i for i in its if i.id == "1")
    assert direct.stops_count == 0
    assert direct.carriers == ["AF"]
    assert direct.total_duration_min == 450
    assert direct.layover_min == 0
    assert direct.price_total == 650.0

    conn = next(i for i in its if i.id == "2")
    assert conn.stops_count == 1
    assert conn.carriers == ["FR"]
    # itin duration 705 - flight time (360+105=465) = 240 layover
    assert conn.layover_min == 240
