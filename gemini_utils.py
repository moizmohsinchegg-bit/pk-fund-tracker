import google.generativeai as genai
import streamlit as st


def get_ai_recommendation(fund_name, category, breakdown_df, rec, portfolio_summary, txn_history_text):
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        return "Gemini API key not configured — add GEMINI_API_KEY in Streamlit secrets."

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""You are analyzing one mutual fund holding for a Pakistani investor's portfolio.

FUND: {fund_name}
CATEGORY: {category}
SYSTEM'S RULE-BASED SIGNAL: {rec['status']} — {rec['reason']}

PERFORMANCE ACROSS TIME SPANS (return % and category percentile vs peers):
{breakdown_df.to_string(index=False)}

THIS INVESTOR'S FULL PORTFOLIO CONTEXT:
{portfolio_summary}

TRANSACTION HISTORY FOR THIS SPECIFIC FUND:
{txn_history_text}

Using ALL of the above — this fund's own trend across time spans, how it stacks up against category peers,
AND how it fits into the investor's broader portfolio (concentration risk, diversification, recent
investment/redemption activity) — give a short, specific recommendation: SWITCH, WATCH, or HOLD.

Write 3-4 sentences max. Reference actual numbers from the data above — don't give generic advice.
End with one line noting this is not financial advice."""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI analysis unavailable right now ({e})."
