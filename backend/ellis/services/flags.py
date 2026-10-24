"""Flag categories: speed, whether they block the gate, and applicant-facing labels (A6/A7)."""

STOP_NOW = "stop_now"
FLAG_CONTINUE = "flag_continue"

CATEGORIES: dict[str, dict] = {
    "arrest": {"speed": STOP_NOW, "blocks": True, "label_es": None, "label_en": None},
    "removal": {"speed": STOP_NOW, "blocks": True, "label_es": None, "label_en": None},
    "citizenship_claim": {"speed": STOP_NOW, "blocks": True, "label_es": None, "label_en": None},
    "fraud": {"speed": STOP_NOW, "blocks": True, "label_es": None, "label_en": None},
    "danger": {"speed": STOP_NOW, "blocks": True, "label_es": None, "label_en": None},
    "citation": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Multa o citación", "label_en": "Fine or citation"},
    "absence_gt_180": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Viaje de más de seis meses",
                       "label_en": "Trip longer than six months"},
    "absence_gte_365": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Viaje de un año o más",
                        "label_en": "Trip of a year or more"},
    "presence_short": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Tiempo dentro del país",
                       "label_en": "Time inside the country"},
    "residence_short": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Tiempo en su domicilio actual",
                        "label_en": "Time at your current address"},
    "trip_open": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Viaje sin fecha de regreso",
                 "label_en": "Trip with no return date"},
    "name_mismatch": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Diferencia en su nombre",
                      "label_en": "Difference in your name"},
    "date_conflict": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Fecha por confirmar",
                      "label_en": "Date to confirm"},
    "document_conflict": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Documentos que no coinciden",
                          "label_en": "Documents that don't match"},
    "document_owner": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Documento por revisar",
                       "label_en": "Document to review"},
    "taxes": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Impuestos", "label_en": "Taxes"},
    "selective_service": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Registro del servicio selectivo",
                          "label_en": "Selective service registration"},
    "oath_answer": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Preguntas del juramento",
                    "label_en": "Oath questions"},
    "other_path": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Revisión de su tipo de solicitud",
                   "label_en": "Review of your application type"},
    "medical_exception_question": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Pregunta para su clínica",
                                   "label_en": "Question for your clinic"},
    "third_party_answered": {"speed": FLAG_CONTINUE, "blocks": False, "label_es": None, "label_en": None},
    "qa_recompute_mismatch": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": None, "label_en": None},
    "liaison_note": {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Pregunta para su clínica",
                     "label_en": "Question for your clinic"},
}

RULE_TRIGGERS = {
    "absence_gt_180": "Rule R-ABS-180 (layer 2)",
    "absence_gte_365": "Rule R-ABS-365 (layer 2)",
    "presence_short": "Rule R-PP-913 (layer 2)",
    "residence_short": "Rule R-RES-3M (layer 2)",
    "trip_open": "Rule R-TRIP-OPEN (layer 2)",
}

# Decisions a reviewer may record, and which close the item.
DECISIONS = {
    "clear": True,
    "clear_with_referral": True,
    "needs_more_info": False,
    "resolved_by_professional": True,
    "block_case": False,
    "not_about_applicant": True,
}


def category(cat: str) -> dict:
    return CATEGORIES.get(cat, {"speed": FLAG_CONTINUE, "blocks": True, "label_es": "Pregunta para su clínica",
                                "label_en": "Question for your clinic"})
