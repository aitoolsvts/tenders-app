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
                            found_mrs.append({
                                "cpv": cpv,
                                "tender_no": tender_no, 
                                "buyer": extracted["buyer"], 
                                "purchase_obj": extracted["purchaseObj"], 
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

        browser.close()
        
    return found_tenders, found_mrs

def render_result_card(item, item_type="tender"):
    border_color = "#dc3545" if item['is_priority'] else "#dee2e6"
    bg_color = "#fff5f5" if item['is_priority'] else "#f8f9fa"
    prio_badge = '<span style="background-color:#ffc107; color:#000; padding:2px 8px; border-radius:12px; font-size:12px; font-weight:bold;">🔥 პრიორიტეტი</span>' if item['is_priority'] else ''
    
    if item_type == "tender":
        st.markdown(f"""
        <div style="border: 1px solid {border_color}; border-radius: 8px; padding: 15px; margin-bottom: 15px; background-color: {bg_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h4 style="margin: 0; color: #1f2937;">{item['tender_no']}</h4>
                {prio_badge}
            </div>
            <p style="margin: 5px 0;"><strong>CPV:</strong> {get_cpv_display(item['cpv'])}</p>
            <p style="margin: 5px 0;"><strong>შემსყიდველი:</strong> {item['buyer']}</p>
            <p style="margin: 5px 0;"><strong>თარიღი:</strong> {item['reg_date']}</p>
            <a href="{item['link']}" target="_blank" style="display: inline-block; margin-top: 10px; background-color: #0d6efd; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 14px;">🔗 ბმულზე გადასვლა</a>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="border: 1px solid {border_color}; border-radius: 8px; padding: 15px; margin-bottom: 15px; background-color: {bg_color};">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h4 style="margin: 0; color: #1f2937;">{item['tender_no']}</h4>
                {prio_badge}
            </div>
            <p style="margin: 5px 0;"><strong>CPV:</strong> {get_cpv_display(item['cpv'])}</p>
            <p style="margin: 5px 0;"><strong>შემსყიდველი:</strong> {item['buyer']}</p>
            <p style="margin: 5px 0;"><strong>ობიექტი:</strong> {item['purchase_obj']}</p>
            <p style="margin: 5px 0;"><strong>თარიღი:</strong> {item['reg_date']}</p>
            <a href="https://tenders.procurement.gov.ge/public/?lang=ka" target="_blank" style="display: inline-block; margin-top: 10px; background-color: #198754; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 14px;">🔗 საიტზე გადასვლა</a>
        </div>
        """, unsafe_allow_html=True)


# --- Streamlit ინტერფეისი ---
st.set_page_config(page_title="ტენდერების მონიტორინგი", layout="wide")
st.title("ტენდერების და MRS შემოწმება")

with st.sidebar:
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
    
    priority_buyers_tags = st_tags(
        label='',
        text='დაამატეთ (Enter)',
        value=[],  
        suggestions=[],
        maxtags=-1,
        key='priority_tags'
    )

if st.button("🚀 შემოწმების დაწყება", type="primary", use_container_width=True):
    error_messages = []
    
    if not selected_cpvs:
        error_messages.append("CPV კოდები (აირჩიეთ მინიმუმ 1 კატეგორია)")
        
    if from_datetime > to_datetime:
        error_messages.append("დროის შუალედი ('საწყისი' დრო არ უნდა იყოს 'საბოლოოზე' გვიან)")
    elif (to_datetime - from_datetime).total_seconds() > (72 * 3600):
        error_messages.append("დროის შუალედი (შუალედი არ უნდა აღემატებოდეს 72 საათს)")

    if error_messages:
        for msg in error_messages:
            st.error(f"❌ გთხოვთ, შეავსოთ/შეასწოროთ სავალდებულო ველი: **{msg}**")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            tenders, mrs = run_scraping_job(selected_cpvs, priority_buyers_tags, progress_bar, status_text, from_datetime, to_datetime)
            progress_bar.progress(1.0)
            status_text.empty()
            
            if not tenders and not mrs:
                st.info("მოცემულ პარამეტრებში ახალი ტენდერი ან კვლევა (MRS) არ მოიძებნა.")
            else:
                st.success("✅ შემოწმება წარმატებით დასრულდა!")
                
                col_tenders, col_mrs = st.columns(2)
                
                with col_tenders:
                    st.subheader(f"ახალი ტენდერები ({len(tenders)})")
                    for t in tenders:
                        render_result_card(t, "tender")
                        
                with col_mrs:
                    st.subheader(f"ახალი კვლევები / MRS ({len(mrs)})")
                    for m in mrs:
                        render_result_card(m, "mrs")
                        
        except Exception as e:
            st.error(f"❌ შემოწმების დროს დაფიქსირდა შეცდომა: {e}")