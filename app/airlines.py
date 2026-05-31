"""Map common airline names <-> IATA codes.

UI accepts regular names; Amadeus + per-segment filters need IATA codes.
Lookup is case-insensitive. Unknown names are surfaced to the caller so the
user gets a clear error instead of a silently-ignored filter.
"""

NAME_TO_IATA: dict[str, str] = {
    "aegean": "A3",
    "aer lingus": "EI",
    "aeroflot": "SU",
    "aeromexico": "AM",
    "air canada": "AC",
    "air china": "CA",
    "air france": "AF",
    "air india": "AI",
    "air new zealand": "NZ",
    "alaska airlines": "AS",
    "alaska": "AS",
    "alitalia": "AZ",
    "american airlines": "AA",
    "american": "AA",
    "ana": "NH",
    "all nippon airways": "NH",
    "austrian airlines": "OS",
    "austrian": "OS",
    "avianca": "AV",
    "british airways": "BA",
    "brussels airlines": "SN",
    "cathay pacific": "CX",
    "china eastern": "MU",
    "china southern": "CZ",
    "copa airlines": "CM",
    "delta air lines": "DL",
    "delta": "DL",
    "easyjet": "U2",
    "egyptair": "MS",
    "el al": "LY",
    "elal": "LY",
    "emirates": "EK",
    "ethiopian airlines": "ET",
    "etihad airways": "EY",
    "etihad": "EY",
    "finnair": "AY",
    "frontier": "F9",
    "frontier airlines": "F9",
    "hawaiian airlines": "HA",
    "iberia": "IB",
    "icelandair": "FI",
    "indigo": "6E",
    "japan airlines": "JL",
    "jal": "JL",
    "jetblue": "B6",
    "jetblue airways": "B6",
    "kenya airways": "KQ",
    "klm": "KL",
    "korean air": "KE",
    "kuwait airways": "KU",
    "latam": "LA",
    "lot polish airlines": "LO",
    "lot": "LO",
    "lufthansa": "LH",
    "malaysia airlines": "MH",
    "norwegian": "DY",
    "pegasus": "PC",
    "philippine airlines": "PR",
    "qantas": "QF",
    "qatar airways": "QR",
    "qatar": "QR",
    "royal air maroc": "AT",
    "ryanair": "FR",
    "saudia": "SV",
    "scandinavian airlines": "SK",
    "sas": "SK",
    "singapore airlines": "SQ",
    "south african airways": "SA",
    "southwest": "WN",
    "southwest airlines": "WN",
    "spirit": "NK",
    "spirit airlines": "NK",
    "sri lankan airlines": "UL",
    "swiss": "LX",
    "swiss international air lines": "LX",
    "tap air portugal": "TP",
    "tap portugal": "TP",
    "thai airways": "TG",
    "turkish airlines": "TK",
    "turkish": "TK",
    "united airlines": "UA",
    "united": "UA",
    "vietnam airlines": "VN",
    "virgin atlantic": "VS",
    "vueling": "VY",
    "wizz air": "W6",
    "wizzair": "W6",
}

IATA_TO_NAME: dict[str, str] = {}
for _name, _code in NAME_TO_IATA.items():
    IATA_TO_NAME.setdefault(_code, _name.title())


class UnknownAirlineError(ValueError):
    def __init__(self, names: list[str]):
        self.names = names
        super().__init__(
            "Unknown airline name(s): "
            + ", ".join(names)
            + ". Use a known airline name or its 2-letter IATA code."
        )


def resolve_codes(names: list[str]) -> list[str]:
    """Resolve a list of airline names (or raw IATA codes) to IATA codes.

    A 2-letter uppercase token is accepted as an already-valid code.
    Raises UnknownAirlineError listing every name that could not be resolved.
    """
    codes: list[str] = []
    unknown: list[str] = []
    for raw in names:
        token = raw.strip()
        if not token:
            continue
        key = token.lower()
        if key in NAME_TO_IATA:
            codes.append(NAME_TO_IATA[key])
        elif len(token) == 2 and token.isalpha():
            codes.append(token.upper())
        else:
            unknown.append(token)
    if unknown:
        raise UnknownAirlineError(unknown)
    # de-dupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def code_to_name(code: str) -> str:
    return IATA_TO_NAME.get(code, code)
