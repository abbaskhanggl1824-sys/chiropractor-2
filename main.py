# -*- coding: utf-8 -*-
"""
Hyper-Personalized AI Contact & Appointment Form Bot (Chiropractor Edition)
- Powered by: LocalTuneUp (Salman Khan)
- Core Fixes: Auto Linux System Dependencies Installation, Structural Attribute Retention, JS-Force Click Submission
"""
import os
import json
import base64
import time
import logging
import sys
import traceback
import subprocess
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

# 🚀 AUTO-INSTALL PLAYWRIGHT BROWSERS & UBUNTU SYSTEM DEPENDENCIES
try:
    log.info("Step 1: Installing Playwright Chromium browser binaries...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    
    log.info("Step 2: Installing missing Linux system dependencies (Fix for Exit Code 1)...")
    subprocess.run([sys.executable, "-m", "playwright", "install-deps", "chromium"], check=True)
    log.info("🎉 Playwright and all system libraries are fully ready!")
except Exception as e:
    log.warning(f"Auto-install warning (might fail if not on Ubuntu/Root): {e}")

try:
    import google.generativeai as genai
    import gspread
    from google.oauth2.service_account import Credentials
    from playwright.sync_api import sync_playwright
    import twocaptcha
except ImportError as ie:
    log.error(f"❌ CRITICAL: Missing Python packages. Run: pip install playwright google-generativeai gspread google-auth 2captcha-python")
    sys.exit(1)

# CONFIGURATION - GitHub Secrets Verification
try:
    GEMINI_API_KEY      = os.environ["GEMINI_API_KEY"].strip()
    CAPTCHA_API_KEY     = os.environ["CAPTCHA_API_KEY"].strip()
    GOOGLE_SHEET_ID     = os.environ["GOOGLE_SHEET_ID"].strip()
    GOOGLE_CREDS_JSON   = os.environ["GOOGLE_CREDS_JSON"].strip()
except KeyError as ke:
    log.error(f"❌ CRITICAL ERROR: GitHub Secret missing in Repository Settings -> {ke}")
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-3.1-flash-lite")

# 👤 SENDER DETAILS
FIRST_NAME  = "Salman"
LAST_NAME   = "Khan"
FULL_NAME   = "Salman Khan"
COMPANY     = "LocalTuneUp"
EMAIL       = "salman@localtuneup.com"
PHONE       = "+918889652586"

SUBJECT_TEMPLATE = "Practice visibility in {city} (Quick Question)"
MESSAGE_TEMPLATE = "Hi,\n\n{intro}\n\nMany prospective patients now start their search through Google Maps, AI Overviews and ChatGPT recommendations before booking an appointment.\n\nWe're helping local practices strengthen their visibility across those channels through local authority signals, citations and industry placements.\n\nWould you be open to a quick conversation?\n\nWarm Regards,\n\nSalman Khan\nLocalTuneUp.com"

PROCESS_LIMIT = None

# Chiropractor Specific Keywords
CONTACT_KEYWORDS = ["contact", "contact-us", "contactus", "contact-form", "get-in-touch",
                    "appointment", "book", "enquire", "enquiry", "booking", "consultation",
                    "getintouch", "reach-us", "reachus", "reach-out", "write-to-us",
                    "get-started", "getstarted", "connect", "say-hello", "hello", "feedback",
                    "schedule", "schedule-now", "book-online", "online-booking", "request-appointment"]

# ------------------------------------------
#  GOOGLE SHEETS SETUP
# ------------------------------------------
def init_sheets():
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON.strip())
    except Exception as je:
        log.error("❌ CRITICAL: GOOGLE_CREDS_JSON Secret is not valid JSON format!")
        raise je

    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    
    try:
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        log.error(f"❌ CRITICAL: Google Sheet ID '{GOOGLE_SHEET_ID}' not found or service account has no access.")
        raise

    try:
        ws = sh.worksheet("websites")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("websites", rows=1000, cols=7)
        ws.update("A1:G1", [["website", "city", "status", "submitted_at", "notes", "fields_filled", "ai_actions"]])
    return ws

def get_pending_rows(ws):
    rows = ws.get_all_records()
    pending = []
    for i, row in enumerate(rows):
        url     = str(row.get("website", "")).strip()
        status  = str(row.get("status", "")).strip().lower()
        if url and status not in ("submitted",):
            pending.append((i + 1, row))
    return pending

def update_sheet_row(ws, row_num, status, notes="", fields_filled="", ai_actions=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    excel_row = row_num + 1
    headers = ws.row_values(1)
    try:
        status_idx = headers.index("status")
        start_col = chr(65 + status_idx)
        end_col = chr(65 + status_idx + 4)
        ws.update("{}{}:{}{}".format(start_col, excel_row, end_col, excel_row), [[status, now, notes, fields_filled, ai_actions]])
    except ValueError:
        ws.update("C{}:G{}".format(excel_row, excel_row), [[status, now, notes, fields_filled, ai_actions]])
    log.info(f"  [Sheets] Row {excel_row} updated -> {status}")

# ------------------------------------------
#  NAVIGATION HELPERS
# ------------------------------------------
def normalise_url(url):
    url = str(url).strip()
    if not url.startswith("http"): url = "https://" + url
    return url.rstrip("/")

def dismiss_cookie_banner(page):
    accept_texts = ["accept all", "accept all cookies", "accept cookies", "accept", "i agree", "agree", "got it", "allow all", "ok", "close"]
    try:
        buttons = page.locator("button, a, input[type='button'], [role='button']").all()
        for btn in buttons[:30]:
            try: txt = (btn.inner_text(timeout=100) or "").strip().lower()
            except: continue
            if any(t == txt for t in accept_texts):
                if btn.is_visible(timeout=100):
                    btn.click(timeout=1000)
                    return True
    except: pass
    return False

def smart_scroll(page):
    try:
        for i in range(4):
            page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {i+1} / 4);")
            time.sleep(1)
        page.evaluate("window.scrollTo(0, 0);")
        time.sleep(1)
    except: pass

def find_contact_page(page):
    current_url = page.url
    try:
        links = page.locator("a").all()
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                lt = (link.inner_text(timeout=100) or "").lower()
            except: continue
            
            if any(kw in href.lower() for kw in CONTACT_KEYWORDS) or any(kw.replace("-", " ") in lt for kw in CONTACT_KEYWORDS):
                if any(kw in current_url.lower
