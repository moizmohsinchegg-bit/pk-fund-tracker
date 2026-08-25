import pandas as pd

def extract_amc(fund_name):
    AMC_KEYWORDS = {
        "Meezan": ["al meezan", "meezan", "kse meezan"],
        "NBP": ["nbp"], "UBL": ["ubl"], "HBL": ["hbl"], "MCB": ["mcb"],
        "Alfalah": ["alfalah"], "AL Habib": ["al habib", "habib"],
        "Atlas": ["atlas"], "Askari": ["askari"], "ABL": ["abl"],
        "AKD": ["akd"], "BMA": ["bma"], "Faysal": ["faysal"],
        "JS": ["js "], "Lakson": ["lakson"], "NIT": ["nit"],
    }
    name_lower = fund_name.lower()
    for canonical_name, keywords in AMC_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return canonical_name
    return "Other"

def score_funds(df):
    """Takes the latest snapshot DataFrame, returns it with Category ranks and scores added."""
    df = df.copy()
    numeric_cols = ['YTD', 'MTD', '1 Day', '15 Days', '30 Days', '90 Days',
                     '180 Days', '270 Days', '365 Days', '2 Years', '3 Years', 'NAV']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    rating_risk_map = {'AAA(f)': 1, 'AA+(f)': 2, 'AA(f)': 3, 'AA-(f)': 4,
                        'A+(f)': 5, 'A(f)': 6, 'A-(f)': 7}
    df['Risk Proxy'] = df['Rating'].map(rating_risk_map)
    df['AMC'] = df['Fund Name'].apply(extract_amc)

    def score_category(group):
    category_value = group.name  # capture it explicitly - works regardless of pandas version
    group = group.copy()
    return_cols = ['YTD', '365 Days', '2 Years', '3 Years']
    pct_cols = []
    for col in return_cols:
        if group[col].notna().sum() >= 2:
            pct_col = f'{col}_pct'
            group[pct_col] = group[col].rank(pct=True) * 100
            pct_cols.append(pct_col)
    group['Return Score'] = group[pct_cols].mean(axis=1, skipna=True) if pct_cols else None

    if group['Risk Proxy'].notna().sum() >= 2:
        group['Risk Score'] = (1 - group['Risk Proxy'].rank(pct=True)) * 100
        group['Composite Score'] = group[['Return Score', 'Risk Score']].mean(axis=1, skipna=True)
    else:
        group['Composite Score'] = group['Return Score']

    group['Category'] = category_value  # re-add it explicitly, regardless of what pandas did
    return group

def get_switch_recommendation(fund_row, category_peers_df, aggressiveness="moderate"):
    if pd.isna(fund_row['Rank in Category']):
        return {"status": "HOLD", "reason": "No peer comparison available for this category.", "suggested_fund": None}

    total_in_category = len(category_peers_df)
    current_rank = fund_row['Rank in Category']
    percentile = 1 - (current_rank / total_in_category)

    thresholds = {
        "conservative": {"watch": 0.30, "switch": 0.15},
        "moderate":     {"watch": 0.50, "switch": 0.30},
        "aggressive":   {"watch": 0.70, "switch": 0.50},
    }
    t = thresholds[aggressiveness]
    best_peer = category_peers_df.sort_values('Rank in Category').iloc[0]
    is_already_best = fund_row['Fund Name'] == best_peer['Fund Name']

    if is_already_best:
        return {"status": "HOLD", "reason": "Already the top-ranked fund in its category.", "suggested_fund": None}
    if percentile <= t["switch"]:
        return {"status": "SWITCH",
                "reason": f"Ranked in the bottom {int((1-percentile)*100)}% of its category (#{int(current_rank)} of {total_in_category}).",
                "suggested_fund": best_peer['Fund Name']}
    elif percentile <= t["watch"]:
        return {"status": "WATCH",
                "reason": f"Below median rank in category (#{int(current_rank)} of {total_in_category}).",
                "suggested_fund": best_peer['Fund Name']}
    else:
        return {"status": "HOLD", "reason": "Ranking is healthy relative to category peers.", "suggested_fund": None}
