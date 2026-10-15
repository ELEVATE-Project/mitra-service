
INDIA_STATES = [
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
]

INDIA_STATES_NORMALIZED = {s.lower(): s for s in INDIA_STATES}


def get_canonical_state(value: str):
    """
    Return the canonical state name for a given input (case-insensitive),
    or None if not found.
    """
    if not value:
        return None
    return INDIA_STATES_NORMALIZED.get(value.strip().lower())
