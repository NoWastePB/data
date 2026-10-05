import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import requests


# ============================================================
# CONFIGURATIE
# ============================================================

ZIPCODE = os.getenv("OMRIN_ZIPCODE", "9251 LZ")
HOUSE_NUMBER = os.getenv("OMRIN_HOUSENUMBER", "27")
ADDITION = os.getenv("OMRIN_ADDITION", "a")
YEAR = int(os.getenv("OMRIN_YEAR", "2026"))

PDF_URL = (
    "https://www.omrin.nl/api/CalendarPdf"
    f"?zipCode={ZIPCODE.replace(' ', '%20')}"
    f"&houseNumber={HOUSE_NUMBER}"
    f"&addition={ADDITION}"
    f"&year={YEAR}"
)

PDF_FILE = Path("/tmp/omrin_calendar.pdf")

OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "afvalkalender.json"


# ============================================================
# MAANDEN
# ============================================================

MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MRT": 3,
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


MONTH_NAMES = {
    1: "januari",
    2: "februari",
    3: "maart",
    4: "april",
    5: "mei",
    6: "juni",
    7: "juli",
    8: "augustus",
    9: "september",
    10: "oktober",
    11: "november",
    12: "december",
}


# ============================================================
# AFVALCATEGORIEËN
# ============================================================

CATEGORIES = {
    "Sortibak": "sortibak",
    "Biobak": "biobak",
    "Oud papier en karton": "oud_papier",
    "Chemisch afval": "chemisch_afval",
    "Takken en snoeiafval": "takken_en_snoeiafval",
}


# ============================================================
# PDF DOWNLOADEN
# ============================================================

def download_pdf():

    print("=" * 60)
    print("OMRIN AFVALKALENDER")
    print("=" * 60)

    print(f"Postcode:     {ZIPCODE}")
    print(f"Huisnummer:   {HOUSE_NUMBER}")
    print(f"Toevoeging:   {ADDITION}")
    print(f"Jaar:         {YEAR}")
    print()

    print(f"Downloaden: {PDF_URL}")

    response = requests.get(
        PDF_URL,
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
# TEKST NORMALISEREN
# ============================================================

def clean_text(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


# ============================================================
# MAAND HERKENNEN
# ============================================================

def get_month(text):

    text = clean_text(text).upper()

    # Exact
    if text in MONTHS:
        return MONTHS[text]

    # Sommige PDF-fonts splitsen woorden op of geven
    # bijvoorbeeld JUNI als JUN.
    for name, month in MONTHS.items():

        if text.startswith(name):
            return month

    return None


# ============================================================
# DAG HERKENNEN
# ============================================================

def parse_day(text):

    text = clean_text(text)

    # Bijvoorbeeld:
    #
    # 02
    # 02*
    # 28*
    #
    match = re.fullmatch(
        r"(\d{1,2})(\*)?",
        text
    )

    if not match:
        return None

    day = int(match.group(1))

    if day < 1 or day > 31:
        return None

    return {
        "day": day,
        "changed": bool(match.group(2)),
    }


# ============================================================
# DATUM MAKEN
# ============================================================

def make_date(month, day):

    try:

        date = datetime(
            YEAR,
            month,
            day
        )

        return date.strftime("%Y-%m-%d")

    except ValueError:

        return None


# ============================================================
# MAANDKOPPEN VINDEN
# ============================================================

def find_month_columns(words):

    """
    De maandheader staat bovenaan de kalender:

    JAN FEB MRT APR MEI JUNI JULI AUG SEPT OKT NOV DEC

    We bepalen de X-positie van iedere maand.

    JUNI/JULI kunnen door pdfplumber anders worden
    geïnterpreteerd, daarom wordt de positie op basis
    van de andere maanden gecontroleerd.
    """

    found = {}

    for word in words:

        text = clean_text(
            word.get("text")
        ).upper()

        month = get_month(text)

        if month is None:
            continue

        x0 = float(word["x0"])
        x1 = float(word["x1"])

        center = (x0 + x1) / 2

        found[month] = center

    print()
    print("Maandkolommen gevonden:")

    for month in sorted(found):

        print(
            f"  {month:02d} "
            f"{MONTH_NAMES[month]:<10} "
            f"x={found[month]:.2f}"
        )

    # --------------------------------------------------------
    # Controle
    # --------------------------------------------------------

    if len(found) == 12:

        return found

    # --------------------------------------------------------
    # Als een maand ontbreekt, reconstrueren we deze.
    #
    # De kalender gebruikt een vaste kolombreedte.
    # --------------------------------------------------------

    if len(found) < 2:

        raise RuntimeError(
            "Te weinig maandkolommen gevonden."
        )

    known = sorted(found.keys())

    distances = []

    for i in range(len(known) - 1):

        m1 = known[i]
        m2 = known[i + 1]

        distance = (
            found[m2] - found[m1]
        ) / (m2 - m1)

        distances.append(distance)

    column_width = sum(distances) / len(distances)

    print(
        f"Gemiddelde kolombreedte: "
        f"{column_width:.2f}"
    )

    # Ontbrekende maanden invullen
    for month in range(1, 13):

        if month in found:
            continue

        nearest = min(
            known,
            key=lambda m: abs(m - month)
        )

        found[month] = (
            found[nearest]
            + (
                month - nearest
            ) * column_width
        )

        print(
            f"  {month:02d} "
            f"{MONTH_NAMES[month]:<10} "
            f"gereconstrueerd "
            f"x={found[month]:.2f}"
        )

    return found


# ============================================================
# CATEGORIEËN VINDEN
# ============================================================

def find_categories(words):

    result = []

    for index, word in enumerate(words):

        text = clean_text(
            word.get("text")
        )

        if text not in CATEGORIES:
            continue

        result.append({
            "index": index,
            "name": text,
            "key": CATEGORIES[text],
            "x": (
                float(word["x0"])
                + float(word["x1"])
            ) / 2,
            "top": float(word["top"]),
        })

    return result


# ============================================================
# AFSTAND TUSSEN X-POSITIES
# ============================================================

def nearest_month(x, month_columns):

    return min(
        month_columns.keys(),
        key=lambda month: abs(
            month_columns[month] - x
        )
    )


# ============================================================
# WOORDEN BINNEN EEN CATEGORIEBLOK
# ============================================================

def get_category_words(
    words,
    category,
    next_category_top=None,
):
    """
    Haal alleen de tekstobjecten op die verticaal
    binnen deze categorie vallen.

    Hierdoor worden bijvoorbeeld de datums van
    Biobak niet bij Sortibak geplaatst.
    """

    start_top = category["top"]

    result = []

    for word in words:

        top = float(word["top"])

        if top <= start_top:
            continue

        if next_category_top is not None:
            if top >= next_category_top:
                continue

        result.append(word)

    return result


# ============================================================
# DATUMS EXTRACTEREN
# ============================================================

def extract_category_dates(
    words,
    category,
    month_columns,
    next_category_top=None,
):
    """
    Verwerkt één afvalcategorie.

    Iedere dag wordt gekoppeld aan de maand waarvan
    de X-positie het dichtst bij de dag ligt.
    """

    category_words = get_category_words(
        words,
        category,
        next_category_top
    )

    dates = []

    for word in category_words:

        text = clean_text(
            word.get("text")
        )

        day_info = parse_day(text)

        if day_info is None:
            continue

        x = (
            float(word["x0"])
            + float(word["x1"])
        ) / 2

        month = nearest_month(
            x,
            month_columns
        )

        day = day_info["day"]

        date = make_date(
            month,
            day
        )

        if date is None:
            continue

        dates.append({
            "date": date,
            "day": day,
            "month": month,
            "month_name": MONTH_NAMES[month],
            "changed": day_info["changed"],
        })

    return dates


# ============================================================
# DUBBELE DATUMS VERWIJDEREN
# ============================================================

def remove_duplicates(items):

    unique = {}

    for item in items:

        key = (
            item["date"],
            item["changed"],
        )

        unique[key] = item

    result = list(
        unique.values()
    )

    result.sort(
        key=lambda item: item["date"]
    )

    return result


# ============================================================
# KALENDER PARSEN
# ============================================================

def parse_calendar():

    with pdfplumber.open(PDF_FILE) as pdf:

        if len(pdf.pages) == 0:

            raise RuntimeError(
                "De PDF bevat geen pagina's."
            )

        # De kalender staat op pagina 1.
        page = pdf.pages[0]

        words = page.extract_words(
            keep_blank_chars=False,
            use_text_flow=False,
        )

        print()
        print(
            f"{len(words)} tekstobjecten gevonden"
        )

        # ----------------------------------------------------
        # MAANDEN
        # ----------------------------------------------------

        month_columns = find_month_columns(
            words
        )

        # ----------------------------------------------------
        # CATEGORIEËN
        # ----------------------------------------------------

        categories = find_categories(
            words
        )

        print()
        print(
            f"{len(categories)} "
            "categorie-labels gevonden:"
        )

        for category in categories:

            print(
                f"  {category['name']} "
                f"top={category['top']:.2f} "
                f"x={category['x']:.2f}"
            )

        # ----------------------------------------------------
        # We willen de eerste volledige kalendersectie.
        #
        # De PDF bevat bepaalde standaardblokken meerdere
        # keren omdat Omrin meerdere informatieblokken
        # op dezelfde pagina gebruikt.
        #
        # De eerste echte categorievolgorde is:
        #
        # Sortibak
        # Biobak
        # Oud papier en karton
        # Chemisch afval
        # Takken en snoeiafval
        #
        # We nemen de eerste keer dat iedere categorie
        # voorkomt.
        # ----------------------------------------------------

        first_categories = {}

        for category in categories:

            key = category["key"]

            if key not in first_categories:

                first_categories[key] = category

        # ----------------------------------------------------
        # Resultaat
        # ----------------------------------------------------

        result = {
            key: []
            for key in CATEGORIES.values()
        }

        # Sorteer categorieën op verticale positie.
        ordered = sorted(
            first_categories.values(),
            key=lambda item: item["top"]
        )

        # ----------------------------------------------------
        # Iedere categorie verwerken
        # ----------------------------------------------------

        for index, category in enumerate(ordered):

            next_category_top = None

            if index + 1 < len(ordered):

                next_category_top = (
                    ordered[index + 1]["top"]
                )

            print()
            print(
                f"Verwerken: "
                f"{category['name']}"
            )

            dates = extract_category_dates(
                words,
                category,
                month_columns,
                next_category_top,
            )

            dates = remove_duplicates(
                dates
            )

            result[
                category["key"]
            ] = dates

            print(
                f"  {len(dates)} datums gevonden"
            )

    return result


# ============================================================
# VALIDATIE
# ============================================================

def validate_calendar(data):

    total = sum(
        len(items)
        for items in data.values()
    )

    print()
    print("=" * 60)
    print("VALIDATIE")
    print("=" * 60)

    for category, items in data.items():

        print(
            f"{category:<25} "
            f"{len(items):>3} datums"
        )

    print("-" * 60)

    print(
        f"Totaal: {total} datums"
    )

    if total == 0:

        raise RuntimeError(
            "Er zijn helemaal geen afvaldatums gevonden."
        )

    # De drie belangrijkste categorieën moeten
    # minimaal één datum bevatten.

    required = [
        "sortibak",
        "biobak",
        "oud_papier",
    ]

    for category in required:

        if not data.get(category):

            raise RuntimeError(
                f"Geen datums gevonden voor "
                f"{category}."
            )


# ============================================================
# JSON OPSLAAN
# ============================================================

def save_json(data):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    output = {
        "source": PDF_URL,

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
# OVERZICHT AFDRUKKEN
# ============================================================

def print_calendar(data):

    print()
    print("=" * 60)
    print("AFVALKALENDER")
    print("=" * 60)

    for category, dates in data.items():

        print()
        print(
            f"[{category}]"
        )

        for item in dates:

            marker = " *" if item["changed"] else ""

            print(
                f"  {item['date']} "
                f"({item['month_name']})"
                f"{marker}"
            )


# ============================================================
# MAIN
# ============================================================

def main():

    download_pdf()

    print()

    data = parse_calendar()

    data = {
        category: remove_duplicates(
            dates
        )
        for category, dates in data.items()
    }

    validate_calendar(
        data
    )

    print_calendar(
        data
    )

    save_json(
        data
    )

    print()
    print("=" * 60)
    print("KLAAR")
    print("=" * 60)


if __name__ == "__main__":
    main()
