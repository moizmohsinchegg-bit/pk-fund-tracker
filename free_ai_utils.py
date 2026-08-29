from tavily import TavilyClient
from groq import Groq
import streamlit as st
import hashlib
from datetime import date as date_type


def get_ai_recommendation_free(fund_name, category, breakdown_df, rec, portfolio_summary, txn_history_text):
    cache_key = f"free_ai_cache_{hashlib.md5(fund_name.encode()).hexdigest()}_{date_type.today()}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    tavily_key = st.secrets.get("TAVILY_API_KEY")
    groq_key = st.secrets.get("GROQ_API_KEY")
    if not tavily_key or not groq_key:
        return "Free AI analysis not configured — add TAVILY_API_KEY and GROQ_API_KEY in Streamlit secrets."

    # Step 1: fetch real current context
    news_context = ""
    try:
        tavily = TavilyClient(api_key=tavily_key)
        queries = [
            f"{fund_name} Pakistan mutual fund news",
            "State Bank of Pakistan policy rate inflation 2026",
            "Pakistan stock exchange KSE-100 outlook",
        ]
        for q in queries:
            result = tavily.search(query=q, max_results=2)
            for r in result.get("results", []):
                news_context += f"- {r.get('title', '')}: {r.get('content', '')[:300]}\n"
    except Exception as e:
        news_context = f"(Web search unavailable: {e})"

    # Step 2: reason over everything with Groq
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

CURRENT NEWS/CONTEXT FOUND VIA WEB SEARCH:
{news_context}

Using ALL of the above — the fund's own numeric trend, how it stacks against category peers, how it fits
this investor's broader portfolio, AND the current news/context found via search — give a specific
recommendation: SWITCH, WATCH, or HOLD.

Write 4-5 sentences max. Reference actual numbers from the data above AND mention anything relevant from
the current news context. End with one line noting this is not financial advice."""

    try:
        client = Groq(api_key=groq_key)
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
        )
        result = completion.choices[0].message.content
        st.session_state[cache_key] = result
        return result
    except Exception as e:
        return f"AI analysis unavailable right now ({e})."
