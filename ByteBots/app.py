import base64
import email
import imaplib
import os
from email.header import decode_header

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MAX_EMAILS = int(os.getenv("MAX_EMAILS", "5"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def connect_gmail(email_address, app_password):
    """Connect to Gmail via IMAP using app password."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(email_address, app_password)
    return mail


def decode_mime_header(value):
    """Decode MIME encoded header like subject or sender."""
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            result.append(part)
    return "".join(result)


def get_email_body(msg):
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="ignore")
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="ignore")
        except Exception:
            pass
    return ""


def fetch_emails(mail, count):
    """Fetch latest emails from inbox."""
    mail.select("INBOX")
    status, data = mail.search(None, "ALL")
    if status != "OK":
        return []

    email_ids = data[0].split()
    latest_ids = email_ids[-count:] if len(email_ids) >= count else email_ids
    latest_ids.reverse()  # newest first

    emails = []
    for eid in latest_ids:
        status, msg_data = mail.fetch(eid, "(RFC822)")
        if status != "OK":
            continue
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        sender = decode_mime_header(msg.get("From", ""))
        subject = decode_mime_header(msg.get("Subject", ""))
        body = get_email_body(msg).strip()

        emails.append({
            "sender": sender,
            "subject": subject,
            "body": body[:3000],
        })
    return emails


def summarize(text, api_key):
    """Summarize email text using OpenAI or fallback to truncation."""
    if not api_key:
        words = " ".join(text.split())
        return words[:200] + ("..." if len(words) > 200 else "")
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.2,
        max_tokens=120,
        messages=[
            {"role": "system", "content": "Summarize the email in one short sentence."},
            {"role": "user", "content": text},
        ],
    )
    return resp.choices[0].message.content.strip()


# ────────────────────────── UI ──────────────────────────

st.set_page_config(page_title="AI Email Summarizer", layout="wide")
st.title("AI Email Summarizer")

# Initialize session state
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "mail" not in st.session_state:
    st.session_state.mail = None
if "gmail_address" not in st.session_state:
    st.session_state.gmail_address = ""

# ── Sidebar ──────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    max_emails = st.number_input("Emails to fetch", min_value=1, value=DEFAULT_MAX_EMAILS, step=1)
    api_key = os.getenv("OPENAI_API_KEY", "")

    if st.session_state.logged_in:
        st.divider()
        st.success(f"Logged in as {st.session_state.gmail_address}")
        if st.button("Logout"):
            try:
                st.session_state.mail.logout()
            except Exception:
                pass
            st.session_state.logged_in = False
            st.session_state.mail = None
            st.session_state.gmail_address = ""
            st.rerun()

# ── Login Page ───────────────────────────────────────────
if not st.session_state.logged_in:
    st.subheader("Login to Gmail")

    with st.form("login_form"):
        gmail_address = st.text_input("Gmail Address", placeholder="you@gmail.com")
        app_password = st.text_input("App Password", type="password", placeholder="xxxx xxxx xxxx xxxx")
        submitted = st.form_submit_button("Login", type="primary")

    if submitted:
        if not gmail_address or not app_password:
            st.error("Please enter both Gmail address and App Password.")
        else:
            with st.spinner("Connecting to Gmail..."):
                try:
                    mail = connect_gmail(gmail_address, app_password)
                    st.session_state.logged_in = True
                    st.session_state.mail = mail
                    st.session_state.gmail_address = gmail_address
                    st.rerun()
                except imaplib.IMAP4.error:
                    st.error("Login failed. Check your email and app password.")
                except Exception as e:
                    st.error(f"Connection error: {e}")

    # ── How to get App Password ──────────────────────────
    st.divider()
    st.subheader("How to get an App Password")
    st.markdown("""
**Step 1: Enable 2-Step Verification FIRST** (required before App Passwords will show up)
1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Under **"How you sign in to Google"**, click **2-Step Verification**
3. Click **Get Started** and follow the steps (you'll need your phone)
4. Turn it **ON**

> ⚠️ **If you skip this step**, the App Passwords page will say *"The setting you are looking for is not available for your account"*

**Step 2: Generate an App Password** (only works after Step 1 is done)
1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. You may need to sign in again
3. Under **"App name"**, type `email-summarizer` and click **Create**
4. A **16-character password** will appear (like `abcd efgh ijkl mnop`)
5. Copy it and paste it above in the **App Password** field

> 💡 **Still not working?** If you have a school/work Google account, your admin may have disabled App Passwords. Try with a personal `@gmail.com` account instead.
""")

# ── Dashboard (after login) ──────────────────────────────
else:
    st.subheader(f"Inbox — {st.session_state.gmail_address}")

    if st.button("Fetch & Summarize", type="primary"):
        with st.spinner("Fetching emails..."):
            try:
                emails = fetch_emails(st.session_state.mail, max_emails)
            except Exception as e:
                st.error(f"Error fetching emails: {e}")
                # Try reconnecting
                st.session_state.logged_in = False
                st.session_state.mail = None
                st.rerun()

        if not emails:
            st.warning("No emails found in inbox.")
        else:
            st.success(f"Found **{len(emails)}** emails. Generating summaries...")

            progress = st.progress(0)
            rows = []
            for i, em in enumerate(emails):
                text = em["body"] or em["subject"] or "(empty)"
                s = summarize(text, api_key)
                rows.append({
                    "#": i + 1,
                    "Subject": em["subject"] or "(No Subject)",
                    "Summary": s,
                })
                progress.progress((i + 1) / len(emails))
            progress.empty()

            st.subheader("Summary Table")
            st.table(rows)

            st.subheader("Details")
            for i, em in enumerate(emails):
                with st.expander(f"{i+1}. {em['subject'] or '(No Subject)'}"):
                    st.write(f"**From:** {em['sender']}")
                    st.write(f"**Subject:** {em['subject']}")
                    st.write(f"**Body:** {em['body'][:1000]}")
                    st.divider()
                    st.write(f"**AI Summary:** {rows[i]['Summary']}")