def run(community_id="nm-albuquerque", state="NM"):
    facts = [
        {"fact_key": "district_proficiency_ela_pct",    "dimension": "academic_need",          "value": 32,   "confidence": "HIGH",     "source_class": "PED_DATA",       "in_main_analysis": True},
        {"fact_key": "chronic_absenteeism_rate_pct",   "dimension": "academic_need",          "value": 22,   "confidence": "MODERATE", "source_class": "PED_DATA",       "in_main_analysis": True},
        {"fact_key": "graduation_rate_pct",             "dimension": "academic_need",          "value": 74,   "confidence": "HIGH",     "source_class": "PED_DATA",       "in_main_analysis": True},
        {"fact_key": "charter_seat_share_pct",          "dimension": "charter_saturation",     "value": 12,   "confidence": "HIGH",     "source_class": "PED_DATA",       "in_main_analysis": True},
        {"fact_key": "num_charter_schools",             "dimension": "charter_saturation",     "value": 18,   "confidence": "HIGH",     "source_class": "PED_DATA",       "in_main_analysis": True},
        {"fact_key": "k12_population_trend_5yr_pct",   "dimension": "population_trends",      "value": 3,    "confidence": "MODERATE", "source_class": "FEDERAL_DATA",   "in_main_analysis": True},
        {"fact_key": "political_climate_index",         "dimension": "political_climate",      "value": 6,    "confidence": "MODERATE", "source_class": "PRIMARY_GOVT",   "in_main_analysis": True},
        {"fact_key": "authorizer_approval_rate_pct",   "dimension": "authorizer_friendliness","value": 45,   "confidence": "HIGH",     "source_class": "AUTHORIZER_DOC", "in_main_analysis": True},
        {"fact_key": "facilities_feasibility_index",   "dimension": "facilities_feasibility", "value": 6,    "confidence": "MODERATE", "source_class": "PRIMARY_GOVT",   "in_main_analysis": True},
        {"fact_key": "per_pupil_revenue_vs_state_avg_pct","dimension": "funding_environment", "value": -5,   "confidence": "HIGH",     "source_class": "FEDERAL_DATA",   "in_main_analysis": True},
        {"fact_key": "demand_supply_gap_index",         "dimension": "competitive_opportunity","value": 7,    "confidence": "MODERATE", "source_class": "THINK_TANK",     "in_main_analysis": True},
        {"fact_key": "operational_complexity_index",   "dimension": "operational_complexity", "value": 5,    "confidence": "HIGH",     "source_class": "PED_DATA",       "in_main_analysis": True},
        # these two will be blocked by S4
        {"fact_key": "advocacy_note",                  "dimension": "political_climate",      "value": "pro-charter city", "confidence": "LOW", "source_class": "ADVOCACY", "in_main_analysis": True},
        {"fact_key": "replication_readiness_index",    "dimension": "replication_feasibility","value": 5,    "confidence": "LOW",      "source_class": "SELF_REPORTED",  "in_main_analysis": True},
    ]
    return {"community_id": community_id, "state": state, "facts": facts}
