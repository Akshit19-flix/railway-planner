"""Station name-to-code lookup for major Indian Railway stations."""

from thefuzz import process

STATION_CODES: dict[str, str] = {
    # Delhi NCR
    "new delhi": "NDLS",
    "delhi": "DLI",
    "old delhi": "DLI",
    "delhi junction": "DLI",
    "hazrat nizamuddin": "NZM",
    "nizamuddin": "NZM",
    "anand vihar terminal": "ANVT",
    "anand vihar": "ANVT",
    "delhi sarai rohilla": "DEE",
    "delhi cantt": "DEC",
    # Uttar Pradesh
    "kanpur central": "CNB",
    "kanpur": "CNB",
    "lucknow": "LKO",
    "lucknow charbagh": "LKO",
    "lucknow ne": "LJN",
    "varanasi": "BSB",
    "varanasi junction": "BSB",
    "allahabad": "ALD",
    "prayagraj": "ALD",
    "prayagraj junction": "ALD",
    "agra cantt": "AGC",
    "agra": "AGC",
    "agra fort": "AF",
    "mathura": "MTJ",
    "mathura junction": "MTJ",
    "gorakhpur": "GKP",
    "jhansi": "JHS",
    "bareilly": "BE",
    "moradabad": "MB",
    "saharanpur": "SRE",
    # Rajasthan
    "jaipur": "JP",
    "jodhpur": "JU",
    "udaipur city": "UDZ",
    "udaipur": "UDZ",
    "ajmer": "AII",
    "bikaner": "BKN",
    "kota": "KOTA",
    "alwar": "AWR",
    "bharatpur": "BTE",
    # Punjab & Haryana
    "amritsar": "ASR",
    "ludhiana": "LDH",
    "chandigarh": "CDG",
    "ambala cantt": "UMB",
    "ambala": "UMB",
    "patiala": "PTA",
    "bathinda": "BTI",
    "firozpur": "FZR",
    # Himachal & J&K
    "shimla": "SML",
    "kalka": "KLK",
    "jammu tawi": "JAT",
    "jammu": "JAT",
    "pathankot": "PTK",
    "udhampur": "UHP",
    # Uttarakhand
    "dehradun": "DDN",
    "haridwar": "HW",
    "rishikesh": "RKSH",
    "kathgodam": "KGM",
    # Bihar & Jharkhand
    "patna": "PNBE",
    "patna junction": "PNBE",
    "gaya": "GAYA",
    "dhanbad": "DHN",
    "ranchi": "RNC",
    "tatanagar": "TATA",
    "jamshedpur": "TATA",
    "bokaro": "BKSC",
    "mughal sarai": "MGS",
    "pt deen dayal upadhyaya": "DDU",
    "ddu": "DDU",
    # West Bengal
    "howrah": "HWH",
    "kolkata": "KOAA",
    "sealdah": "SDAH",
    "asansol": "ASN",
    "durgapur": "DGR",
    "kharagpur": "KGP",
    "bardhaman": "BWN",
    "new jalpaiguri": "NJP",
    "siliguri": "SGUJ",
    # Maharashtra
    "mumbai central": "BCT",
    "bombay central": "BCT",
    "mumbai cst": "CSTM",
    "chhatrapati shivaji terminus": "CSTM",
    "cst": "CSTM",
    "lokmanya tilak terminus": "LTT",
    "ltt": "LTT",
    "bandra terminus": "BDTS",
    "dadar": "DR",
    "thane": "TNA",
    "pune": "PUNE",
    "nagpur": "NGP",
    "aurangabad": "AWB",
    "nasik road": "NK",
    "nashik road": "NK",
    "nashik": "NK",
    "solapur": "SUR",
    "kolhapur": "KOP",
    "nanded": "NED",
    "akola": "AK",
    "amravati": "AMI",
    # Gujarat
    "ahmedabad": "ADI",
    "surat": "ST",
    "vadodara": "BRC",
    "baroda": "BRC",
    "rajkot": "RJT",
    "bhavnagar": "BVC",
    "bhuj": "BHUJ",
    "gandhidham": "GIMB",
    # Madhya Pradesh
    "bhopal": "BPL",
    "bhopal junction": "BPL",
    "habibganj": "HBJ",
    "rani kamlapati": "HBJ",
    "indore": "INDB",
    "jabalpur": "JBP",
    "gwalior": "GWL",
    "ujjain": "UJN",
    "ratlam": "RTM",
    # Chhattisgarh
    "raipur": "R",
    "raipur junction": "R",
    "durg": "DURG",
    "bilaspur": "BSP",
    # Karnataka
    "bangalore city": "SBC",
    "ksr bengaluru": "SBC",
    "bengaluru": "SBC",
    "bangalore": "SBC",
    "yeshwantpur": "YPR",
    "bangalore cantt": "BNC",
    "mysuru": "MYS",
    "mysore": "MYS",
    "hubli": "UBL",
    "dharwad": "DWR",
    "belgaum": "BGM",
    "belagavi": "BGM",
    "gulbarga": "GR",
    "kalaburagi": "GR",
    "mangalore central": "MAQ",
    "mangalore": "MAQ",
    "mangaluru central": "MAQ",
    # Tamil Nadu
    "chennai central": "MAS",
    "madras central": "MAS",
    "chennai egmore": "MS",
    "coimbatore": "CBE",
    "madurai": "MDU",
    "trichy": "TPJ",
    "tiruchirappalli": "TPJ",
    "tirunelveli": "TEN",
    "tirupati": "TPTY",
    "nellore": "NLR",
    "erode": "ED",
    "salem": "SA",
    # Kerala
    "ernakulam junction": "ERS",
    "ernakulam": "ERS",
    "cochin": "ERS",
    "kochi": "ERS",
    "thiruvananthapuram central": "TVC",
    "trivandrum central": "TVC",
    "trivandrum": "TVC",
    "thiruvananthapuram": "TVC",
    "thrissur": "TCR",
    "trichur": "TCR",
    "kozhikode": "CLT",
    "calicut": "CLT",
    "kollam": "QLN",
    "palakkad": "PGT",
    # Andhra Pradesh & Telangana
    "hyderabad deccan": "HYB",
    "hyderabad": "HYB",
    "secunderabad": "SC",
    "kacheguda": "KCG",
    "vijayawada": "BZA",
    "visakhapatnam": "VSKP",
    "vizag": "VSKP",
    "guntur": "GNT",
    "rajahmundry": "RJY",
    "warangal": "WL",
    # Odisha
    "bhubaneswar": "BBS",
    "cuttack": "CTC",
    "puri": "PURI",
    "sambalpur": "SBP",
    "rourkela": "ROU",
    # Assam & Northeast
    "guwahati": "GHY",
    "dibrugarh": "DBRG",
    "lumding": "LMG",
    "agartala": "AGTL",
    # Goa
    "madgaon": "MAO",
    "goa": "MAO",
    "vasco da gama": "VSG",
    "margao": "MAO",
}


def find_station_code(name: str) -> tuple[str, str]:
    """
    Resolve a station name to its code.
    Returns (code, display_name). Raises ValueError if no good match.
    """
    name_lower = name.lower().strip()

    if name_lower in STATION_CODES:
        return STATION_CODES[name_lower], name.title()

    choices = list(STATION_CODES.keys())
    match, score = process.extractOne(name_lower, choices)

    if score >= 70:
        return STATION_CODES[match], match.title()

    raise ValueError(
        f"Station '{name}' not found in database. "
        f"Closest match: '{match.title()}' (confidence: {score}%). "
        f"Try a more specific name or use the 3-5 letter station code directly (e.g. NDLS)."
    )


def is_station_code(value: str) -> bool:
    """Return True if the value looks like a raw station code (all uppercase letters)."""
    return value.strip().isupper() and value.strip().isalpha() and len(value.strip()) <= 5
