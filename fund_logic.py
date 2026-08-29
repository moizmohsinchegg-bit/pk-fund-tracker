import pandas as pd
from datetime import date


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
    df = df.copy()
    numeric_cols = ['YTD', 'MTD', '1 Day', '15 Days', '30 Days', '90 Days',
                     '180 Days', '270 Days', '365 Days', '2 Years', '3 Years', 'NAV']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    rating_risk_map = {'AAA(f)': 1, 'AA+(f)': 2, 'AA(f)': 3, 'AA-(f)': 4,
                        'A+(f)': 5, 'A(f)': 6, 'A-(f)': 7}
    df['Risk Proxy'] = df['Rating'].map(rating_risk_map)
    df['AMC'] = df['Fund Name'].apply(extract_amc)
    df['Shariah'] = df['Category'].str.contains('Shariah Compliant', na=False)

    def score_category(group):
        category_value = group.name
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

        group['Category'] = category_value
        return group

    scored = df.groupby('Category', group_keys=False).apply(score_category)
    scored['Rank in Category'] = scored.groupby('Category')['Composite Score'].rank(ascending=False, method='min')
    return scored


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
    is_already_best = fund_row['FundName'] == best_peer['Fund Name']

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


def get_indicator_breakdown(fund_row, category_peers_df):
    windows = ['1 Day', '15 Days', '30 Days', '90 Days', '180 Days', '270 Days',
               'YTD', '365 Days', '2 Years', '3 Years']
    rows = []
    for w in windows:
        fund_value = fund_row.get(w)
        if pd.isna(fund_value):
            continue
        peer_values = category_peers_df[w].dropna()
        if len(peer_values) < 2:
            percentile = None
        else:
            percentile = (peer_values < fund_value).mean() * 100
        rows.append({
            "Time Span": w,
            "Return (%)": round(fund_value, 2),
            "Category Percentile": round(percentile, 0) if percentile is not None else "N/A",
            "Funds Compared": len(peer_values)
        })
    return pd.DataFrame(rows)


def generate_interpretation(fund_row, breakdown_df, rec):
    if breakdown_df.empty:
        return "Not enough data to interpret this fund's trend yet."

    short_term = breakdown_df[breakdown_df['Time Span'].isin(['30 Days', '90 Days'])]
    long_term = breakdown_df[breakdown_df['Time Span'].isin(['365 Days', '2 Years', '3 Years'])]

    short_pct = pd.to_numeric(short_term['Category Percentile'], errors='coerce').mean()
    long_pct = pd.to_numeric(long_term['Category Percentile'], errors='coerce').mean()

    trend_note = ""
    if pd.notna(short_pct) and pd.notna(long_pct):
        diff = short_pct - long_pct
        if diff >= 15:
            trend_note = "Its recent performance is notably better than its longer-term track record — it may be improving."
        elif diff <= -15:
            trend_note = "Its recent performance is notably weaker than its longer-term track record — worth watching closely."
        else:
            trend_note = "Its recent and longer-term performance are broadly consistent."

    status_explainer = {
        "HOLD": "It's performing well enough relative to peers that no action is suggested.",
        "WATCH": "It has slipped below the median for its category — not urgent, but worth monitoring.",
        "SWITCH": "It's fallen into the bottom tier for its category, which is where the system starts actively suggesting alternatives."
    }

    return f"{status_explainer[rec['status']]} {trend_note}"


def get_category_leaderboard(scored_df, top_n=3, shariah_only=False):
    """Returns top N funds per category, for new-investor overview and the always-visible dashboard leaderboard."""
    df = scored_df.copy()
    if shariah_only:
        df = df[df['Shariah'] == True]

    leaderboard = []
    for cat in df['Category'].dropna().unique():
        cat_df = df[df['Category'] == cat].sort_values('Rank in Category').head(top_n)
        for _, row in cat_df.iterrows():
            leaderboard.append({
                "Category": cat.replace(" (Absolute Return )", "").replace(" (Annualized Return )", ""),
                "Rank": int(row['Rank in Category']) if pd.notna(row['Rank in Category']) else None,
                "Fund Name": row['Fund Name'],
                "AMC": row['AMC'],
                "YTD %": row['YTD'],
                "1Y %": row['365 Days'],
                "2Y %": row['2 Years'],
                "3Y %": row['3 Years'],
                "Rating": row['Rating'],
            })
    return pd.DataFrame(leaderboard)


def get_or_create_worksheet(sh, name, headers):
    try:
        ws = sh.worksheet(name)
    except Exception:
        ws = sh.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws


def get_users_df(sh):
    ws = get_or_create_worksheet(sh, "Users", ["UserKey", "Email", "InvestorType", "StartDate", "PlannedAmount"])
    records = ws.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(
        columns=["UserKey", "Email", "InvestorType", "StartDate", "PlannedAmount"])


def get_transactions_df(sh):
    ws = get_or_create_worksheet(sh, "Transactions",
                                   ["UserKey", "Date", "Type", "FundName", "GrossAmount", "NetAmount", "Units"])
    records = ws.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(
        columns=["UserKey", "Date", "Type", "FundName", "GrossAmount", "NetAmount", "Units"])


def add_user(sh, user_key, email, investor_type, start_date, planned_amount):
    ws = get_or_create_worksheet(sh, "Users", ["UserKey", "Email", "InvestorType", "StartDate", "PlannedAmount"])
    ws.append_row([user_key, email, investor_type, str(start_date), planned_amount])


def add_transaction(sh, user_key, txn_date, txn_type, fund_name, gross_amount, net_amount, units):
    ws = get_or_create_worksheet(sh, "Transactions",
                                   ["UserKey", "Date", "Type", "FundName", "GrossAmount", "NetAmount", "Units"])
    ws.append_row([user_key, str(txn_date), txn_type, fund_name, gross_amount, net_amount, units])


def compute_portfolio(transactions_df, scored_df, user_key):
    user_txns = transactions_df[transactions_df['UserKey'] == user_key].copy()
    if user_txns.empty:
        return pd.DataFrame()

    user_txns['Units'] = pd.to_numeric(user_txns['Units'], errors='coerce')
    user_txns['GrossAmount'] = pd.to_numeric(user_txns['GrossAmount'], errors='coerce')
    user_txns['NetAmount'] = pd.to_numeric(user_txns['NetAmount'], errors='coerce')

    def signed_units(r):
        if r['Type'] == 'INVESTMENT':
            return r['Units']
        elif r['Type'] == 'REDEMPTION':
            return -r['Units']
        else:
            return r['Units']

    def signed_invested(r):
        if r['Type'] == 'INVESTMENT':
            return r['GrossAmount']
        elif r['Type'] == 'REDEMPTION':
            return -r['NetAmount']
        else:
            return r['GrossAmount']

    user_txns['SignedUnits'] = user_txns.apply(signed_units, axis=1)
    user_txns['SignedInvested'] = user_txns.apply(signed_invested, axis=1)

    holdings = user_txns.groupby('FundName').agg(
        Units=('SignedUnits', 'sum'),
        NetInvested=('SignedInvested', 'sum')
    ).reset_index()

    holdings = holdings[holdings['Units'] > 0.0001]
    if holdings.empty:
        return pd.DataFrame()

    nav_lookup = scored_df[['Fund Name', 'NAV', 'Category', 'AMC', 'Rank in Category', 'Composite Score']].rename(
        columns={'Fund Name': 'FundName'})
    holdings = holdings.merge(nav_lookup, on='FundName', how='left')
    holdings['Current Value'] = holdings['Units'] * holdings['NAV']
    holdings['Gain/Loss'] = holdings['Current Value'] - holdings['NetInvested']
    holdings['Gain/Loss %'] = (holdings['Gain/Loss'] / holdings['NetInvested'] * 100).round(2)

    return holdings


def update_user_profile(sh, user_key, investor_type, start_date, planned_amount):
    ws = get_or_create_worksheet(sh, "Users", ["UserKey", "Email", "InvestorType", "StartDate", "PlannedAmount"])
    cell = ws.find(user_key)
    if cell is None:
        return False
    row_num = cell.row
    ws.update(f"C{row_num}:E{row_num}",
              [[investor_type, str(start_date), planned_amount if planned_amount is not None else ""]])
    return True


def get_signup_requests_df(sh):
    ws = get_or_create_worksheet(sh, "SignupRequests", ["Name", "Email", "Phone", "RequestDate", "Status"])
    records = ws.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(
        columns=["Name", "Email", "Phone", "RequestDate", "Status"])


def add_signup_request(sh, name, email, phone):
    ws = get_or_create_worksheet(sh, "SignupRequests", ["Name", "Email", "Phone", "RequestDate", "Status"])
    ws.append_row([name, email, phone, str(date.today()), "Pending"])
