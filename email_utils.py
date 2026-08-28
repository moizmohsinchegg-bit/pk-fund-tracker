import requests
import streamlit as st

def send_admin_notification(name, email, phone):
    api_key = st.secrets.get("RESEND_API_KEY")
    if not api_key:
        return False, "RESEND_API_KEY not configured"
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": "onboarding@resend.dev",
                "to": "moizmohsinchegg@gmail.com",
                "subject": f"New Fund Tracker access request: {name}",
                "text": f"Name: {name}\nEmail: {email}\nPhone: {phone}\n\n"
                        f"Generate an access key, add it as a new row in the Users tab "
                        f"(UserKey, Email, InvestorType blank, StartDate blank, PlannedAmount blank), "
                        f"then send the key to the client yourself."
            },
            timeout=10,
        )
        return response.status_code in (200, 201), response.text
    except Exception as e:
        return False, str(e)
