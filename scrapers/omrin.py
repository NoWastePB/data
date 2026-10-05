import os
import json
import re
from datetime import datetime
from pathlib import Path

import requests
import pdfplumber


# ============================================================
# CONFIGURATIE
# ============================================================

ZIPCODE = os.getenv("OMrin_ZIPCODE", "9251 LZ")
HOUSE_NUMBER = os.getenv("OMrin_HOUSENUMBER", "27")
ADDITION = os.getenv("OMrin_ADDITION", "a")
YEAR = int(os.getenv("OMrin_YEAR", datetime.now().year))

OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "afvalkalender.json"

PDF_FILE = Path("/tmp/omrin_calendar.pdf")

MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MRT": 3,
    "MAA": 3,
    "APR": 4,
    "MEI": 5,
    "JUN": 6,
    "JUNI": 6,
    "JUL": 7,
    "JULI": 7,
    "AUG": 8,
    "SEP": 9,
    "SEPT": 9,
    "OKT": 10,
    "NOV": 11,
    "DEC": 12,
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
# PDF DOWNLOADEN
# ============================================================

def download_pdf():
    url = build_url()

    print(f"Downloaden: {url}")

    response = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": "Mozilla/5.0 GitHubActions Omrin Scraper"
        },
    )

    response.raise_for_status()

    content_type = response.headers.get("content-type", "")

    if "pdf" not in content_type.lower():
        raise RuntimeError(
            f"Omrin gaf geen PDF terug. Content-Type: {content_type}"
        )

    PDF_FILE.write_bytes(response.content)

    print(f"PDF opgeslagen: {PDF_FILE}")
    print(f"Grootte: {len(response.content)} bytes")


# ============================================================
# HULPFUNCTIES
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_category(category):
    category = clean_text(category).lower()

    mappings = {
        "sortibak": "sortibak",
        "biobak": "biobak",
        "gft afval": "gft",
        "gft": "gft",
        "oud papier en karton": "oud_papier",
        "papier en karton": "oud_papier",
        "chemisch afval": "chemisch_afval",
        "klein chemisch afval": "chemisch_afval",
        "grofvuil": "grofvuil",
        "snoeiafval": "snoeiafval",
        "takken en snoeiafval": "takken_en_snoeiafval",
    }

    return mappings.get(category, category)


def extract_day(value):
    """
    Haalt een dagnummer uit bijvoorbeeld:

        02
        02*
        02 *
        02 (gewijzigd)

    Retourneert:
        2
    """

    if value is None:
        return None

    value = clean_text(value)

    match = re.search(r"\b(\d{1,2})\b", value)

    if not match:
        return None

    day = int(match.group(1))

    if day < 1 or day > 31:
        return None

    return day


def is_changed_date(value):
    """
    Omrin gebruikt * voor gewijzigde inzameldagen.
    """

    if value is None:
        return False

    return "*" in str(value)


# ============================================================
# DATUM MAKEN
# ============================================================

def create_date(month, day):
    try:
        return datetime(
            YEAR,
            month,
            day
        ).strftime("%Y-%m-%d")
    except ValueError:
        return None


# ============================================================
# PDF PARSEN
# ============================================================

def parse_pdf():
    result = {}

    with pdfplumber.open(PDF_FILE) as pdf:

        print(f"PDF heeft {len(pdf.pages)} pagina('s)")

        for page_number, page in enumerate(pdf.pages, start=1):

            print(f"Pagina {page_number} verwerken...")

            tables = page.extract_tables()

            print(f"  {len(tables)} tabel(len) gevonden")

            for table_number, table in enumerate(tables, start=1):

                if not table:
                    continue

                process_table(
                    table,
                    result,
                    page_number,
                    table_number
                )

    return result


# ============================================================
# TABEL VERWERKEN
# ============================================================

def process_table(table, result, page_number, table_number):

    if not table:
        return

    # Zoek de rij waarin de maanden staan
    month_row_index = None
    month_columns = {}

    for row_index, row in enumerate(table):

        if not row:
            continue

        for column_index, cell in enumerate(row):

            text = clean_text(cell).upper()

            if text in MONTHS:
                month_row_index = row_index
                month_columns[column_index] = MONTHS[text]

        if len(month_columns) >= 3:
            break

    if not month_columns:
        return

    print(
        f"  Tabel {table_number}: "
        f"maanden gevonden: {month_columns}"
    )

    # Alle rijen onder de maandheader verwerken
    for row in table[month_row_index + 1:]:

        if not row:
            continue

        if len(row) < 2:
            continue

        category = clean_text(row[0])

        if not category:
            continue

        normalized = normalize_category(category)

        # Sommige PDF-tabellen bevatten instructietekst.
        # Alleen bekende afvalcategorieën verwerken.
        known_categories = {
            "sortibak",
            "biobak",
            "gft",
            "oud_papier",
            "chemisch_afval",
            "grofvuil",
            "snoeiafval",
            "takken_en_snoeiafval",
        }

        if normalized not in known_categories:
            continue

        if normalized not in result:
            result[normalized] = []

        for column_index, month in month_columns.items():

            if column_index >= len(row):
                continue

            value = clean_text(row[column_index])

            if not value:
                continue

            # Een cel kan meerdere dagen bevatten.
            days = re.findall(r"\d{1,2}\*?", value)

            for day_value in days:

                day = extract_day(day_value)

                if day is None:
                    continue

                date = create_date(month, day)

                if date is None:
                    continue

                result[normalized].append({
                    "date": date,
                    "day": day,
                    "month": month,
                    "changed": is_changed_date(day_value),
                })


# ============================================================
# DUPLICATEN VERWIJDEREN
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

        data[category] = list(unique.values())

        data[category].sort(
            key=lambda x: x["date"]
        )

    return data


# ============================================================
# JSON OPSLAAN
# ============================================================

def save_json(collections):

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
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "collections": collections,
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
    print(f"JSON opgeslagen: {OUTPUT_FILE}")


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("OMRIN AFVALKALENDER")
    print("=" * 60)

    print(f"Postcode:     {ZIPCODE}")
    print(f"Huisnummer:   {HOUSE_NUMBER}")
    print(f"Toevoeging:   {ADDITION}")
    print(f"Jaar:         {YEAR}")
    print()

    download_pdf()

    collections = parse_pdf()

    collections = remove_duplicates(
        collections
    )

    save_json(collections)

    print()
    print("Gevonden categorieën:")

    for category, dates in collections.items():

        print(
            f"  {category}: "
            f"{len(dates)} ophaaldagen"
        )

    print()
    print("Klaar!")


if __name__ == "__main__":
    main()
