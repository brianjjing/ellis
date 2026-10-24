"""Synthetic answers for the four demo applicants (all fictional). Used by the seed, the clinic's
"simulate remaining intake" demo button, and the end-to-end flow evals."""

NO_BACKGROUND = {
    "background.claimed_us_citizen": "no", "background.voted_or_registered": "no",
    "background.tax_not_filed": "no", "background.overdue_taxes": "no",
    "background.removal_proceedings": "no", "background.removed_deported": "no",
    "background.arrested_cited_detained": "no", "background.committed_crime_not_arrested": "no",
    "background.false_info_to_official": "no", "background.harmed_or_persecuted": "no",
}
OATH_YES = {"oath.support_constitution": "yes", "oath.understand_oath": "yes", "oath.willing_full_oath": "yes",
            "oath.bear_arms": "yes"}

MARIA = {
    "lpr_since": "2022-01-15", "dob": "1988-05-02", "name.given": "Maria", "name.family": "Torres",
    "country_of_birth": "Mexico",
    "names.used": [], "name_change.requested": None, "nationality": "Mexico",
    "sex": "female", "height": "5 ft 3 in", "weight": "140 lb", "eye_color": "brown", "hair_color": "black",
    "ethnicity": "hispanic_or_latino", "race": "white",
    "contact.phone": "8315550142",
    "addresses[0].city": "Salinas", "addresses[0].state": "CA", "addresses[0].zip": "93901",
    "addresses[0].street": "123 Calle Ejemplo Apt 4", "addresses[0].from": "2021-11-01", "addresses[0].to": "present",
    "addresses[1].city": "Salinas", "addresses[1].state": "CA", "addresses[1].zip": "93905",
    "addresses[1].street": "77 Calle Anterior", "addresses[1].from": "2015-05-01", "addresses[1].to": "2021-11-01",
    "employment[0].employer": "Empacadora del Valle", "employment[0].city": "Salinas",
    "employment[0].occupation": "empacadora", "employment[0].from": "2019-07-01", "employment[0].to": "present",
    "employment[1].employer": "Campos Verdes", "employment[1].city": "Salinas",
    "employment[1].occupation": "trabajadora agrícola", "employment[1].from": "2016-03-01",
    "employment[1].to": "2019-04-30",
    "trips.any": True, "trips[0].departure": "2023-08-03", "trips[0].return": "2024-03-13",
    "trips[0].countries": "México", "trips[0].reason": "cuidar a su madre", "trips[0].home_kept": True,
    "trips[0].another": False,
    "marital.status": "married", "marital.times_married": 1, "spouse.name": "Luis Torres",
    "spouse.dob": "1985-09-20", "spouse.marriage_date": "2010-06-12", "spouse.citizenship_status": "lpr",
    "children.count": 2,
    "children[0].name": "Sofía Torres", "children[0].dob": "2012-03-04", "children[0].residence_city": "Salinas",
    "children[0].relationship": "biological",
    "children[1].name": "Mateo Torres", "children[1].dob": "2015-08-19", "children[1].residence_city": "Salinas",
    "children[1].relationship": "biological",
    **NO_BACKGROUND, "background.arrested_cited_detained": "yes",
    "background.detail.citation_year": "2023", "background.detail.citation_county": "condado de Monterey",
    "background.detail.citation_paid": "pagada",
    **OATH_YES,
    "fee.method": "online",
}

JORGE = {
    "consent": True, "lpr_since": "2014-05-20", "dob": "1982-08-08", "name.given": "Jorge",
    "name.family": "Ramírez Soto", "names.used": [], "name_change.requested": None,
    "country_of_birth": "Mexico", "nationality": "Mexico",
    "trips.any": True, "trips[0].departure": "2022-12-18", "trips[0].return": "2023-01-02",
    "trips[0].countries": "México", "trips[0].reason": "visita familiar", "trips[0].another": True,
    "trips[1].departure": "2024-07-01", "trips[1].return": "2024-07-15", "trips[1].countries": "México",
    "trips[1].reason": "boda de un primo", "trips[1].another": False,
}
JORGE_REST = {
    "sex": "male", "height": "5 ft 8 in", "weight": "180 lb", "eye_color": "brown", "hair_color": "black",
    "ethnicity": "hispanic_or_latino", "race": "white", "contact.phone": "5595550177",
    "addresses[0].city": "Fresno", "addresses[0].state": "CA", "addresses[0].zip": "93701",
    "addresses[0].street": "456 Calle Muestra", "addresses[0].from": "2015-02-01", "addresses[0].to": "present",
    "employment[0].employer": "Almacenes Central", "employment[0].city": "Fresno",
    "employment[0].occupation": "almacenista", "employment[0].from": "2016-10-01", "employment[0].to": "present",
    "marital.status": "married", "marital.times_married": 1, "spouse.name": "Carmen Ramírez",
    "spouse.dob": "1984-02-11", "spouse.marriage_date": "2008-09-06", "spouse.citizenship_status": "lpr",
    "children.count": 0, **{k: v for k, v in NO_BACKGROUND.items()
                            if k not in ("background.arrested_cited_detained", "background.committed_crime_not_arrested")},
    "background.selective_service": "yes", **OATH_YES, "fee.method": "online",
}

ANA = {
    "lpr_since": "2020-06-02", "name.given": "Ana Lucía", "name.family": "Hernández Ruiz",
    "names.used": ["Ana Lucía Morales"], "name_change.requested": "Ana Lucía Morales", "spouse.name": "Daniel Morales",
    "spouse.marriage_date": "2023-04-15",
    "dob": "1995-09-11", "country_of_birth": "Mexico", "nationality": "Mexico",
    "sex": "female", "height": "5 ft 4 in", "weight": "130 lb", "eye_color": "brown", "hair_color": "brown",
    "ethnicity": "hispanic_or_latino", "race": "white", "contact.phone": "8315550199",
    "addresses[0].city": "Watsonville", "addresses[0].state": "CA", "addresses[0].zip": "95076",
    "addresses[0].street": "789 Avenida Prueba", "addresses[0].from": "2021-03-01", "addresses[0].to": "present",
    "employment[0].employer": "Clínica Dental Sonrisa", "employment[0].city": "Watsonville",
    "employment[0].occupation": "recepcionista", "employment[0].from": "2020-09-01", "employment[0].to": "present",
    "trips.any": False,
    "marital.status": "married", "marital.times_married": 1, "spouse.dob": "1993-01-30",
    "spouse.citizenship_status": "us_citizen", "children.count": 0,
    **NO_BACKGROUND, **OATH_YES, "fee.method": "online",
}

ROSA_TRIPS = [("2021-12-01", "2022-02-15"), ("2022-11-20", "2023-03-05"), ("2023-11-25", "2024-03-18"),
              ("2024-11-22", "2025-03-17"), ("2025-11-20", "2026-03-09")]
ROSA = {
    "name.given": "Rosa", "name.family": "Delgado Peña", "names.used": [], "name_change.requested": None,
    "country_of_birth": "Mexico", "nationality": "Mexico", "filing.planned_date": "2026-11-15",
    "sex": "female", "height": "5 ft 1 in", "weight": "150 lb", "eye_color": "brown", "hair_color": "gray",
    "ethnicity": "hispanic_or_latino", "race": "white", "contact.phone": "8315550123",
    "addresses[0].city": "Castroville", "addresses[0].state": "CA", "addresses[0].zip": "95012",
    "addresses[0].street": "22 Calle Demo", "addresses[0].from": "2009-04-01", "addresses[0].to": "present",
    "employment[0].employer": "Trabajo agrícola de temporada", "employment[0].city": "Castroville",
    "employment[0].occupation": "trabajadora agrícola", "employment[0].from": "2009-05-01",
    "employment[0].to": "present",
    "trips.any": True,
    **{f"trips[{i}].{k}": v for i, (dep, ret) in enumerate(ROSA_TRIPS)
       for k, v in (("departure", dep), ("return", ret), ("countries", "México"), ("reason", "visita familiar"),
                    ("another", i < len(ROSA_TRIPS) - 1))},
    "marital.status": "widowed", "marital.times_married": 1, "children.count": 1,
    "children[0].name": "Lucía Delgado", "children[0].dob": "1996-05-05", "children[0].residence_city": "Castroville",
    "children[0].relationship": "biological",
    **NO_BACKGROUND, "background.tax_not_filed": "yes", **OATH_YES,
    "fee.method": "paper", "fee.benefit_type": "medi-cal", "fee.household_size": 1, "fee.income": 14000,
}

SCRIPTS = {"c_maria": MARIA, "c_jorge": {**JORGE, **JORGE_REST}, "c_ana": ANA, "c_rosa": ROSA}
