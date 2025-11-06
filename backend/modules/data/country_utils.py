"""Utilities for matching catalogue items to user-selected countries."""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Optional, Set

import pycountry

from backend.models.data_catalogue import DataRegion, DataCatalogueItem

logger = logging.getLogger(__name__)


def _sanitize_token(value: str) -> str:
    """Normalize strings into comparable tokens."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = ascii_only.lower()
    ascii_only = ascii_only.replace("&", " and ")
    ascii_only = ascii_only.replace("-", " ")
    ascii_only = ascii_only.replace(".", " ")
    ascii_only = re.sub(r"[^a-z0-9\s]", " ", ascii_only)
    ascii_only = re.sub(r"\s+", " ", ascii_only).strip()
    return ascii_only.replace(" ", "_")


NAME_OVERRIDES = {
    "dominican_rep": "Dominican Republic",
    "st_vin_and_gren": "Saint Vincent and the Grenadines",
    "antigua_and_barb": "Antigua and Barbuda",
    "s_sudan": "South Sudan",
    "w_sahara": "Western Sahara",
    "bosnia_and_herz": "Bosnia and Herzegovina",
    "macedonia": "North Macedonia",
    "solomon_is": "Solomon Islands",
    "palestine": "Palestine, State of",
    "north_korea": "Korea, Democratic People's Republic of",
    "south_korea": "Korea, Republic of",
    "laos": "Lao People's Democratic Republic",
    "brunei": "Brunei Darussalam",
    "timor_leste": "Timor-Leste",
    "taiwan": "Taiwan",
    "st_kitts_and_nevis": "Saint Kitts and Nevis",
}


TOKEN_OVERRIDES = {
    "united_states_of_america": {"us", "usa", "united_states", "usd", "dollar"},
    "united_kingdom": {"uk", "gb", "gbr", "great_britain"},
    "north_korea": {"dprk", "prk"},
    "south_korea": {"rok", "kor", "kr"},
    "china": {"prc", "cn", "chn", "cny", "yuan"},
    "japan": {"jp", "jpn", "jpy", "yen"},
    "india": {"in", "ind", "inr", "rupee"},
    "canada": {"ca", "can", "cad"},
    "australia": {"au", "aus", "aud"},
    "new_zealand": {"nz", "nzl", "nzd"},
    "brazil": {"br", "bra", "brl"},
    "argentina": {"ar", "arg", "ars"},
    "mexico": {"mx", "mex", "mxn"},
    "germany": {"de", "deu", "eur"},
    "france": {"fr", "fra", "eur"},
    "italy": {"it", "ita", "eur"},
    "spain": {"es", "esp", "eur"},
    "switzerland": {"ch", "che", "chf"},
    "sweden": {"se", "swe", "sek"},
    "norway": {"no", "nor", "nok"},
    "denmark": {"dk", "dnk", "dkk"},
    "netherlands": {"nl", "nld", "eur"},
    "belgium": {"be", "bel", "eur"},
    "austria": {"at", "aut", "eur"},
    "ireland": {"ie", "irl", "eur"},
    "finland": {"fi", "fin", "eur"},
    "iceland": {"is", "isl", "isk"},
    "portugal": {"pt", "prt", "eur"},
    "greece": {"gr", "grc", "eur"},
    "poland": {"pl", "pol", "pln"},
    "czechia": {"cz", "cze", "czech_republic", "czk"},
    "slovakia": {"sk", "svk", "eur"},
    "hungary": {"hu", "hun", "huf"},
    "romania": {"ro", "rou", "ron"},
    "bulgaria": {"bg", "bgr", "bgn"},
    "croatia": {"hr", "hrv", "eur"},
    "slovenia": {"si", "svn", "eur"},
    "serbia": {"rs", "srb", "rsd"},
    "montenegro": {"me", "mne", "eur"},
    "albania": {"al", "alb", "all"},
    "ukraine": {"ua", "ukr", "uah"},
    "belarus": {"by", "blr", "byn"},
    "moldova": {"md", "mda", "mdl"},
    "russia": {"ru", "rus", "russian_federation", "rub"},
    "georgia": {"ge", "geo", "gel"},
    "armenia": {"am", "arm", "amd"},
    "azerbaijan": {"az", "aze", "azn"},
    "turkey": {"tr", "tur", "try"},
    "israel": {"il", "isr", "ils", "shekel"},
    "saudi_arabia": {"sa", "sau", "sar"},
    "united_arab_emirates": {"ae", "are", "uae", "aed"},
    "qatar": {"qa", "qat", "qar"},
    "bahrain": {"bh", "bhr", "bhd"},
    "kuwait": {"kw", "kwt", "kwd"},
    "oman": {"om", "omn", "omr"},
    "yemen": {"ye", "yem", "yer"},
    "jordan": {"jo", "jor", "jod"},
    "lebanon": {"lb", "lbn", "lbp"},
    "iraq": {"iq", "irq", "iqd"},
    "syria": {"sy", "syr", "syp"},
    "iran": {"ir", "irn", "irr"},
    "egypt": {"eg", "egy", "egp"},
    "sudan": {"sd", "sdn", "sdg"},
    "south_sudan": {"ss", "ssd", "ssp"},
    "morocco": {"ma", "mar", "mad"},
    "algeria": {"dz", "dza", "dzd"},
    "tunisia": {"tn", "tun", "tnd"},
    "libya": {"ly", "lby", "lyd"},
    "mauritania": {"mr", "mrt", "mru"},
    "cyprus": {"cy", "cyp", "eur"},
    "pakistan": {"pk", "pak", "pkr"},
    "bangladesh": {"bd", "bgd", "bdt"},
    "sri_lanka": {"lk", "lka", "lkr"},
    "thailand": {"th", "tha", "thb"},
    "vietnam": {"vn", "vnm", "vnd"},
    "myanmar": {"mm", "mmr", "burma", "mmk"},
    "cambodia": {"kh", "khm", "khr"},
    "malaysia": {"my", "mys", "myr"},
    "singapore": {"sg", "sgp", "sgd"},
    "indonesia": {"id", "idn", "idr"},
    "philippines": {"ph", "phl", "php"},
    "mongolia": {"mn", "mng", "mnt"},
    "nepal": {"np", "npl", "npr"},
    "bhutan": {"bt", "btn", "btn", "nu"},
    "hong_kong": {"hk", "hkg", "hkd"},
    "taiwan": {"tw", "twn", "twd"},
    "papua_new_guinea": {"pg", "png", "pgk"},
    "fiji": {"fj", "fji", "fjd"},
    "vanuatu": {"vu", "vut", "vuv"},
    "samoa": {"ws", "wsm", "wst"},
    "timor_leste": {"tl", "tls", "east_timor", "usd"},
    "colombia": {"co", "col", "cop"},
    "venezuela": {"ve", "ven", "ves"},
    "guyana": {"gy", "guy", "gyd"},
    "suriname": {"sr", "sur", "srd"},
    "ecuador": {"ec", "ecu", "usd"},
    "peru": {"pe", "per", "pen"},
    "bolivia": {"bo", "bol", "bob"},
    "paraguay": {"py", "pry", "pyg"},
    "chile": {"cl", "chl", "clp"},
    "uruguay": {"uy", "ury", "uyu"},
    "belize": {"bz", "blz", "bzd"},
    "costa_rica": {"cr", "cri", "crc"},
    "guatemala": {"gt", "gtm", "gtq"},
    "honduras": {"hn", "hnd", "hnl"},
    "el_salvador": {"sv", "slv", "usd"},
    "nicaragua": {"ni", "nic", "nio"},
    "panama": {"pa", "pan", "usd", "pab"},
    "cuba": {"cu", "cub", "cup"},
    "jamaica": {"jm", "jam", "jmd"},
    "haiti": {"ht", "hti", "htg"},
    "bahamas": {"bs", "bhs", "bsd"},
    "barbados": {"bb", "brb", "bbd"},
    "trinidad_and_tobago": {"tt", "tto", "ttd"},
    "dominica": {"dm", "dma", "xcd"},
    "grenada": {"gd", "grd", "xcd"},
    "saint_lucia": {"lc", "lca", "xcd"},
    "andorra": {"ad", "and", "eur"},
    "monaco": {"mc", "mco", "eur"},
    "san_marino": {"sm", "smr", "eur"},
    "liechtenstein": {"li", "lie", "chf"},
    "luxembourg": {"lu", "lux", "eur"},
    "greenland": {"gl", "grl"},
    "bermuda": {"bm", "bmu"},
}


REGION_TO_COUNTRIES = {
    DataRegion.NORTH_AMERICA: {
        "canada",
        "united_states_of_america",
        "greenland",
        "bermuda",
    },
    DataRegion.LATIN_AMERICA: {
        "belize",
        "costa_rica",
        "guatemala",
        "honduras",
        "el_salvador",
        "nicaragua",
        "panama",
        "cuba",
        "jamaica",
        "haiti",
        "dominican_rep",
        "bahamas",
        "barbados",
        "saint_lucia",
        "trinidad_and_tobago",
        "dominica",
        "grenada",
        "st_vin_and_gren",
        "antigua_and_barb",
        "st_kitts_and_nevis",
        "colombia",
        "venezuela",
        "guyana",
        "suriname",
        "ecuador",
        "peru",
        "bolivia",
        "brazil",
        "paraguay",
        "chile",
        "argentina",
        "uruguay",
    },
    DataRegion.MIDDLE_EAST: {
        "morocco",
        "algeria",
        "tunisia",
        "libya",
        "egypt",
        "sudan",
        "s_sudan",
        "mauritania",
        "w_sahara",
        "jordan",
        "lebanon",
        "israel",
        "palestine",
        "saudi_arabia",
        "united_arab_emirates",
        "qatar",
        "bahrain",
        "kuwait",
        "oman",
        "yemen",
        "iraq",
        "syria",
        "turkey",
        "iran",
        "cyprus",
    },
    DataRegion.EUROPE: {
        "united_kingdom",
        "ireland",
        "france",
        "belgium",
        "netherlands",
        "luxembourg",
        "germany",
        "austria",
        "switzerland",
        "italy",
        "spain",
        "portugal",
        "norway",
        "sweden",
        "finland",
        "denmark",
        "iceland",
        "monaco",
        "andorra",
        "san_marino",
        "liechtenstein",
        "malta",
        "poland",
        "czechia",
        "slovakia",
        "hungary",
        "romania",
        "bulgaria",
        "croatia",
        "slovenia",
        "serbia",
        "bosnia_and_herz",
        "montenegro",
        "albania",
        "macedonia",
        "greece",
        "estonia",
        "latvia",
        "lithuania",
        "ukraine",
        "belarus",
        "moldova",
        "georgia",
        "armenia",
        "azerbaijan",
        "russia",
    },
    DataRegion.ASIA: {
        "china",
        "japan",
        "south_korea",
        "north_korea",
        "india",
        "pakistan",
        "bangladesh",
        "sri_lanka",
        "thailand",
        "vietnam",
        "myanmar",
        "laos",
        "cambodia",
        "malaysia",
        "singapore",
        "brunei",
        "indonesia",
        "philippines",
        "australia",
        "new_zealand",
        "papua_new_guinea",
        "fiji",
        "solomon_is",
        "vanuatu",
        "samoa",
        "timor_leste",
        "mongolia",
        "nepal",
        "bhutan",
        "hong_kong",
        "taiwan",
    },
    DataRegion.AFRICA: set(),
    DataRegion.GLOBAL: set(),
}


REGION_CODE_MAP = {
    "NA": DataRegion.NORTH_AMERICA,
    "NORTH_AMERICA": DataRegion.NORTH_AMERICA,
    "LATAM": DataRegion.LATIN_AMERICA,
    "LATIN_AMERICA": DataRegion.LATIN_AMERICA,
    "MENA": DataRegion.MIDDLE_EAST,
    "MIDDLE_EAST": DataRegion.MIDDLE_EAST,
    "AFRICA": DataRegion.AFRICA,
    "EU": DataRegion.EUROPE,
    "EUROPE": DataRegion.EUROPE,
    "EU_WEST": DataRegion.EUROPE,
    "EU_EAST": DataRegion.EUROPE,
    "PACIFIC": DataRegion.ASIA,
    "ASIA": DataRegion.ASIA,
    "APAC": DataRegion.ASIA,
    "GLOBAL": DataRegion.GLOBAL,
}


def _lookup_country(name: str):
    """Return pycountry record for name using fallbacks."""
    try:
        return pycountry.countries.lookup(name)
    except LookupError:
        sanitized = _sanitize_token(name)
        alt = NAME_OVERRIDES.get(sanitized)
        if alt:
            try:
                return pycountry.countries.lookup(alt)
            except LookupError:
                logger.debug("pycountry lookup failed for alias %s", alt)
        # Try replacing underscores with spaces
        if "_" in sanitized:
            attempt = sanitized.replace("_", " ")
            try:
                return pycountry.countries.lookup(attempt)
            except LookupError:
                pass
    return None


def _tokenize_string(value: str) -> Set[str]:
    token = _sanitize_token(value)
    if not token:
        return set()
    parts = {token, token.replace("_", "")}
    parts.update(filter(None, token.split("_")))
    return parts


@lru_cache(maxsize=512)
def country_tokens(name: str) -> Set[str]:
    """Return comparable tokens for a country name."""
    tokens = set()
    sanitized = _sanitize_token(name)
    if sanitized:
        tokens.add(sanitized)
        tokens.add(sanitized.replace("_", ""))
        tokens.update(TOKEN_OVERRIDES.get(sanitized, set()))

    record = _lookup_country(name)
    if record:
        tokens.update(_tokenize_string(getattr(record, "name", "")))
        tokens.update(_tokenize_string(getattr(record, "official_name", "")))
        tokens.update(_tokenize_string(getattr(record, "common_name", "")))
        tokens.add(getattr(record, "alpha_2", "").lower())
        tokens.add(getattr(record, "alpha_3", "").lower())

    alias = NAME_OVERRIDES.get(sanitized)
    if alias:
        tokens.update(_tokenize_string(alias))

    return {token for token in tokens if token}


@lru_cache(maxsize=512)
def country_regions(name: str) -> Set[DataRegion]:
    """Return DataRegion values associated with the country."""
    sanitized = _sanitize_token(name)
    regions = {region for region, countries in REGION_TO_COUNTRIES.items() if sanitized in countries}
    return regions


def normalize_region_codes(codes: Optional[Iterable[str]]) -> Set[DataRegion]:
    """Convert UI region codes to DataRegion values."""
    normalized: Set[DataRegion] = set()
    if not codes:
        return normalized
    for code in codes:
        if not code:
            continue
        mapped = REGION_CODE_MAP.get(code.strip().upper())
        if mapped:
            normalized.add(mapped)
    return normalized


def extract_item_tokens(item: DataCatalogueItem) -> Set[str]:
    """Extract comparable tokens from a catalogue item."""
    tokens: Set[str] = set()
    tokens.update(_tokenize_string(getattr(item, "code", "")))
    tokens.update(_tokenize_string(getattr(item, "name", "")))

    if getattr(item, "region", None):
        region_value = item.region.value if hasattr(item.region, "value") else str(item.region)
        tokens.update(_tokenize_string(region_value))

    tags = item.tags if isinstance(item.tags, (list, tuple, set)) else []
    for tag in tags:
        if isinstance(tag, str):
            tokens.update(_tokenize_string(tag))

    parameters = item.parameters if isinstance(item.parameters, dict) else {}
    for key, value in parameters.items():
        if isinstance(value, str):
            tokens.update(_tokenize_string(value))
        elif isinstance(value, (list, tuple, set)):
            tokens.update(
                token for entry in value if isinstance(entry, str) for token in _tokenize_string(entry)
            )
        elif isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, str):
                    tokens.update(_tokenize_string(nested))

    if getattr(item, "endpoint", None):
        tokens.update(_tokenize_string(item.endpoint))

    return {token for token in tokens if token}


class CountryMatcher:
    """Determine whether a catalogue item should be collected for the selected filters."""

    def __init__(self, country_names: Optional[Iterable[str]], region_codes: Optional[Iterable[str]] = None):
        self.country_names = [name for name in (country_names or []) if name]
        self.country_tokens: Set[str] = set()
        self.allowed_regions: Set[DataRegion] = normalize_region_codes(region_codes)

        for name in self.country_names:
            self.country_tokens.update(country_tokens(name))
            self.allowed_regions.update(country_regions(name))

        self.active = bool(self.country_tokens or self.allowed_regions)

    def should_collect(self, item: DataCatalogueItem) -> bool:
        """Return True if the item matches the configured filters."""
        if not self.active:
            return True

        item_region = getattr(item, "region", None)
        item_tokens = extract_item_tokens(item)

        if self.country_tokens:
            if self.country_tokens.intersection(item_tokens):
                return True
            # No token match - reject even if region aligns
            return False

        if self.allowed_regions and item_region not in self.allowed_regions:
            return False

        return True

    def describe(self) -> str:
        if not self.active:
            return "no country filter applied"
        parts = []
        if self.country_names:
            parts.append(f"countries={self.country_names}")
        if self.allowed_regions:
            parts.append(f"regions={[region.value for region in self.allowed_regions]}")
        return ", ".join(parts)
