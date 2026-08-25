import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from fund_logic import score_funds, get_switch_recommendation
import json

st.set_page_config(page_title="Pakistan Fund Intelligence", layout="wide")
st.title("🇵🇰 Pakistan Fund Intelligence")

@st.cache_data(ttl=3600)
def load_data():
    creds_json = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open("PK_Fund_Data")
    df = pd.DataFrame(sh.sheet1.get_all_records())
    latest_date = df['Snapshot Date'].max()
    latest = df[df['Snapshot Date'] == latest_date].drop_duplicates(subset='Fund Name', keep='last')
    return score_funds(latest)

scored = load_data()

st.sidebar.header("Settings")
aggressiveness = st.sidebar.select_slider(
    "How aggressive should switching recommendations be?",
    options=["conservative", "moderate", "aggressive"],
    value="moderate"
)

investor_type = st.radio("Are you an existing investor or new?", ["Existing", "New"])

if investor_type == "Existing":
    if "holdings" not in st.session_state:
        st.session_state.holdings = []

    col1, col2, col3 = st.columns(3)
    with col1:
        amc = st.selectbox("Bank/AMC", sorted(scored['AMC'].unique()))
    with col2:
        fund_options = sorted(scored[scored['AMC'] == amc]['Fund Name'].tolist())
        fund = st.selectbox("Fund", fund_options)
    with col3:
        amount = st.number_input("Amount Invested (PKR)", min_value=0.0, step=1000.0)

    if st.button("Add Fund"):
        st.session_state.holdings.append({"Fund Name": fund, "Amount Invested": amount})
        st.success(f"Added {fund}")

    if st.session_state.holdings:
        st.subheader("Your Holdings")
        for h in st.session_state.holdings:
            fund_row = scored[scored['Fund Name'] == h['Fund Name']].iloc[0]
            peers = scored[scored['Category'] == fund_row['Category']]
            rec = get_switch_recommendation(fund_row, peers, aggressiveness)

            color = {"HOLD": "🟢", "WATCH": "🟡", "SWITCH": "🔴"}[rec['status']]
            st.markdown(f"**{color} {h['Fund Name']}** — PKR {h['Amount Invested']:,.0f}")
            st.write(f"Category: {fund_row['Category']}")
            st.write(f"Recommendation: **{rec['status']}** — {rec['reason']}")
            if rec['suggested_fund']:
                st.write(f"Top alternative: {rec['suggested_fund']}")
            st.divider()
else:
    planned_amount = st.number_input("Planned investment (PKR)", min_value=0.0, step=1000.0)
    shariah_only = st.checkbox("Shariah-compliant only")
    st.info("Allocation recommendation for new investors — coming next.")
