"""Haalt de Omrin afvalkalender op en schrijft data/afvalkalender.json."""
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path

import requests
from pypdf import PdfReader

ZIPCODE = os.getenv("OMRIN_ZIPCODE", "9251 LZ")
HOUSE_NUMBER = os.getenv("OMRIN_HOUSENUMBER", "27")
ADDITION = os.getenv("OMRIN_ADDITION", "a")
YEAR = int(os.getenv("OMRIN_YEAR", "2026"))

API_URL = "https://www.omrin.nl/api/CalendarPdf"
OUTPUT_FILE = Path("data/afvalkalender.json")

# json-key -> label in de pdf
CATEGORIES = {
    "sortibak": "Sortibak",
    "biobak": "Biobak",  # GFT
    "oud_papier": "Oud papier en karton",
    "chemisch_afval": "Chemisch afval",
}

MONTH_NAMES = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def download_pdf_text():
    response = requests.get(
        API_URL,
        params={
            "zipCode": ZIPCODE,
            "houseNumber": HOUSE_NUMBER,
            "addition": ADDITION,
            "year": YEAR,
        },
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 (compatible; OmrinCalendarBot/1.0)"},
    )
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError("Omrin heeft geen geldige PDF teruggegeven.")
    reader = PdfReader(BytesIO(response.content))
    return "\n".join(page.extract_text() or "" for page in reader.pages), response.url


def day_tokens(text, label):
    """Eerste keer dat `label` direct gevolgd wordt door dagnummers (bv. '07*').

    Zinnen als 'Zet de Biobak op de aangegeven datum' worden zo overgeslagen,
    omdat daar geen getal achter het label staat.
    """
    match = re.search(re.escape(label) + r"\s+((?:\d{1,2}\*?\s+)+)", text)
    if not match:
        raise RuntimeError(f"Geen datums gevonden voor '{label}'.")
    return re.findall(r"(\d{1,2})(\*?)", match.group(1))


def to_dates(tokens, label):
    """De dagnummers staan in kalendervolgorde. Een nieuwe maand begint zodra
    een dagnummer niet groter is dan het vorige."""
    month, previous, result = 1, 0, []
    for day_text, star in tokens:
        day = int(day_text)
        if day <= previous:
            month += 1
        previous = day
        if month > 12:
            raise RuntimeError(f"{label}: meer dan 12 maanden herkend.")
        d = date(YEAR, month, day)
        result.append({
            "date": d.isoformat(),
            "day": day,
            "month": month,
            "month_name": MONTH_NAMES[month - 1],
            "weekday": d.strftime("%A").lower(),
            "changed": bool(star),
        })
    return result


def validate(collections):
    """Een ophaaldag valt normaliter steeds op dezelfde weekdag. Wijkt een
    niet-gewijzigde datum af, dan is er iets mis met de parsing."""
    for key, items in collections.items():
        if not items:
            raise RuntimeError(f"Geen datums voor {key}.")
        normal = [i["weekday"] for i in items if not i["changed"]]
        usual = Counter(normal).most_common(1)[0][0]
        for item in items:
            if not item["changed"] and item["weekday"] != usual:
                raise RuntimeError(
                    f"{key}: {item['date']} valt op {item['weekday']}, "
                    f"verwacht {usual}. Controleer de parsing."
                )


def parse(text):
    collections = {}
    for key, label in CATEGORIES.items():
        collections[key] = to_dates(day_tokens(text, label), key)
    validate(collections)
    return collections


def main():
    text, source = download_pdf_text()
    collections = parse(text)

    output = {
        "source": source,
        "year": YEAR,
        "address": {
            "zipcode": ZIPCODE,
            "house_number": HOUSE_NUMBER,
            "addition": ADDITION,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "collections": collections,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for key, items in collections.items():
        print(f"{key:<15} {len(items):>3} datums")
    print(f"Opgeslagen: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
