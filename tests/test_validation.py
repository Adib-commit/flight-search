from __future__ import annotations

from datetime import date

import pytest

from app.airlines import UnknownAirlineError, resolve_codes
from app.models import AirlineFilters, FlightDates, SearchRequest
from app.validation import ValidationError, validate_request

TODAY = date(2026, 1, 1)


def _req(**kw):
    base = dict(
        origin="JFK",
        destination="CDG",
        flight_dates=FlightDates(departure=date(2026, 9, 15), ret=date(2026, 9, 22)),
        traveler_count=2,
        airline_filters=AirlineFilters(),
    )
    base.update(kw)
    return SearchRequest(**base)


def test_valid_passes():
    validate_request(_req(), today=TODAY)


def test_past_departure():
    with pytest.raises(ValidationError):
        validate_request(
            _req(flight_dates=FlightDates(departure=date(2025, 1, 1))), today=TODAY
        )


def test_return_before_departure():
    with pytest.raises(ValidationError):
        validate_request(
            _req(flight_dates=FlightDates(departure=date(2026, 9, 22), ret=date(2026, 9, 15))),
            today=TODAY,
        )


def test_bad_iata():
    with pytest.raises(ValidationError):
        validate_request(_req(origin="J"), today=TODAY)


def test_same_origin_destination():
    with pytest.raises(ValidationError):
        validate_request(_req(destination="JFK"), today=TODAY)


def test_include_and_exclude_conflict():
    with pytest.raises(ValidationError):
        validate_request(
            _req(airline_filters=AirlineFilters(include=["Delta"], exclude=["Ryanair"])),
            today=TODAY,
        )


def test_resolve_names():
    assert resolve_codes(["Ryanair", "Spirit"]) == ["FR", "NK"]
    assert resolve_codes(["delta", "UNITED"]) == ["DL", "UA"]
    assert resolve_codes(["BA"]) == ["BA"]  # raw IATA passthrough


def test_resolve_unknown():
    with pytest.raises(UnknownAirlineError):
        resolve_codes(["NotAnAirline"])
