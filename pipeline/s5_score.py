DIMENSIONS = {
    "academic_need":          {"primary": "district_proficiency_ela_pct",       "weight": 0.18, "thresholds": [(15,10),(25,9),(35,8),(45,7),(55,6),(65,5),(75,4),(85,3),(None,2)]},
    "charter_saturation":     {"primary": "charter_seat_share_pct",             "weight": 0.12, "thresholds": [(5,10),(10,8),(15,7),(20,6),(30,4),(40,2),(None,1)]},
    "population_trends":      {"primary": "k12_population_trend_5yr_pct",       "weight": 0.10, "thresholds": [(-10,1),(-5,2),(0,4),(5,6),(10,8),(None,10)]},
    "political_climate":      {"primary": "political_climate_index",            "weight": 0.12, "thresholds": [(2,1),(4,3),(6,5),(8,7),(None,9)]},
    "authorizer_friendliness":{"primary": "authorizer_approval_rate_pct",       "weight": 0.12, "thresholds": [(10,1),(25,3),(40,5),(60,7),(80,8),(None,10)]},
    "facilities_feasibility": {"primary": "facilities_feasibility_index",       "weight": 0.10, "thresholds": [(2,1),(4,3),(6,5),(8,7),(None,9)]},
    "replication_feasibility":{"primary": "replication_readiness_index",        "weight": 0.08, "thresholds": [(2,1),(4,3),(6,5),(8,7),(None,9)]},
    "funding_environment":    {"primary": "per_pupil_revenue_vs_state_avg_pct", "weight": 0.08, "thresholds": [(-20,2),(-10,4),(0,6),(10,7),(20,8),(None,9)]},
    "competitive_opportunity":{"primary": "demand_supply_gap_index",            "weight": 0.05, "thresholds": [(2,2),(4,4),(6,6),(8,8),(None,10)]},
    "operational_complexity": {"primary": "operational_complexity_index",       "weight": 0.05, "thresholds": [(2,9),(4,7),(6,5),(8,3),(None,1)]},
}

TIERS = [(8.5,"HIGH_PRIORITY","HIGH PRIORITY EXPANSION MARKET"),(7.0,"STRONG","STRONG OPPORTUNITY"),
         (5.5,"MODERATE","MODERATE OPPORTUNITY"),(4.0,"WATCHLIST","WATCHLIST / MONITOR"),(0.0,"AVOID","AVOID ENTRY")]

def _lookup(facts, fact_key):
    for f in facts:
        if f.get("fact_key") == fact_key and f.get("in_main_analysis"):
            v = f.get("value")
            if isinstance(v, (int, float)):
                return v
    return None

def _threshold(value, thresholds):
    for max_val, score in thresholds:
        if max_val is None or value <= max_val:
            return float(score)
    return 5.0

def run(bundle):
    facts = bundle.get("facts", [])
    dims = {}
    for name, d in DIMENSIONS.items():
        val = _lookup(facts, d["primary"])
        score = _threshold(val, d["thresholds"]) if val is not None else 5.0
        dims[name] = {"score": round(score, 2), "weight": d["weight"],
                      "driver": f"{d['primary']}={val}" if val is not None else "no data — default 5.0"}
    composite = round(sum(d["score"] * d["weight"] for d in dims.values()), 2)
    tier_key, tier_label = next((k, l) for mn, k, l in TIERS if composite >= mn)
    return {"community_id": bundle.get("community_id"), "state": bundle.get("state"),
            "composite": composite, "tier": tier_key, "tier_label": tier_label, "dimensions": dims}
