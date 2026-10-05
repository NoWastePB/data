import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
import pdfplumber


# ============================================================
# CONFIG
# ============================================================

ZIPCODE = os.getenv("OMRIN_ZIPCODE", "9251 LZ")
HOUSE_NUMBER = os.getenv("OMRIN_HOUSENUMBER", "27")
ADDITION = os.getenv("OMRIN_ADDITION", "a")
YEAR = int(os.getenv("OMRIN_YEAR", "2026"))

OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "afvalkalender.json"
PDF_FILE = Path("/tmp/omrin_calendar.pdf")


MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MRT": 3,
    "APR": 4,
    "MEI": 5,
    "JUN": 6,
    "JULI": 7,
    "JUL": 7,
    "AUG": 8,
    "SEPT": 9,
    "SEP": 9,
    "OKT": 10,
    "NOV": 11,
    "DEC": 12,
}


CATEGORY_NAMES = {
    "Sortibak": "sortibak",
    "Biobak": "biobak",
    "Oud papier en karton": "oud_papier",
    "Chemisch afval": "chemisch_afval",
    "Takken en snoeiafval": "takken_en_snoeiafval",
}


# ============================================================
# URL
# ============================================================

def build_url():
    return (
        "https://www.omrin.nl/api/CalendarPdf"
        f"?zipCode={ZIPCODE.replace(' ', '%20')}"
        f"&houseNumber={HOUSE_NUMBER}"
        f"&addition={ADDITION}"
        f"&year={YEAR}"
    )


# ============================================================
# PDF DOWNLOAD
# ============================================================

def download_pdf():

    url = build_url()

    print(f"Downloaden: {url}")

    response = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; OmrinCalendarBot/1.0)"
            )
        },
    )

    response.raise_for_status()

    if not response.content.startswith(b"%PDF"):
        raise RuntimeError(
            "Omrin heeft geen geldige PDF teruggegeven."
        )

    PDF_FILE.write_bytes(response.content)

    print(
        f"PDF opgeslagen: {PDF_FILE} "
        f"({len(response.content)} bytes)"
    )


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def normalize_category(value):

    value = normalize_text(value)

    return CATEGORY_NAMES.get(
        value
    )


def is_day(value):

    if value is None:
        return False

    value = normalize_text(value)

    return re.fullmatch(
        r"\d{1,2}\*?",
        value
    ) is not None


def parse_day(value):

    value = normalize_text(value)

    match = re.match(
        r"(\d{1,2})(\*)?",
        value
    )

    if not match:
        return None, False

    day = int(match.group(1))
    changed = bool(match.group(2))

    if day < 1 or day > 31:
        return None, changed

    return day, changed


# ============================================================
# MONTH COLUMNS
# ============================================================

def find_month_columns(words):

    """
    Zoek de X-positie van de maanden bovenaan de kalender.

    Hierdoor zijn we niet afhankelijk van de tabelstructuur
    die Omrin in de PDF gebruikt.
    """

    months = {}

    for word in words:

        text = normalize_text(
            word.get("text")
        ).upper()

        if text not in MONTHS:
            continue

        month = MONTHS[text]

        x = (
            float(word["x0"])
            + float(word["x1"])
        ) / 2

        months[month] = x

    return months


# ============================================================
# CATEGORY POSITIONS
# ============================================================

def find_category_words(words):

    categories = []

    for index, word in enumerate(words):

        text = normalize_text(
            word.get("text")
        )

        if text in CATEGORY_NAMES:
            categories.append({
                "index": index,
                "category": text,
                "normalized": CATEGORY_NAMES[text],
                "x": (
                    float(word["x0"])
                    + float(word["x1"])
                ) / 2,
                "top": float(word["top"]),
            })

    return categories


# ============================================================
# NEAREST MONTH
# ============================================================

def nearest_month(x, month_columns):

    if not month_columns:
        return None

    return min(
        month_columns.keys(),
        key=lambda month: abs(
            month_columns[month] - x
        )
    )


# ============================================================
# DATE VALIDATION
# ============================================================

def make_date(month, day):

    try:

        return datetime(
            YEAR,
            month,
            day
        ).strftime("%Y-%m-%d")

    except ValueError:

        return None


# ============================================================
# EXTRACT CALENDAR
# ============================================================

def extract_calendar():

    result = {
        category: []
        for category in CATEGORY_NAMES.values()
    }

    with pdfplumber.open(PDF_FILE) as pdf:

        # Alleen pagina 1 bevat de kalender.
        page = pdf.pages[0]

        words = page.extract_words(
            keep_blank_chars=False,
            use_text_flow=False
        )

        print(
            f"{len(words)} tekstobjecten gevonden"
        )

        # ----------------------------------------------------
        # MAANDEN
        # ----------------------------------------------------

        month_columns = find_month_columns(
            words
        )

        print()
        print("Maandkolommen:")

        for month, x in sorted(
            month_columns.items()
        ):
            print(
                f"  {month:02d}: x={x:.2f}"
            )

        if len(month_columns) < 12:

            raise RuntimeError(
                "Niet alle 12 maandkolommen "
                "konden worden gevonden."
            )

        # ----------------------------------------------------
        # CATEGORIEËN
        # ----------------------------------------------------

        category_words = find_category_words(
            words
        )

        print()
        print(
            f"{len(category_words)} "
            "categorie-labels gevonden"
        )

        # ----------------------------------------------------
        # PER CATEGORIE
        # ----------------------------------------------------

        for category_info in category_words:

            category = category_info["normalized"]

            category_x = category_info["x"]
            category_top = category_info["top"]

            # Zoek alle dagwaarden die:
            #
            # 1. onder het categorie-label staan
            # 2. ongeveer dezelfde horizontale tabel gebruiken
            #
            # We beperken de verticale range om te voorkomen
            # dat de volgende afvalcategorie wordt meegenomen.

            candidates = []

            for word in words:

                top = float(
                    word["top"]
                )

                if top <= category_top:
                    continue

                text = normalize_text(
                    word.get("text")
                )

                if not is_day(text):
                    continue

                x = (
                    float(word["x0"])
                    + float(word["x1"])
                ) / 2

                candidates.append({
                    "text": text,
                    "x": x,
                    "top": top,
                })

            # ------------------------------------------------
            # STOP BIJ VOLGENDE CATEGORIE
            # ------------------------------------------------

            next_categories = [
                c["top"]
                for c in category_words
                if c["top"] > category_top
            ]

            if next_categories:

                next_category_top = min(
                    next_categories
                )

                candidates = [
                    c
                    for c in candidates
                    if c["top"] < next_category_top
                ]

            # ------------------------------------------------
            # DATUMS KOPPELEN AAN MAAND
            # ------------------------------------------------

            for candidate in candidates:

                day, changed = parse_day(
                    candidate["text"]
                )

                if day is None:
                    continue

                month = nearest_month(
                    candidate["x"],
                    month_columns
                )

                if month is None:
                    continue

                date = make_date(
                    month,
                    day
                )

                if date is None:
                    continue

                result[category].append({
                    "date": date,
                    "day": day,
                    "month": month,
                    "changed": changed,
                })

    return result


# ============================================================
# DUPLICATES
# ============================================================

def remove_duplicates(data):

    for category in data:

        unique = {}

        for item in data[category]:

            key = (
                item["date"],
                item["changed"]
            )

            unique[key] = item

        data[category] = list(
            unique.values()
        )

        data[category].sort(
            key=lambda item: item["date"]
        )

    return data


# ============================================================
# VALIDATE
# ============================================================

def validate_data(data):

    total = sum(
        len(values)
        for values in data.values()
    )

    print()
    print("=" * 60)
    print("RESULTAAT")
    print("=" * 60)

    for category, dates in data.items():

        print(
            f"{category:25} "
            f"{len(dates):3} ophaaldagen"
        )

    print("-" * 60)
    print(
        f"Totaal: {total} ophaaldagen"
    )

    if total == 0:

        raise RuntimeError(
            "Er zijn 0 ophaaldagen gevonden. "
            "De PDF-layout is mogelijk gewijzigd."
        )


# ============================================================
# JSON
# ============================================================

def save_json(data):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    output = {
        "source": build_url(),

        "year": YEAR,

        "address": {
            "zipcode": ZIPCODE,
            "house_number": HOUSE_NUMBER,
            "addition": ADDITION,
        },

        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "collections": data,
    }

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(
        f"JSON opgeslagen: {OUTPUT_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("OMRIN AFVALKALENDER")
    print("=" * 60)

    print(
        f"Postcode:     {ZIPCODE}"
    )

    print(
        f"Huisnummer:   {HOUSE_NUMBER}"
    )

    print(
        f"Toevoeging:   {ADDITION}"
    )

    print(
        f"Jaar:         {YEAR}"
    )

    print()

    download_pdf()

    data = extract_calendar()

    data = remove_duplicates(
        data
    )

    validate_data(
        data
    )

    save_json(
        data
    )

    print()
    print("Klaar!")


if __name__ == "__main__":
    main()
