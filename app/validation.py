from __future__ import annotations

import re
from datetime import date

from .models import SearchRequest

IATA_RE = re.compile(r"^[A-Z]{3}$")


class ValidationError(ValueError):
    pass


def validate_request(req: SearchRequest, today: date | None = None) -> None:
    """Validate business rules beyond Pydantic typing. Raises ValidationError."""
    today = today or date.today()

    origin = req.origin.strip().upper()
    destination = req.destination.strip().upper()

    if not IATA_RE.match(origin):
        raise ValidationError(f"Origin '{req.origin}' must be a 3-letter IATA code.")
    if not IATA_RE.match(destination):
        raise ValidationError(
            f"Destination '{req.destination}' must be a 3-letter IATA code."
        )
    if origin == destination:
        raise ValidationError("Origin and destination must differ.")

    dep = req.flight_dates.departure
    ret = req.flight_dates.ret

    if dep < today:
        raise ValidationError(f"Departure date {dep} is in the past.")
    if ret is not None:
        if ret < today:
            raise ValidationError(f"Return date {ret} is in the past.")
        if ret < dep:
            raise ValidationError("Return date must be on or after departure date.")

    if req.traveler_count < 1:
        raise ValidationError("traveler_count must be at least 1.")
    if req.traveler_count > 9:
        raise ValidationError("traveler_count max is 9 (Amadeus limit).")

    inc = req.airline_filters.include
    exc = req.airline_filters.exclude
    if inc and exc:
        raise ValidationError(
            "Provide either an include list or an exclude list, not both."
        )
