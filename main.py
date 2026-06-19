# -*- coding: utf-8 -*-
"""
Hyper-Personalized AI Contact Form Bot (Chiropractors Edition)
- Powered by: LocalTuneUp (Salman Khan)
- Google Sheets: Dynamic City + Dynamic Intro
- Gemini AI: Website ka name, main chiropractic/wellness service, aur milestone read karke custom line banata hai
"""
import os
import json
import base64
import time
import logging
import sys
import traceback
from datetime import datetime

import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
import twocaptcha

# ------------------------------------------
#  CONFIGURATION - GitHub Secrets se aata hai
# ------------------------------------------

GEMINI_API_KEY      = os.environ["GEMINI_API_KEY"].strip()
CAPTCHA_API_KEY     = os.environ["CAPTCHA_API_KEY"].strip()
GOOGLE_SHEET_ID     = os.environ["GOOGLE_SHEET_ID"].strip()
GOOGLE_CREDS_JSON   = os.environ["GOOGLE_CREDS_JSON"].strip()

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-3.1-flash-lite")

# 👤 SENDER DETAILS
FIRST_NAME  = "Salman"
LAST_NAME   = "Khan"
FULL_NAME   = "Salman Khan"
COMPANY     = "LocalTuneUp"
EMAIL       = "salman@localtuneup.com"
PHONE       = "+918889652586"

# 🎯 Updated for Chiropractors
SUBJECT_TEMPLATE = "Chiropractic practice visibility in {city} (Quick Question)"

# 🎯 Updated Pitch for Chiropractic & Wellness Patients
MESSAGE_TEMPLATE = "Hi,\n\n{intro}\n\nMany prospective patients now start their search through Google Maps, AI Overviews and ChatGPT recommendations before booking an appointment.\n\nWe're helping chiropractic practices strengthen their visibility across those channels through local authority signals, citations and wellness-industry placements.\n\nWould you be open to a quick conversation?\n\nWarm Regards,\n\nSalman Khan\nLocalTuneUp.com"

PROCESS_LIMIT = None

CONTACT_KEYWORDS = ["contact", "contact-us", "contactus", "contact-form", "get-in-touch",
                    "getintouch", "reach-us", "reachus", "reach-out", "write-to-us",
                    "get-started", "getstarted", "start-here", "enquiry", "enquire",
                    "enquiries", "inquiry", "inquire", "lets-talk", "let-s-talk", "lets-connect",
                    "work-with-us", "hire-us", "hire", "start-project", "start-a-project",
                    "request-quote", "request-a-quote", "get-a-quote", "get-quote", "quote",
                    "book-a-call", "book-call", "book-a-consultation", "book-consultation",
                    "free-consultation", "free-audit", "free-quote", "schedule", "schedule-a-call",
                    "consultation", "talk-to-us", "connect", "connect-with-us", "say-hello",
                    "hello", "support", "help", "get-in-touch-with-us", "contact-sales"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

# ------------------------------------------
#  GOOGLE SHEETS SETUP
# ------------------------------------------

def init_sheets():
    creds_dict = json.loads(GOOGLE_CREDS_JSON.strip())
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
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
    log.info("  [Sheets] Row {} -> {}".format(excel_row, status))

# ------------------------------------------
#  URL HELPERS & COOKIE DISMISS
# ------------------------------------------

def normalise_url(url):
    url = str(url).strip()
    if not url.startswith("http"): url = "https://" + url
    return url.rstrip("/")

def dismiss_cookie_banner(page):
    accept_texts = ["accept all", "accept all cookies", "accept cookies", "accept", "i agree", "agree", "got it", "allow all", "ok", "close"]
    selectors = "button, a, input[type='button'], [role='button'], div, span"
    try:
        buttons = page.locator(selectors).all()
        for btn in buttons[:50]:
            try: txt = (btn.inner_text(timeout=200) or "").strip().lower()
            except: continue
            if any(t == txt for t in accept_texts):
                if btn.is_visible(timeout=200):
                    btn.click(timeout=1000)
                    return True
    except: pass
    return False

def find_contact_page(page, base_url):
    current_url = page.url
    try: page.wait_for_load_state("networkidle", timeout=4000)
    except: pass
    try:
        links = page.locator("a").all()
        for link in links:
            href = link.get_attribute("href") or ""
            try: lt = (link.inner_text(timeout=200) or "").lower()
            except: lt = ""
            if any(kw in href.lower() for kw in CONTACT_KEYWORDS) or any(kw.replace("-", " ") in lt for kw in CONTACT_KEYWORDS):
                if any(kw in current_url.lower() for kw in CONTACT_KEYWORDS): return True
                try:
                    link.click()
                    page.wait_for_load_state("domcontentloaded", timeout=6000)
                    return True
                except: pass
    except: pass
    return any(kw in current_url.lower() for kw in CONTACT_KEYWORDS)

# ------------------------------------------
#  CAPTCHA SOLVER
# ------------------------------------------

def solve_captcha(page, website):
    solver = twocaptcha.TwoCaptcha(CAPTCHA_API_KEY)
    try:
        frame = page.locator('iframe[src*="recaptcha"]').first
        if frame.is_visible(timeout=500):
            src = frame.get_attribute("src") or ""
            sitekey = ""
            for part in src.split("&"):
                if "k=" in part: sitekey = part.split("k=")[1].split("&")[0]; break
            if sitekey:
                log.info("  [CAPTCHA] Solving reCAPTCHA...")
                result = solver.recaptcha(sitekey=sitekey, url=website)
                token = result["code"]
                page.evaluate(f"document.getElementById('g-recaptcha-response').innerHTML = '{token}';")
                return True
    except: pass
    return False

# ------------------------------------------
#  HYPER-PERSONALIZATION ENGINE (CHIROPRACTOR SPECIFIC)
# ------------------------------------------

def get_page_text(page):
    try:
        return page.evaluate("""() => {
            let out = '';
            document.querySelectorAll('h1,h2,h3,p,title').forEach(el => {
                if (el.innerText) out += el.innerText.trim() + ' | ';
            });
            return out;
        }""")[:4000]
    except: return ""

def generate_personalized_line(page, website, city):
    site_text = get_page_text(page)
    backup_line = f"I noticed your clinic focuses on professional chiropractic care and spinal health for patients throughout {city}."
    
    if len(site_text.strip()) < 50:
        return backup_line

    prompt = """You are an expert copywriter writing a personalized opening line for a B2B sales message.
Target Audience: A Chiropractor, Spine Specialist, Physical Therapist, or Wellness Clinic located in or serving the city of '{city}'.

Here is the scraped text from their website ({website}):
---
{site_text}
---

Your task is to draft exactly ONE natural, high-converting opening sentence.
Rules:
1. Find the actual Practice/Clinic/Doctor Name (e.g., "Back in Motion Chiropractic" or "Dr. Smith Wellness") from the text. If you can't find it clearly, use "your practice".
2. Identify their primary care focus or treatment specialty (e.g., spinal adjustments, sciatica relief, chronic back pain treatment, decompression therapy, sports injury rehabilitation).
3. Merge them into a fluid sentence matching this exact style: "I noticed [Clinic Name/your practice] focuses on [Specialty/Service] for patients throughout {city}."
4. If they mention a big milestone (like 'over 20 years of spinal care experience' or 'helping thousands of local families stay pain-free'), you can optionally blend it in naturally.
5. DO NOT sound robotic. Keep it under 25 words.
6. Return ONLY the sentence. No quotes, no markdown, no conversational filler.

Example Output: I noticed Back in Motion Chiropractic focuses on advanced spinal adjustments and chronic pain relief for patients throughout {city}."""

    prompt = prompt.format(website=website, site_text=site_text, city=city)

    for attempt in range(3):
        try:
            resp = gemini_model.generate_content(prompt)
            if not resp or not resp.text:
                continue
            raw = resp.text.strip()
            if raw:
                line = raw.replace("```", "").strip().strip('"').strip("'").strip().split("\n")[0]
                if len(line.split()) > 5 and len(line) < 200:
                    log.info(f"  [AI Hyper-Personalized Line]: {line}")
                    return line
        except Exception as e:
            time.sleep(3)
            
    return backup_line

# ------------------------------------------
#  AI FORM ANALYSIS & EXECUTION
# ------------------------------------------

def ask_gemini(page, website, subject, message):
    page_html = get_page_html(page)
    prompt = """You are a web automation expert. Fill this contact form on: {website}
Form HTML:
{html}

Details to fill:
- Full Name: {full_name}
- Email: {email}
- Phone: {phone}
- Subject: {subject}
- Message:
{message}

Return ONLY a JSON array of actions. Format:
[ {{"action": "fill", "selector": "css_selector", "value": "value"}}, {{"action": "click", "selector": "submit_css_selector"}} ]"""
    
    prompt = prompt.format(website=website, html=page_html, full_name=FULL_NAME, email=EMAIL, phone=PHONE, subject=subject, message=message)
    
    try:
        resp = gemini_model.generate_content(prompt)
        if not resp or not resp.text:
            return []
            
        raw = resp.text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
            
        if not raw.strip():
            return []
            
        return json.loads(raw.strip())
    except Exception as e:
        log.error(f"Failed to parse Gemini Form Response safely: {e}")
        return []

def get_page_html(page):
    try:
        return page.evaluate("() => Array.from(document.querySelectorAll('input, textarea, button, select, label, form')).map(el => el.outerHTML).join('\\n')")[:18000]
    except: return ""

def execute_actions(page, actions):
    filled = []
    submitted = False
    if not actions:
        return filled, submitted
        
    for action in actions:
        act = action.get("action", "").lower()
        sel = action.get("selector", "")
        val = action.get("value", "")
        if not sel: continue
        try:
            loc = page.locator(sel).first
            if act == "fill" and loc.is_visible(timeout=1000):
                loc.fill(val)
                filled.append(sel[:20])
            elif act == "click" and loc.is_visible(timeout=1000):
                url_before = page.url
                loc.click(timeout=4000)
                time.sleep(4)
                if page.url != url_before or "thank" in page.content().lower() or "sent" in page.content().lower():
                    submitted = True
        except: pass
    return filled, submitted

# ------------------------------------------
#  MAIN RUNNER
# ------------------------------------------

def main():
    ws = init_sheets()
    pending = get_pending_rows(ws)
    if not pending: log.info("No pending sites."); return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        pg = context.new_page()
        pg.set_default_timeout(20000)

        for row_idx, row
