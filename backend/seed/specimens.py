"""Generate synthetic specimen document images and their pinned extraction fixtures.

Every image is stamped "SPECIMEN — NOT A REAL DOCUMENT". The extraction worker matches uploads by sha256
against seed/fixtures/extractions.json, so the demo runs without a vision model.

    python -m seed.specimens
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
DOCS = HERE / "documents"
FIXTURES = HERE / "fixtures" / "extractions.json"


def _font(size: int):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def card(title: str, lines: list[str], color=(214, 232, 222), size=(900, 560), glare: bool = False) -> bytes:
    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, size[0] - 10, size[1] - 10], outline=(40, 60, 80), width=4)
    d.text((40, 30), title, fill=(20, 30, 60), font=_font(34))
    y = 100
    for ln in lines:
        d.text((40, y), ln, fill=(20, 20, 20), font=_font(26))
        y += 44
    banner = Image.new("RGBA", size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(banner)
    bd.text((60, size[1] // 2 - 30), "SPECIMEN — NOT A REAL DOCUMENT", fill=(200, 0, 0, 150), font=_font(44))
    banner = banner.rotate(12, expand=False)
    img = Image.alpha_composite(img.convert("RGBA"), banner).convert("RGB")
    if glare:
        g = Image.new("L", size, 0)
        gd = ImageDraw.Draw(g)
        gd.ellipse([250, 120, 900, 420], fill=255)
        g = g.filter(ImageFilter.GaussianBlur(40))
        white = Image.new("RGB", size, (255, 255, 255))
        img = Image.composite(white, img, g)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()


SPECS = {
    # María (pre-extracted at seed)
    "maria_green_card.png": ("green_card", card("PERMANENT RESIDENT CARD (SPECIMEN)", [
        "Surname: TORRES", "Given Name: MARIA", "USCIS#: A-123-456-789", "Country of Birth: Mexico",
        "Date of Birth: 02 MAY 1988", "Resident Since: 01/15/2022", "Card Expires: 01/15/2032", "Category: IR6"]),
        {"quality": "high", "quality_reasons": [], "family_name": "TORRES", "given_name": "MARIA",
         "a_number": "A123456789", "country_of_birth": "Mexico", "dob": "1988-05-02",
         "resident_since": "2022-01-15", "card_expires": "2032-01-15", "category": "IR6", "side": "both"}),
    "maria_passport.png": ("passport", card("PASAPORTE / PASSPORT (SPECIMEN)", [
        "Apellidos: TORRES", "Nombres: MARIA", "Nacionalidad: MEXICANA", "Fecha de nacimiento: 02 05 1988",
        "No. de pasaporte: G12345678", "US CBP ADMITTED  MAR 13 2024  SAN YSIDRO"], color=(200, 214, 230)),
        {"quality": "high", "quality_reasons": [], "family_name": "TORRES", "given_name": "MARIA",
         "nationality": "Mexico", "dob": "1988-05-02", "passport_number": "G12345678", "expiry": "2031-06-30",
         "stamps": [{"date": "2024-03-13", "port": "San Ysidro", "direction": "entry"}]}),
    "maria_lease.png": ("lease", card("RESIDENTIAL LEASE (SPECIMEN)", [
        "Tenants: Maria Torres, Luis Torres", "Premises: Salinas, CA 93901", "Term: 11/01/2021 to present",
        "Monthly rent: $1,850"], color=(240, 236, 220)),
        {"quality": "high", "quality_reasons": [], "tenant_names": ["Maria Torres", "Luis Torres"],
         "city": "Salinas", "state": "CA", "start": "2021-11-01", "end": None}),
    "maria_court_receipt.png": ("court_record", card("SUPERIOR COURT OF CALIFORNIA, COUNTY OF MONTEREY (SPECIMEN)", [
        "Traffic citation  Case No. TR-2023-0042177", "Violation: VC 22350 speeding",
        "Paid in full: $238.00  on 07/21/2023", "Disposition: bail forfeited / paid"], color=(235, 235, 235)),
        {"quality": "high", "quality_reasons": [], "case_no": "TR-2023-0042177", "court": "Monterey County Superior Court",
         "date": "2023-07-21", "disposition": "paid", "amount_paid": "238.00", "violation": "speeding"}),
    "maria_tax_2023.png": ("tax_transcript", card("IRS TAX RETURN TRANSCRIPT 2023 (SPECIMEN)", [
        "Taxpayer: MARIA TORRES", "Tax period: Dec 31, 2023", "Filing status: Married filing jointly",
        "Return received: 04/02/2024"], color=(236, 240, 246)),
        {"quality": "high", "quality_reasons": [], "tax_year": "2023", "return_filed": True,
         "filing_status": "married_filing_jointly", "taxpayer_name": "Maria Torres"}),
    # Ana Lucía (uploaded during the call)
    "ana_green_card_glare.png": ("green_card", card("PERMANENT RESIDENT CARD (SPECIMEN)", [
        "Surname: HERNANDEZ RUIZ", "Given Name: ANA LUCIA", "USCIS#: A-098-765-432", "Country of Birth: Mexico",
        "Date of Birth: 11 SEP 1995", "Resident Since: 06/02/2020", "Card Expires: 06/02/2030"], glare=True),
        {"quality": "low", "quality_reasons": ["glare"], "family_name": "HERNANDEZ RUIZ", "given_name": "ANA LUCIA",
         "a_number": None, "country_of_birth": "Mexico", "dob": None, "resident_since": None}),
    "ana_green_card_clear.png": ("green_card", card("PERMANENT RESIDENT CARD (SPECIMEN)", [
        "Surname: HERNANDEZ RUIZ", "Given Name: ANA LUCIA", "USCIS#: A-098-765-432", "Country of Birth: Mexico",
        "Date of Birth: 11 SEP 1995", "Resident Since: 06/02/2020", "Card Expires: 06/02/2030", "Category: CR6"]),
        {"quality": "high", "quality_reasons": [], "family_name": "HERNANDEZ RUIZ", "given_name": "ANA LUCIA",
         "a_number": "A098765432", "country_of_birth": "Mexico", "dob": "1995-09-11", "resident_since": "2020-06-02",
         "card_expires": "2030-06-02", "category": "CR6", "side": "both"}),
    "ana_marriage_certificate.png": ("marriage_certificate", card("CERTIFICATE OF MARRIAGE, STATE OF CALIFORNIA (SPECIMEN)", [
        "Party A: ANA LUCIA HERNANDEZ RUIZ", "Party B: DANIEL MORALES", "Date of marriage: 04/15/2023",
        "Place: Watsonville, Santa Cruz County"], color=(245, 240, 230)),
        {"quality": "high", "quality_reasons": [], "spouse_1_name": "ANA LUCIA HERNANDEZ RUIZ",
         "spouse_2_name": "DANIEL MORALES", "marriage_date": "2023-04-15", "place": "Watsonville, CA"}),
    "ana_passport.png": ("passport", card("PASAPORTE / PASSPORT (SPECIMEN)", [
        "Apellidos: HERNÁNDEZ RUIZ", "Nombres: ANA LUCÍA", "Nacionalidad: MEXICANA", "No.: G87654321"],
        color=(200, 214, 230)),
        {"quality": "high", "quality_reasons": [], "family_name": "HERNÁNDEZ RUIZ", "given_name": "ANA LUCÍA",
         "nationality": "Mexico", "dob": "1995-09-11", "passport_number": "G87654321", "stamps": []}),
    # Rosa
    "rosa_benefit_letter.png": ("benefit_letter", card("MEDI-CAL BENEFITS NOTICE (SPECIMEN)", [
        "Beneficiary: ROSA DELGADO PEÑA", "Program: Medi-Cal", "Notice date: 01/10/2026",
        "Status: Active"], color=(232, 242, 236)),
        {"quality": "high", "quality_reasons": [], "program": "medi-cal", "beneficiary_name": "Rosa Delgado Peña",
         "date": "2026-01-10"}),
    "rosa_irs_2022.png": ("tax_transcript", card("IRS ACCOUNT TRANSCRIPT 2022 (SPECIMEN)", [
        "Taxpayer: ROSA DELGADO PENA", "Tax period: Dec 31, 2022", "No tax return filed"], color=(236, 240, 246)),
        {"quality": "high", "quality_reasons": [], "tax_year": "2022", "return_filed": False,
         "taxpayer_name": "Rosa Delgado Peña"}),
    "rosa_green_card.png": ("green_card", card("PERMANENT RESIDENT CARD (SPECIMEN)", [
        "Surname: DELGADO PENA", "Given Name: ROSA", "USCIS#: A-045-678-123", "Country of Birth: Mexico",
        "Date of Birth: 14 FEB 1965", "Resident Since: 03/10/2008"]),
        {"quality": "high", "quality_reasons": [], "family_name": "DELGADO PEÑA", "given_name": "ROSA",
         "a_number": "A045678123", "country_of_birth": "Mexico", "dob": "1965-02-14", "resident_since": "2008-03-10",
         "side": "both"}),
    "jorge_green_card.png": ("green_card", card("PERMANENT RESIDENT CARD (SPECIMEN)", [
        "Surname: RAMIREZ SOTO", "Given Name: JORGE", "USCIS#: A-076-543-210", "Country of Birth: Mexico",
        "Date of Birth: 08 AUG 1982", "Resident Since: 05/20/2014"]),
        {"quality": "high", "quality_reasons": [], "family_name": "RAMIREZ SOTO", "given_name": "JORGE",
         "a_number": "A076543210", "country_of_birth": "Mexico", "dob": "1982-08-08", "resident_since": "2014-05-20",
         "side": "both"}),
}


def build() -> dict[str, dict]:
    DOCS.mkdir(parents=True, exist_ok=True)
    FIXTURES.parent.mkdir(parents=True, exist_ok=True)
    reg = {}
    for name, (doc_type, data, extraction) in SPECS.items():
        path = DOCS / name
        path.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        reg[sha] = {"file": name, "document_type": doc_type, "extraction": extraction}
    FIXTURES.write_text(json.dumps(reg, indent=1, ensure_ascii=False))
    return reg


def fixture_for(name: str) -> tuple[str, bytes, dict]:
    doc_type, _, extraction = SPECS[name]
    return doc_type, (DOCS / name).read_bytes(), extraction


if __name__ == "__main__":
    r = build()
    print(f"wrote {len(r)} specimen documents to {DOCS}")
