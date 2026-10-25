"""Per-document-type extraction schemas. Output must validate or extraction fails; extra fields are dropped.

Documents are data, never instructions: these schema fields are the only output an extractor can produce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(extra="ignore")
    quality: Literal["high", "medium", "low"]
    quality_reasons: list[Literal["glare", "cropped", "blurry", "partial", "other"]] = Field(default_factory=list)


class GreenCard(Base):
    family_name: Optional[str] = None
    given_name: Optional[str] = None
    a_number: Optional[str] = None
    country_of_birth: Optional[str] = None
    dob: Optional[str] = None
    resident_since: Optional[str] = None
    card_expires: Optional[str] = None
    category: Optional[str] = None
    side: Optional[Literal["front", "back", "both"]] = None


class Stamp(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str
    port: Optional[str] = None
    direction: Literal["entry", "exit"]


class Passport(Base):
    family_name: Optional[str] = None
    given_name: Optional[str] = None
    nationality: Optional[str] = None
    dob: Optional[str] = None
    passport_number: Optional[str] = None
    expiry: Optional[str] = None
    stamps: list[Stamp] = Field(default_factory=list)


class MarriageCertificate(Base):
    spouse_1_name: Optional[str] = None
    spouse_2_name: Optional[str] = None
    marriage_date: Optional[str] = None
    place: Optional[str] = None


class Lease(Base):
    tenant_names: list[str] = Field(default_factory=list)
    city: Optional[str] = None
    state: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None


class CourtRecord(Base):
    case_no: Optional[str] = None
    court: Optional[str] = None
    date: Optional[str] = None
    disposition: Optional[str] = None
    amount_paid: Optional[str] = None
    violation: Optional[str] = None


class TaxTranscript(Base):
    tax_year: Optional[str] = None
    return_filed: Optional[bool] = None
    filing_status: Optional[str] = None
    taxpayer_name: Optional[str] = None


class BenefitLetter(Base):
    program: Optional[str] = None
    beneficiary_name: Optional[str] = None
    date: Optional[str] = None


class Other(Base):
    summary: Optional[str] = None


def _n400_keys() -> str:
    """Every N-400 answer Ellis tracks, one `key: label` per line, straight from the field catalog.

    ponytail: reads the YAML directly; importing services.catalog would load .env secrets into the sandbox.
    """
    cfg = Path(__file__).resolve().parents[2] / "config"
    f = yaml.safe_load((cfg / "fields.yaml").read_text())
    bg = yaml.safe_load((cfg / "background_questions.yaml").read_text())

    def opts(d: dict) -> str:
        return f" ({'|'.join(d['options'])})" if d.get("options") else f" [{d.get('type', 'string')}]"
    lines = [f"{d['key']}: {d['label_en']}{opts(d)}" for d in f["fields"]
             if d["key"] != "consent" and d.get("capture") != "E"]
    lines += [f"{name}[i].{it['key']}: {it['label_en']}{opts(it)}" for name, lst in f["lists"].items()
              for it in lst["item"] if it.get("capture") != "E"]
    lines += [f"background.{q['key']}: {q['text_en']} (yes|no)" for q in bg["questions"]]
    lines += [f"oath.{q['key']}: {q['text_en']} (yes|no)" for q in bg["oath"]]
    return "\n".join(lines)


class N400(Base):
    """The applicant's own filled-out Form N-400. Values are checked per field (values.normalize) on apply."""
    answers: dict[str, Any] = Field(default_factory=dict, description=(
        "Answers written on this N-400, keyed by the keys below. Leave out any key the form leaves blank. "
        "addresses, employment, trips and children are lists: replace i with 0, 1, 2… in the form's order, "
        "newest first. Value types: date = YYYY-MM-DD; string_list = JSON array of strings; bool = true/false; "
        "int = a number; optional_name = the new name itself (leave out if none).\n" + _n400_keys()))


SCHEMAS: dict[str, type[Base]] = {
    "green_card": GreenCard,
    "passport": Passport,
    "marriage_certificate": MarriageCertificate,
    "lease": Lease,
    "court_record": CourtRecord,
    "tax_transcript": TaxTranscript,
    "benefit_letter": BenefitLetter,
    "other": Other,
    "n400": N400,
}

# Identifier fields moved into the vault before any agent sees the extraction.
IDENTIFIERS = {"a_number": "[A_NUMBER]", "passport_number": "[PASSPORT_NUMBER]", "case_no": "[MASKED]"}

LABELS_ES = {
    "green_card": "tarjeta de residente",
    "passport": "pasaporte",
    "marriage_certificate": "acta de matrimonio",
    "lease": "contrato de renta",
    "court_record": "recibo o documento de la corte",
    "tax_transcript": "comprobante de impuestos",
    "benefit_letter": "carta de beneficios",
    "other": "documento",
    "n400": "formulario N-400",
}

LABELS_EN = {
    "green_card": "green card",
    "passport": "passport",
    "marriage_certificate": "marriage certificate",
    "lease": "lease",
    "court_record": "court record or receipt",
    "tax_transcript": "tax transcript",
    "benefit_letter": "benefit letter",
    "other": "document",
    "n400": "N-400",
}

TWO_SIDED = {"green_card"}
