import streamlit as st
from streamlit_tags import st_tags
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import re
import smtplib
import time
import urllib.request
from playwright.sync_api import sync_playwright
os.system("playwright install chromium")

# --- ძირითადი პარამეტრები ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "ai.tools.vts@gmail.com"
SENDER_PASSWORD = "yeyr xyqg wsea vjku"
SENT_ITEMS_FILE = "sent_tenders.txt"
LAST_RUN_FILE = "last_run.txt"

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

def _send_mail(subject, html_body, receiver_email, tender_no=None):
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = receiver_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=60) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, receiver_email, msg.as_string())
        if tender_no:
            save_sent_item(tender_no)
    except Exception as e:
        print(f"მეილის ერორი: {e}")

def send_tender_email(tender_no, buyer_name, purchase_link, reg_date, cpv_code, is_priority, receiver_email):
    subject = f"ტენდერი | CPV: {cpv_code} | {reg_date} | {buyer_name}"
    if is_priority:
        subject = f"🔥 [პრიორიტეტი] " + subject

    cpv_display = get_cpv_display(cpv_code)
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; {'background-color: #fff3f3; border: 2px solid red; padding: 15px;' if is_priority else 'padding: 10px;'}">
        <h2 style="{'color: red;' if is_priority else 'color: #004085;'}">
            {'🚨 ყურადღება: შენი კლიენტი გამოჩნდა!' if is_priority else 'ახალი ტენდერი ნაპოვნია'}
        </h2>
        <p><strong>CPV კოდი:</strong> {cpv_display}</p>
        <p><strong>განცხადების ნომერი:</strong> {tender_no}</p>
        <p><strong>შემსყიდველი:</strong> <span style="font-size: 1.1em; font-weight: bold; {'color: red; background-color: yellow; padding: 2px 5px;' if is_priority else 'color: #333;'}">{buyer_name}</span></p>
        <p><strong>გამოცხადების თარიღი:</strong> {reg_date}</p>
        <br>
        <p><a href="{purchase_link}" style="display: inline-block; padding: 10px 15px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">🔗 შესყიდვის ბმულზე გადასვლა</a></p>
    </body>
    </html>
    """
    _send_mail(subject, body, receiver_email, tender_no)

def send_mrs_email(tender_no, buyer_name, purchase_object, reg_date, cpv_code, is_priority, receiver_email):
    subject = f"MRS | CPV: {cpv_code} | {reg_date} | {buyer_name}"
    if is_priority:
        subject = f"🔥 [პრიორიტეტი] " + subject

    cpv_display = get_cpv_display(cpv_code)
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; {'background-color: #fff3f3; border: 2px solid red; padding: 15px;' if is_priority else 'padding: 10px;'}">
        <h2 style="{'color: red;' if is_priority else 'color: #004085;'}">
            {'🚨 ყურადღება: შენი კლიენტის კვლევა გამოჩნდა!' if is_priority else 'ახალი ბაზრის კვლევა'}
        </h2>
        <p><strong>CPV კოდი:</strong> {cpv_display}</p>
        <p><strong>რეგისტრაციის ნომერი:</strong> {tender_no}</p>
        <p><strong>შემსყიდველი:</strong> <span style="font-size: 1.1em; font-weight: bold; {'color: red; background-color: yellow; padding: 2px 5px;' if is_priority else 'color: #333;'}">{buyer_name}</span></p>
        <p><strong>შესყიდვის ობიექტი:</strong> {purchase_object}</p>
        <p><strong>რეგისტრაციის თარიღი:</strong> {reg_date}</p>
        <br>
        <p><a href="https://tenders.procurement.gov.ge/public/?lang=ka" style="display: inline-block; padding: 10px 15px; background-color: #28a745; color: white; text-decoration: none; border-radius: 5px;">🔗 საიტზე გადასვლა</a></p>
    </body>
    </html>
    """
    _send_mail(subject, body, receiver_email, tender_no)

def send_combined_tenders_email(cpv_code, tenders_list, receiver_email):
    if not tenders_list: return
    subject = f"ტენდერი {cpv_code}"
    has_priority = any(t['is_priority'] for t in tenders_list)
    cpv_display = get_cpv_display(cpv_code)
    
    items_html = ""
    for t in tenders_list:
        p_style = "background-color: #fff3f3; border: 2px solid red; padding: 15px; margin-bottom: 15px; border-radius: 5px;" if t['is_priority'] else "padding: 10px; border-bottom: 1px solid #ccc; margin-bottom: 10px;"
        buyer_style = "font-size: 1.1em; font-weight: bold; color: red; background-color: yellow; padding: 2px 5px;" if t['is_priority'] else "font-size: 1.1em; font-weight: bold; color: #333;"
        items_html += f"""
        <div style="{p_style}">
            <h3 style="{'color: red;' if t['is_priority'] else 'color: #004085;'}">
                {'🚨 ყურადღება: შენი კლიენტი გამოჩნდა!' if t['is_priority'] else 'ტენდერი'}
            </h3>
            <p><strong>განცხადების ნომერი:</strong> {t['tender_no']}</p>
            <p><strong>შემსყიდველი:</strong> <span style="{buyer_style}">{t['buyer']}</span></p>
            <p><strong>გამოცხადების თარიღი:</strong> {t['reg_date']}</p>
            <p><a href="{t['link']}" style="display: inline-block; padding: 8px 12px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">🔗 შესყიდვის ბმულზე გადასვლა</a></p>
        </div>
        """
    body = f"<html><body style='font-family: Arial; padding: 10px;'><h2 style='color: {'red' if has_priority else '#004085'};'>CPV: {cpv_display} - ახალი ({len(tenders_list)})</h2>{items_html}</body></html>"
    _send_mail(subject, body, receiver_email)
    for t in tenders_list: save_sent_item(t['tender_no'])

def send_combined_mrs_email(cpv_code, mrs_list, receiver_email):
    if not mrs_list: return
    subject = f"MRS {cpv_code}"
    has_priority = any(m['is_priority'] for m in mrs_list)
    cpv_display = get_cpv_display(cpv_code)
    
    items_html = ""
    for m in mrs_list:
        p_style = "background-color: #fff3f3; border: 2px solid red; padding: 15px; margin-bottom: 15px; border-radius: 5px;" if m['is_priority'] else "padding: 10px; border-bottom: 1px solid #ccc; margin-bottom: 10px;"
        buyer_style = "font-size: 1.1em; font-weight: bold; color: red; background-color: yellow; padding: 2px 5px;" if m['is_priority'] else "font-size: 1.1em; font-weight: bold; color: #333;"
        items_html += f"""
        <div style="{p_style}">
            <h3 style="{'color: red;' if m['is_priority'] else 'color: #004085;'}">
                {'🚨 ყურადღება: შენი კლიენტის კვლევა გამოჩნდა!' if m['is_priority'] else 'ბაზრის კვლევა'}
            </h3>
            <p><strong>რეგისტრაციის ნომერი:</strong> {m['tender_no']}</p>
            <p><strong>შემსყიდველი:</strong> <span style="{buyer_style}">{m['buyer']}</span></p>
            <p><strong>შესყიდვის ობიექტი:</strong> {m['purchase_obj']}</p>
            <p><strong>რეგისტრაციის თარიღი:</strong> {m['reg_date']}</p>
        </div>
        """
    body = f"<html><body style='font-family: Arial; padding: 10px;'><h2 style='color: {'red' if has_priority else '#004085'};'>CPV: {cpv_display} - ახალი კვლევები ({len(mrs_list)})</h2>{items_html}</body></html>"
    _send_mail(subject, body, receiver_email)
    for m in mrs_list: save_sent_item(m['tender_no'])

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

def run_scraping_job(selected_cpvs, priority_buyers, receiver_email, progress_bar, status_text, start_window, end_window):
    combined_codes = {"30200000", "31100000", "31600000", "42500000"}
    total_pages = 3

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
            cpv_tenders_found = []

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
                            if cpv in combined_codes:
                                cpv_tenders_found.append({"tender_no": tender_no, "buyer": extracted["buyer"], "link": extracted["link"], "reg_date": extracted["regDate"], "is_priority": is_prio})
                            else:
                                send_tender_email(tender_no, extracted["buyer"], extracted["link"], extracted["regDate"], cpv, is_prio, receiver_email)
                                sent_items.add(tender_no)
                    
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
            
            if cpv in combined_codes and cpv_tenders_found:
                send_combined_tenders_email(cpv, cpv_tenders_found, receiver_email)

        # --- ნაწილი 2: MRS ---
        mrs_btn = page.locator("#btn_mrs")
        if mrs_btn.count() > 0:
            mrs_btn.click()
            page.wait_for_load_state("networkidle")

        for cpv in selected_cpvs:
            current_step += 1
            progress_bar.progress(current_step / total_steps)
            status_text.text(f"MRS კვლევების ძიება: {cpv}")
            cpv_mrs_found = []

            page.evaluate(f"() => {{ const sel = document.querySelector('#qep_basecode'); if(!sel) return; for(let i=0; i<sel.options.length; i++) {{ if(sel.options[i].text.startsWith('{cpv}') || sel.options[i].text.includes(' {cpv}')) {{ sel.selectedIndex = i; sel.dispatchEvent(new Event('change')); break; }} }} }}")
            search_btn = page.locator("#qep_search_btn")
            if search_btn.count() > 0: search_btn.click()
            else: page.evaluate("document.querySelector('#qep_search_btn').click()")

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

                    extracted = page.evaluate("() => { let buyer='უცნობი', purchaseObj='-', regDate='-'; const tds=Array.from(document.querySelectorAll('td')); for(let j=0; j<tds.length; j++){ let t=tds[j].textContent.trim(); if(t==='შესყიდვის ობიექტის აღწერა'&&tds[j+1]) purchaseObj=tds[j+1].textContent.trim(); if(t==='რეგისტრაციის თარიღი'&&tds[j+1]) regDate=tds[j+1].textContent.trim(); } const pl=document.querySelector('a[onclick*=\"ShowProfile\"]'); if(pl) buyer=pl.textContent.trim(); return {buyer:buyer, purchaseObj:purchaseObj, regDate:regDate}; }")
                    
                    match_dt = re.search(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", extracted["regDate"])
                    if match_dt:
                        card_dt = datetime.strptime(match_dt.group(1), "%d.%m.%Y %H:%M")
                        if start_window <= card_dt <= end_window:
                            is_prio = check_priority(extracted["buyer"], priority_buyers)
                            if cpv in combined_codes:
                                cpv_mrs_found.append({"tender_no": tender_no, "buyer": extracted["buyer"], "purchase_obj": extracted["purchaseObj"], "reg_date": extracted["regDate"], "is_priority": is_prio})
                            else:
                                send_mrs_email(tender_no, extracted["buyer"], extracted["purchaseObj"], extracted["regDate"], cpv, is_prio, receiver_email)
                                sent_items.add(tender_no)
                    
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

            if cpv in combined_codes and cpv_mrs_found:
                send_combined_mrs_email(cpv, cpv_mrs_found, receiver_email)

        browser.close()

# --- Streamlit ინტერფეისი ---
st.set_page_config(page_title="ტენდერების მონიტორინგი", layout="wide")
st.title("ტენდერების და MRS შემოწმება")

with st.sidebar:
    st.markdown(
        """
        <style>
        div[data-testid="InputInstructions"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    st.markdown("**მიმღების ელ.ფოსტა**")
    col1, col2 = st.columns([3, 1]) 
    with col1:
        receiver_email = st.text_input("ელ.ფოსტა", "", label_visibility="collapsed", placeholder="example@gmail.com")
    with col2:
        st.button("OK", type="primary", use_container_width=True)
        
    st.caption("⚠️ თუ მეილი inbox-ში არ მოგივიდათ, გთხოვთ შეამოწმოთ Spam, Junk, Promotions ან Updates ფოლდერი.")
    st.divider() 
    
    # --- დროის შუალედი ---
    st.subheader("დროის შუალედი")
    
    now = datetime.now()
    default_to = now
    default_from = now - timedelta(hours=4)
    min_allowed_date = (now - timedelta(hours=72)).date()

    st.markdown("**საწყისი:**")
    col_from_d, col_from_t = st.columns(2)
    with col_from_d:
        from_date = st.date_input("საწყისი თარიღი", value=default_from.date(), min_value=min_allowed_date, max_value=now.date(), label_visibility="collapsed")
    with col_from_t:
        from_time = st.time_input("საწყისი დრო", value=default_from.time(), label_visibility="collapsed")
        
    st.write("") 

    st.markdown("**საბოლოო:**")
    col_to_d, col_to_t = st.columns(2)
    with col_to_d:
        to_date = st.date_input("საბოლოო თარიღი", value=default_to.date(), min_value=min_allowed_date, max_value=now.date(), label_visibility="collapsed")
    with col_to_t:
        to_time = st.time_input("საბოლოო დრო", value=default_to.time(), label_visibility="collapsed")

    from_datetime = datetime.combine(from_date, from_time)
    to_datetime = datetime.combine(to_date, to_time)
    
    st.caption("⚠️ მაქსიმალური დასაშვები შუალედია უკანასკნელი 72 საათი (3 დღე).")
    st.divider()
    
    st.subheader("CPV კოდები")
    selected_cpvs = st.multiselect(
        "ჩამოშალეთ და მონიშნეთ კატეგორიები", 
        list(CPV_DESCRIPTIONS.keys()), 
        default=[],  
        format_func=lambda x: f"{x} - {CPV_DESCRIPTIONS[x]}"
    )
    
    st.divider() 

    st.markdown('### პრიორიტეტული შემსყიდველები <span style="font-size: 0.6em; color: gray; font-weight: normal;">(არასავალდებულო)</span>', unsafe_allow_html=True)
    st.caption("⚠️ გაითვალისწინეთ: შემსყიდველის დასახელება უნდა ჩაწეროთ ზუსტად ისე, როგორც ტენდერების ოფიციალურ საიტზე წერია.")
    
    priority_buyers_tags = st_tags(
        label='',
        text='დაამატეთ (Enter)',
        value=[],  
        suggestions=[],
        maxtags=-1,
        key='priority_tags'
    )

if st.button("🚀 შემოწმების დაწყება", type="primary", use_container_width=True):
    # სავალდებულო ველების ვალიდაცია შემოწმების დაწყებამდე
    error_messages = []
    
    if not receiver_email.strip():
        error_messages.append("მიმღების ელ.ფოსტა")
        
    if not selected_cpvs:
        error_messages.append("CPV კოდები (აირჩიეთ მინიმუმ 1 კატეგორია)")
        
    if from_datetime > to_datetime:
        error_messages.append("დროის შუალედი ('საწყისი' დრო არ უნდა იყოს 'საბოლოოზე' გვიან)")
    elif (to_datetime - from_datetime).total_seconds() > (72 * 3600):
        error_messages.append("დროის შუალედი (შუალედი არ უნდა აღემატებოდეს 72 საათს)")

    # თუ სიაში ერთი შეცდომა მაინცაა, შემოწმება ჩერდება და გამოდის გაფრთხილებები
    if error_messages:
        for msg in error_messages:
            st.error(f"❌ გთხოვთ, შეავსოთ/შეასწოროთ სავალდებულო ველი: **{msg}**")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            run_scraping_job(selected_cpvs, priority_buyers_tags, receiver_email, progress_bar, status_text, from_datetime, to_datetime)
            progress_bar.progress(1.0)
            status_text.empty()
            st.success(f"✅ შემოწმება წარმატებით დასრულდა! შედეგები გაიგზავნა მისამართზე: {receiver_email}")
        except Exception as e:
            st.error(f"❌ შემოწმების დროს დაფიქსირდა შეცდომა: {e}")