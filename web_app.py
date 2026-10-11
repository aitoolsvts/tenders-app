import streamlit as st
from streamlit_tags import st_tags
from datetime import datetime, timedelta
import os
import re
import time
import urllib.request
from playwright.sync_api import sync_playwright

os.system("playwright install chromium")

SENT_ITEMS_FILE = "sent_tenders.txt"

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

def load_sent_items():
    if not os.path.exists(SENT_ITEMS_FILE):
        return set()
    try:
        with open(SENT_ITEMS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()

def save_sent_item(tender_no):
    try:
        with open(SENT_ITEMS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{tender_no}\n")
    except Exception:
        pass

def check_priority(buyer_name, priority_list):
    return any(priority_name in buyer_name for priority_name in priority_list)

def get_current_page_number(page):
    try:
        text = page.evaluate("() => { const spans = Array.from(document.querySelectorAll('span.ui-button-text')); for (let span of spans) { if (span.textContent.includes('გვერდი:')) return span.textContent.trim(); } return ''; }")
        match = re.search(r"გვერდი:\s*(\d+)/", text)
        if match: return int(match.group(1))
    except: pass
    return None

def wait_for_exact_page(page, target_page, timeout=10):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if get_current_page_number(page) == target_page: return True
        time.sleep(0.2)
    return False

def go_back_to_list(page):
    page.evaluate("() => { const elements = Array.from(document.querySelectorAll('span.ui-button-text, button, a')); const visibleBackBtns = elements.filter(el => el.textContent.trim() === 'უკან' && el.offsetWidth > 0); if (visibleBackBtns.length > 0) visibleBackBtns[visibleBackBtns.length - 1].click(); else if (typeof $ !== 'undefined') { if ($('#app_details').length) $('#app_details').hide(); if ($('#app_list').length) $('#app_list').show(); } }")
    try: page.wait_for_selector("tr[id^='A']", timeout=5000)
    except: pass

def run_scraping_job(selected_cpvs, priority_buyers, progress_bar, status_text, start_window, end_window):
    total_pages = 3
    found_tenders = []
    found_mrs = []

    valid_date_strs = []
    curr_d = start_window
    while curr_d.date() <= end_window.date():
        valid_date_strs.append(curr_d.strftime("%d.%m.%Y"))
        curr_d += timedelta(days=1)

    sent_items = load_sent_items()
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
            if search_btn.count() > 0: search_btn.click()

            try: page.wait_for_selector("tr[id^='A']", timeout=10000)
            except: continue

            page_idx = 0
            while page_idx < total_pages:
                wait_for_exact_page(page, page_idx + 1)
                rows = page.locator("tr[id^='A']")
                if rows.count() == 0: break

                i = 0
                while i < rows.count():
                    rows = page.locator("tr[id^='A']")
                    if i >= rows.count(): break
                    current_row = rows.nth(i)
                    row_text = current_row.inner_text()

                    if not any(d_str in row_text for d_str in valid_date_strs):
                        i += 1
                        continue

                    tender_no = "ვერ მოიძებნა"
                    match = re.search(r'([A-Z]{3}\d{7,10})', row_text)
                    if match: tender_no = match.group(1)

                    if tender_no in sent_items:
                        i += 1
                        continue

                    current_row.click()
                    try: page.wait_for_selector("a[onclick*='ShowProfile']", timeout=8000)
                    except: pass

                    extracted = page.evaluate("() => { let buyer='უცნობი'; const pl=document.querySelector('a[onclick*=\"ShowProfile\"]'); if(pl) buyer=pl.textContent.trim(); let link=window.location.href; const pres=document.querySelectorAll('pre'); for(let pre of pres){ if(pre.textContent.includes('შესყიდვის ბმული')){ const m=pre.textContent.match(/http[s]?:\\/\\/[^\\s]+/); if(m){link=m[0].trim(); break;} } } let regDate='ვერ მოიძებნა'; const tds=Array.from(document.querySelectorAll('td')); for(let j=0; j<tds.length; j++){ let t=tds[j].textContent.trim(); if((t==='რეგისტრაციის თარიღი'||t==='გამოცხადების თარიღი')&&tds[j+1]) regDate=tds[j+1].textContent.trim(); } return {buyer:buyer, link:link, regDate:regDate}; }")
                    
                    match_dt = re.search(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", extracted["regDate"])
                    if match_dt:
                        card_dt = datetime.strptime(match_dt.group(1), "%d.%m.%Y %H:%M")
                        if start_window <= card_dt <= end_window:
                            is_prio = check_priority(extracted["buyer"], priority_buyers)
                            found_tenders.append({
                                "cpv": cpv,
                                "tender_no": tender_no, 
                                "buyer": extracted["buyer"], 
                                "link": extracted["link"], 
                                "reg_date": extracted["regDate"], 
                                "is_priority": is_prio
                            })
                            sent_items.add(tender_no)
                            save_sent_item(tender_no)
                    
                    go_back_to_list(page)
                    i += 1
                
                page_idx += 1
                if page_idx < total_pages:
                    next_btn = page.locator("span.ui-icon-seek-next")
                    if next_btn.count() > 0:
                        next_btn.first.click()
                        try: page.wait_for_selector("tr[id^='A']", timeout=8000)
                        except: pass
                    else: break

        # --- ნაწილი 2: MRS ---
        mrs_btn = page.locator("#btn_mrs")
        if mrs_btn.count() > 0:
            mrs_btn.click()
            page.wait_for_load_state("networkidle")

        for cpv in selected_cpvs:
            current_step += 1
            progress_bar.progress(current_step / total_steps)
            status_text.text(f"MRS კვლევების ძიება: {cpv}")

            page.evaluate(f"() => {{ const sel = document.querySelector('#qep_basecode'); if(!sel) return; for(let i=0; i<sel.options.length; i++) {{ if(sel.options[i].text.startsWith('{cpv}') || sel.options[i].text.includes(' {cpv}')) {{ sel.selectedIndex = i; sel.dispatchEvent(new Event('change')); break; }} }} }}")
            search_btn = page.locator("#qep_search_btn")
            if search_btn.count() > 0: search_btn.click()
            else: page.evaluate("document.querySelector('#qep_search_btn').click()")

            try: