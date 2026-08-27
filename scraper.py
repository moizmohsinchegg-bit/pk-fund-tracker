import os
import json
import pandas as pd
from io import StringIO
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

MUFAP_URL = "https://www.mufap.com.pk/Industry/IndustryStatDaily?tab=1"
SHEET_NAME = "PK_Fund_Data"

def fetch_mufap_html():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        page.goto(MUFAP_URL, timeout=30000)
        page.wait_for_timeout(8000)
        content = page.content()
        browser.close()
        return content

def parse_table(content):
    raw = pd.read_html(StringIO(content), header=None)[2]

    col_names = ["Sector", "Fund Name", "Rating", "Benchmark", "Validity Date",
                 "NAV", "YTD", "MTD", "1 Day", "15 Days", "30 Days", "90 Days",
                 "180 Days", "270 Days", "365 Days", "2 Years", "3 Years"]

    records = []
    current_category = None

    for _, row in raw.iterrows():
        vals = row.tolist()
        first18 = vals[:18]
        non_null = [v for v in first18 if pd.notna(v)]

        if len(set(non_null)) == 1:
            current_category = non_null[0]
            continue
        if first18[0] == "Sector":
            continue

        record = dict(zip(col_names, vals[:17]))
        record["Category"] = current_category
        records.append(record)

    df = pd.DataFrame(records)

    numeric_cols = ["NAV", "YTD", "MTD", "1 Day", "15 Days", "30 Days",
                     "90 Days", "180 Days", "270 Days", "365 Days", "2 Years", "3 Years"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['Validity Date'] = pd.to_datetime(df['Validity Date'], format='%b %d, %Y', errors='coerce')
    df['Snapshot Date'] = pd.Timestamp.now().normalize()
    df['Shariah'] = df['Category'].str.contains('Shariah Compliant')
    df['Asset Class'] = df['Category'].str.replace('Shariah Compliant ', '', regex=False)
    return df

def push_to_sheet(df):
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(creds)

    sh = gc.open(SHEET_NAME)
    worksheet = sh.sheet1

    export_df = df.copy()
    export_df['Validity Date'] = export_df['Validity Date'].dt.strftime('%Y-%m-%d')
    export_df['Snapshot Date'] = export_df['Snapshot Date'].dt.strftime('%Y-%m-%d')
    export_df = export_df.fillna('')

    existing = worksheet.get_all_values()

    # Make sure the grid has room before appending - grow it generously (1 year of daily data)
    rows_needed = len(existing) + len(export_df) + 50  # +50 buffer
    if worksheet.row_count < rows_needed:
        worksheet.resize(rows=max(rows_needed, worksheet.row_count + 5000))

    if not existing:
        worksheet.update([export_df.columns.tolist()] + export_df.values.tolist())
    else:
        worksheet.append_rows(export_df.values.tolist(), value_input_option='RAW')

    print(f"✅ Wrote {len(export_df)} rows to '{SHEET_NAME}' (grid now {worksheet.row_count} rows)")

if __name__ == "__main__":
    html = fetch_mufap_html()
    print("Fetched page, length:", len(html))
    df = parse_table(html)
    print("Parsed rows:", df.shape)
    push_to_sheet(df)
