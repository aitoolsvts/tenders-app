import streamlit as st
from streamlit_tags import st_tags
from datetime import datetime, timedelta
import os
import re
import time
import urllib.request
from playwright.sync_api import sync_playwright

os.system("playwright install chromium")

@st.cache_data(ttl=86400) 
def fetch_all_cpvs():
    cpv_dict = {}
    try:
        req = urllib.request.Request(
            "https://tenders.procurement.gov.ge/public/?lang=ka",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
        
        block = re.search(r'<select[^>]*id="app_basecode"[^>]*>(.*?)</select>', html, re.DOTALL)
        if block:
            options = re.findall(r'<option[^>]*>([^<]+)</option>', block.group(1))
            for opt in options:
                opt = opt.strip()
                match = re.match(r'^(\d{8})\s*-\s*(.+)$', opt)
                if match:
                    code = match.group(1)
                    name = match.group(2)
                    if any(c in '123456789' for c in code[:3]):
                        cpv_dict[code] = name
    except Exception as e:
        print(f"CPV კოდების ჩამოტვირთვის შეცდომა: {e}")
        
    if not cpv_dict:
        cpv_dict = {
            "30200000": "კომპიუტერული მოწყობილობები და აქსესუარები",
            "32400000": "ქსელები",
            "72200000": "პროგრამული უზრუნველყოფის შემუშავება"
        }
    return cpv_dict

CPV_DESCRIPTIONS = fetch_all_cpvs()

def get_cpv_display(cpv_code):
    desc = CPV_DESCRIPTIONS.get(cpv_code, "")
    if desc:
        return f"{cpv_code} - {desc}"
    return cpv_code

def check_priority(buyer_name, priority_list):
    return any(priority_name in buyer_name for priority_name in priority_list)

def get_current_page_number(page):
    try:
        text = page.evaluate("() => { const spans = Array.from(document.querySelectorAll('span.ui-button-text')); for (let span of spans) { if (span.textContent.includes('გვერდი:')) return span.textContent.trim(); } return ''; }")
        match = re.search(r"გვერდი:\s*(\d+)/", text)
        if match: 
            return int(match.group(1))
    except: 
        pass
    return None

def wait_for_exact_page(page, target_page, timeout=10):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if get_current_page_number(page) == target_page: 
            return True
        time.sleep(0.2)
    return False

def go_back_to_list(page):
    page.evaluate("() => { const elements = Array.from(document.querySelectorAll('span.ui-button-text, button, a')); const visibleBackBtns = elements.filter(el => el.textContent.trim() === 'უკან' && el.offsetWidth > 0); if (visibleBackBtns.length > 0) visibleBackBtns[visibleBackBtns.length - 1].click(); else if (typeof $ !== 'undefined') { if ($('#app_details').length) $('#app_details').hide(); if ($('#app_list').length) $('#app_list').show(); } }")
    try: 
        page.wait_for_selector("tr[id^='A']", timeout=5000)
    except: 
        pass

def run_scraping_job(selected_cpvs, priority_buyers, progress_bar, status_text, start_window, end_window):
    total_pages = 3
    found_tenders = []
    found_mrs = []

    valid_date_strs = []
    curr_d = start_window
    while curr_d.date() <= end_window.date():
        valid_date_strs.append(curr_d.strftime("%d.%m.%Y"))
        curr_d += timedelta(days=1)

    total_steps = len(selected_cpvs) * 2
    current_step = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        status_text.text("საიტზე შესვლა...")
        page.goto("https://tenders.procurement.gov.ge/public/?lang=ka", timeout=60000)
        page.wait_for_load_state("networkidle")

        # --- ნაწილი 1: ტენდერები ---
        for cpv in selected_cpvs:
            current_step += 1
            progress_bar.progress(current_step / total_steps)
            status_text.text(f"ტენდერების ძიება: {cpv}")

            page.evaluate(f"() => {{ const sel = document.querySelector('#app_basecode'); if(!sel) return; for(let i=0; i<sel.options.length; i++) {{ if(sel.options[i].text.startsWith('{cpv}') || sel.options[i].text.includes(' {cpv}')) {{ sel.selectedIndex = i; sel.dispatchEvent(new Event('change')); break; }} }} }}")
            search_btn = page.locator("span.ui-button-text", has_text="ძებნა").first
            if search_btn.count() > 0: 
                search_btn.click()

            try: 
                page.wait_for_selector("tr[id^='A']", timeout=10000)
            except: 
                continue

            page_idx = 0
            while page_idx < total_pages:
                wait_for_exact_page(page, page_idx + 1)
                rows = page.locator("tr[id^='A']")
                if rows.count() == 0: 
                    break

                i = 0
                while i < rows.count():
                    rows = page.locator("tr[id^='A']")
                    if i >= rows.count(): 
                        break
                    current_row = rows.nth(i)
                    row_text = current_row.inner_text()

                    if not any(d_str in row_text for d_str in valid_date_strs):
                        i += 1
                        continue

                    tender_no = "ვერ მოიძებნა"
                    match = re.search(r'([A-Z]{3}\d{7,10})', row