import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date
import json
import plotly.express as px
from fund_logic import (
    score_funds, get_switch_recommendation,
    get_users_df, get_transactions_df, add_user, add_transaction, compute_portfolio
)

st.set_page_config(page_title="Pakistan Fund Intelligence", layout="wide")


@st.cache_resource
def get_sheet_connection():
    creds_json = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open("PK_Fund_Data")


@st.cache_data(ttl=3600)
def load_scored_data():
    sh = get_sheet_connection()
    df = pd.DataFrame(sh.sheet1.get_all_records())
    latest_date = df['Snapshot Date'].max()
    latest = df[df['Snapshot Date'] == latest_date].drop_duplicates(subset='Fund Name', keep='last')
    return score_funds(latest)


sh = get_sheet_connection()
scored = load_scored_data()

st.title("🇵🇰 Pakistan Fund Intelligence")
st.caption("Not financial or tax advice — verify independently before acting.")

# ---------- LOGIN GATE ----------
if "user_key" not in st.session_state:
    st.session_state.user_key = None

if st.session_state.user_key is None:
    st.subheader("Enter your access key")
    key_input = st.text_input("Access Key", type="password")
    if st.button("Continue"):
        if key_input.strip():
            st.session_state.user_key = key_input.strip()
            st.rerun()
        else:
            st.error("Please enter a key.")
    st.stop()

user_key = st.session_state.user_key
users_df = get_users_df(sh)
transactions_df = get_transactions_df(sh)
existing_user_row = users_df[users_df['UserKey'] == user_key]

st.sidebar.write(f"Logged in as: **{user_key}**")
if st.sidebar.button("Log out"):
    st.session_state.user_key = None
    st.rerun()

aggressiveness = st.sidebar.select_slider(
    "Switching aggressiveness",
    options=["conservative", "moderate", "aggressive"],
    value="moderate"
)

# ---------- ONBOARDING (first time only) ----------
if existing_user_row.empty:
    st.subheader("Welcome — let's set up your profile")
    investor_type = st.radio("Are you a new investor or an existing investor?", ["New", "Existing"])

    if investor_type == "New":
        planned_amount = st.number_input("How much are you planning to invest (PKR)?", min_value=0.0, step=1000.0)
        planned_date = st.date_input("When do you plan to invest?", value=date.today())
        if st.button("Save profile"):
            add_user(sh, user_key, "New", planned_date, planned_amount)
            st.success("Profile saved! Refresh to continue.")
            st.rerun()

    else:  # Existing
        st.write("Tell us your current holdings — add each fund one at a time.")
        if "onboard_holdings" not in st.session_state:
            st.session_state.onboard_holdings = []

        col1, col2, col3 = st.columns(3)
        with col1:
            amc = st.selectbox("Bank/AMC", sorted(scored['AMC'].unique()))
        with col2:
            fund_options = sorted(scored[scored['AMC'] == amc]['Fund Name'].tolist())
            fund = st.selectbox("Fund", fund_options)
        with col3:
            amount = st.number_input("Current Value (PKR)", min_value=0.0, step=1000.0, key="onboard_amt")

        if st.button("Add this fund"):
            st.session_state.onboard_holdings.append({"fund": fund, "amount": amount})
            st.success(f"Added {fund}")

        if st.session_state.onboard_holdings:
            st.write("Funds added so far:")
            for h in st.session_state.onboard_holdings:
                st.write(f"- {h['fund']}: PKR {h['amount']:,.0f}")

            if st.button("Finish setup"):
                add_user(sh, user_key, "Existing", date.today(), None)
                for h in st.session_state.onboard_holdings:
                    nav_row = scored[scored['Fund Name'] == h['fund']]
                    nav = float(nav_row['NAV'].iloc[0]) if not nav_row.empty else None
                    units = h['amount'] / nav if nav else 0
                    add_transaction(sh, user_key, date.today(), "INVESTMENT", h['fund'], h['amount'], h['amount'], units)
                st.success("Setup complete! Refresh to see your dashboard.")
                st.session_state.onboard_holdings = []
                st.rerun()
    st.stop()

# ---------- MAIN DASHBOARD (returning users) ----------
st.subheader("Your Portfolio")
portfolio = compute_portfolio(transactions_df, scored, user_key)

if portfolio.empty:
    st.info("No active holdings yet. Use the form below to add an investment.")
else:
    total_value = portfolio['Current Value'].sum()
    total_invested = portfolio['NetInvested'].sum()
    total_gain = total_value - total_invested

    c1, c2, c3 = st.columns(3)
    c1.metric("Current Value", f"PKR {total_value:,.0f}")
    c2.metric("Net Invested", f"PKR {total_invested:,.0f}")
    c3.metric("Gain/Loss", f"PKR {total_gain:,.0f}", f"{(total_gain/total_invested*100):.1f}%" if total_invested else "")

    col_a, col_b = st.columns(2)
    with col_a:
        fig_pie = px.pie(portfolio, values='Current Value', names='FundName', title="Allocation by Fund")
        st.plotly_chart(fig_pie, use_container_width=True)
    with col_b:
        cat_alloc = portfolio.groupby('Category')['Current Value'].sum().reset_index()
        fig_cat = px.pie(cat_alloc, values='Current Value', names='Category', title="Allocation by Category")
        st.plotly_chart(fig_cat, use_container_width=True)

    st.write("### Fund-by-Fund Detail & Recommendations")
    for _, row in portfolio.iterrows():
        peers = scored[scored['Category'] == row['Category']]
        rec = get_switch_recommendation(row, peers, aggressiveness)
        color = {"HOLD": "🟢", "WATCH": "🟡", "SWITCH": "🔴"}[rec['status']]

        st.markdown(f"**{color} {row['FundName']}**")
        st.write(f"Units: {row['Units']:.2f} | Current Value: PKR {row['Current Value']:,.0f} | "
                 f"Gain/Loss: PKR {row['Gain/Loss']:,.0f} ({row['Gain/Loss %']}%)")
        st.write(f"Recommendation: **{rec['status']}** — {rec['reason']}")
        if rec['suggested_fund']:
            st.write(f"Top alternative in category: {rec['suggested_fund']}")
        st.divider()

# ---------- ADD INVESTMENT ----------
st.write("### Add a New Investment")
col1, col2, col3 = st.columns(3)
with col1:
    amc2 = st.selectbox("Bank/AMC", sorted(scored['AMC'].unique()), key="inv_amc")
with col2:
    fund2 = st.selectbox("Fund", sorted(scored[scored['AMC'] == amc2]['Fund Name'].tolist()), key="inv_fund")
with col3:
    amt2 = st.number_input("Amount (PKR)", min_value=0.0, step=1000.0, key="inv_amt")

if st.button("Record Investment"):
    nav_row = scored[scored['Fund Name'] == fund2]
    nav = float(nav_row['NAV'].iloc[0])
    units = amt2 / nav
    add_transaction(sh, user_key, date.today(), "INVESTMENT", fund2, amt2, amt2, units)
    st.success(f"Recorded investment of PKR {amt2:,.0f} in {fund2}")
    st.rerun()

# ---------- REDEMPTION ----------
st.write("### Record a Redemption")
if not portfolio.empty:
    redeem_fund = st.selectbox("Which fund are you redeeming?", portfolio['FundName'].tolist())
    gross = st.number_input("Gross amount redeemed (PKR)", min_value=0.0, step=1000.0, key="redeem_gross")
    net = st.number_input("Net amount you actually received (PKR)", min_value=0.0, step=1000.0, key="redeem_net")

    if st.button("Record Redemption"):
        nav_row = scored[scored['Fund Name'] == redeem_fund]
        nav = float(nav_row['NAV'].iloc[0])
        units_redeemed = gross / nav
        add_transaction(sh, user_key, date.today(), "REDEMPTION", redeem_fund, gross, net, units_redeemed)
        st.success(f"Recorded redemption of PKR {gross:,.0f} from {redeem_fund}")
        st.rerun()
else:
    st.write("No holdings to redeem yet.")
