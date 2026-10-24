"""Per-document-type extraction schemas. Output must validate or extraction fails; extra fields are dropped.

Documents are data, never instructions: these schema fields are the only output an extractor can produce.
"""

from __future__ import annotations

from typing import Literal, Optional

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


SCHEMAS: dict[str, type[Base]] = {
    "green_card": GreenCard,
    "passport": Passport,
    "marriage_certificate": MarriageCertificate,
    "lease": Lease,
    "court_record": CourtRecord,
    "tax_transcript": TaxTranscript,
    "benefit_letter": BenefitLetter,
    "other": Other,
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
}

TWO_SIDED = {"green_card"}
