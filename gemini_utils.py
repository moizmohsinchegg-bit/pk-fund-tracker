from google import genai
from google.genai import types
import streamlit as st


def get_ai_recommendation(fund_name, category, breakdown_df, rec, portfolio_summary, txn_history_text):
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        return "Gemini API key not configured — add GEMINI_API_KEY in Streamlit secrets."

    client = genai.Client(api_key=api_key)

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

Before answering, search for current, relevant context that could affect this recommendation:
- Recent Pakistan economic news (SBP policy rate decisions, inflation data, PSX/KSE-100 trends)
- Any recent news specific to this fund or its asset management company
- Relevant global market/economic conditions affecting Pakistani markets (oil prices, US Fed rate moves, regional conflicts)

Using ALL of the above — the fund's own numeric trend, how it stacks against category peers, how it fits
this investor's broader portfolio, AND current real-world conditions you find via search — give a specific
recommendation: SWITCH, WATCH, or HOLD.

Write 4-5 sentences max. Reference actual numbers from the data above AND cite what current news/conditions
influenced your view. End with one line noting this is not financial advice."""

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        return response.text
    except Exception as e:
        return f"AI analysis unavailable right now ({e})."
