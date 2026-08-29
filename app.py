import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from gemini_utils import get_ai_recommendation
from datetime import date
import json
import plotly.express as px
from fund_logic import (
    score_funds, get_switch_recommendation, get_indicator_breakdown, generate_interpretation,
    get_users_df, get_transactions_df, add_user, add_transaction, compute_portfolio,
    update_user_profile
)
from email_utils import send_admin_notification
from fund_logic import get_signup_requests_df, add_signup_request  # add to existing fund_logic import line instead if you prefer one line
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

# ---------- LOGIN GATE (email + key, with request-access flow) ----------
if "user_key" not in st.session_state:
    st.session_state.user_key = None
    st.session_state.user_email = None

if st.session_state.user_key is None:
    st.subheader("Login")
    email_input = st.text_input("Email")
    key_input = st.text_input("Access Key", type="password")

    if st.button("Continue"):
        if not email_input.strip() or not key_input.strip():
            st.error("Please enter both email and access key.")
        else:
            users_df_check = get_users_df(sh)
            match = users_df_check[users_df_check['UserKey'] == key_input.strip()]

            if match.empty:
                st.error("Access key not found. If you don't have one yet, request access below.")
            else:
                stored_email = str(match.iloc[0].get('Email', '')).strip().lower()
                if stored_email and stored_email != email_input.strip().lower():
                    st.error("Email does not match this access key.")
                else:
                    st.session_state.user_key = key_input.strip()
                    st.session_state.user_email = email_input.strip()
                    st.rerun()

    st.divider()
    st.subheader("Don't have an access key yet?")
    with st.form("request_access_form"):
        req_name = st.text_input("Full Name")
        req_email = st.text_input("Email", key="req_email")
        req_phone = st.text_input("Phone (format: +923001234567)")
        submitted = st.form_submit_button("Request Access")

        if submitted:
            phone_clean = req_phone.strip().replace(" ", "")
            valid_phone = (phone_clean.startswith("+92") and
                           phone_clean[3:].isdigit() and
                           len(phone_clean[3:]) == 10)

            if not req_name.strip() or not req_email.strip():
                st.error("Please fill in your name and email.")
            elif not valid_phone:
                st.error("Phone must be in the format +92 followed by 10 digits, e.g. +923001234567")
            else:
                add_signup_request(sh, req_name.strip(), req_email.strip(), phone_clean)
                sent, info = send_admin_notification(req_name.strip(), req_email.strip(), phone_clean)
                if sent:
                    st.success("Request submitted! You'll receive your access key by email once approved.")
                else:
                    st.warning("Request saved, but the notification email failed to send. Check the SignupRequests sheet.")
    st.stop()

user_key = st.session_state.user_key
user_email = st.session_state.user_email
users_df = get_users_df(sh)
transactions_df = get_transactions_df(sh)
existing_user_row = users_df[users_df['UserKey'] == user_key]
needs_onboarding = existing_user_row.empty or str(existing_user_row.iloc[0].get('InvestorType', '')).strip() == ''
st.sidebar.write(f"Logged in as: **{user_email}**")
if st.sidebar.button("Log out"):
    st.session_state.user_key = None
    st.session_state.user_email = None
    st.rerun()

aggressiveness = st.sidebar.select_slider(
    "Switching aggressiveness",
    options=["conservative", "moderate", "aggressive"],
    value="moderate"
)

# ---------- ONBOARDING (first time only) ----------
if needs_onboarding:
    st.subheader("Welcome — let's set up your profile")
    investor_type = st.radio("Are you a new investor or an existing investor?", ["New", "Existing"])

    if investor_type == "New":
        planned_amount = st.number_input("How much are you planning to invest (PKR)?", min_value=0.0, step=1000.0)
        planned_date = st.date_input("When do you plan to invest?", value=date.today())
        if st.button("Save profile"):
            update_user_profile(sh, user_key, "New", planned_date, planned_amount)
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
                update_user_profile(sh, user_key, "Existing", date.today(), None)
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

    # Summary table first - everything at a glance
    summary_rows = []
    for _, row in portfolio.iterrows():
        peers = scored[scored['Category'] == row['Category']]
        rec = get_switch_recommendation(row, peers, aggressiveness)
        summary_rows.append({
            "Status": {"HOLD": "🟢 HOLD", "WATCH": "🟡 WATCH", "SWITCH": "🔴 SWITCH"}[rec['status']],
            "Fund": row['FundName'],
            "Category": row['Category'].replace(" (Absolute Return )", "").replace(" (Annualized Return )", ""),
            "Rank in Category": f"#{int(row['Rank in Category'])} of {len(peers)}" if pd.notna(row['Rank in Category']) else "N/A",
            "Current Value (PKR)": f"{row['Current Value']:,.0f}",
            "Gain/Loss": f"{row['Gain/Loss %']}%",
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.divider()

    # Then full detail per fund
    for _, row in portfolio.iterrows():
        peers = scored[scored['Category'] == row['Category']]
        rec = get_switch_recommendation(row, peers, aggressiveness)
        color = {"HOLD": "🟢", "WATCH": "🟡", "SWITCH": "🔴"}[rec['status']]
        full_fund_row = scored[scored['Fund Name'] == row['FundName']].iloc[0].rename({'Fund Name': 'FundName'})
        breakdown = get_indicator_breakdown(full_fund_row, peers)
        interpretation = generate_interpretation(full_fund_row, breakdown, rec)
        st.markdown(f"**{color} {row['FundName']}** — {rec['status']}")
        st.write(f"Units: {row['Units']:.2f} | Current Value: PKR {row['Current Value']:,.0f} | "
                 f"Gain/Loss: PKR {row['Gain/Loss']:,.0f} ({row['Gain/Loss %']}%)")
        st.info(interpretation)

        with st.expander("See the full performance breakdown"):
            st.write(f"**{row['FundName']}** across every time span, vs. all {len(peers)} funds in "
                     f"*{row['Category']}*:")
            st.dataframe(breakdown, use_container_width=True, hide_index=True)

            if rec['suggested_fund']:
                alt_row = peers[peers['Fund Name'] == rec['suggested_fund']].iloc[0]
                alt_breakdown = get_indicator_breakdown(alt_row.rename({'Fund Name': 'FundName'}), peers)
                st.write(f"**Compare to {rec['suggested_fund']}** (top-ranked alternative):")
                st.dataframe(alt_breakdown, use_container_width=True, hide_index=True)

            st.caption(
                f"Composite Score = average category-percentile across YTD/1Y/2Y/3Y returns, blended with a "
                f"risk-rating score where available. Current threshold ('{aggressiveness}'): SWITCH fires below the "
                f"{'15th' if aggressiveness=='conservative' else '30th' if aggressiveness=='moderate' else '50th'} "
                f"percentile in category."
            )
            with st.expander("🤖 AI Analysis (full-context recommendation)"):
            if st.button(f"Get AI analysis for {row['FundName']}", key=f"ai_btn_{row['FundName']}"):
                with st.spinner("Analyzing..."):
                    portfolio_summary = (
                        f"Total portfolio value: PKR {total_value:,.0f} across {len(portfolio)} funds. "
                        f"Allocation: " + ", ".join(
                            f"{r['FundName']} ({r['Current Value']/total_value*100:.0f}%)"
                            for _, r in portfolio.iterrows()
                        )
                    )
                    fund_txns = transactions_df[
                        (transactions_df['UserKey'] == user_key) & (transactions_df['FundName'] == row['FundName'])
                    ]
                    txn_history_text = fund_txns[['Date', 'Type', 'GrossAmount', 'NetAmount']].to_string(index=False) \
                        if not fund_txns.empty else "No transaction history recorded."

                    ai_response = get_ai_recommendation(
                        row['FundName'], row['Category'], breakdown, rec, portfolio_summary, txn_history_text
                    )
                    st.write(ai_response)
            else:
                st.caption("Click the button to run a full-context AI analysis (uses one API call).")
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

# ---------- ADJUST AN EXISTING HOLDING ----------
st.write("### Adjust a Holding (to match your real statement)")
if not portfolio.empty:
    adjust_fund = st.selectbox("Which fund needs adjusting?", portfolio['FundName'].tolist(), key="adjust_fund")
    current_row = portfolio[portfolio['FundName'] == adjust_fund].iloc[0]

    st.number_input("Current value on file (PKR)", value=float(current_row['Current Value']),
                     disabled=True, key="adjust_old")
    new_value = st.number_input("Actual current value (PKR)", min_value=0.0,
                                  value=float(current_row['Current Value']), step=1000.0, key="adjust_new")

    if st.button("Apply Adjustment"):
        nav_row = scored[scored['Fund Name'] == adjust_fund]
        nav = float(nav_row['NAV'].iloc[0])
        target_units = new_value / nav
        delta_units = target_units - current_row['Units']
        delta_amount = new_value - current_row['Current Value']
        add_transaction(sh, user_key, date.today(), "ADJUSTMENT", adjust_fund, delta_amount, delta_amount, delta_units)
        st.success(f"Adjusted {adjust_fund} by PKR {delta_amount:,.0f}")
        st.rerun()
else:
    st.write("No holdings yet to adjust.")

# ---------- REDEMPTION ----------
st.write("### Record a Redemption")
if not portfolio.empty:
    redeem_fund = st.selectbox("Which fund are you redeeming?", portfolio['FundName'].tolist(), key="redeem_fund")
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
