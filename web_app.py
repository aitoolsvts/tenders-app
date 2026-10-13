import streamlit as st
import pandas as pd
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

# --- შემსყიდველების ფაილის ჩატვირთვა ---
@st.cache_data
def load_buyers():
    try:
        df = pd.read_csv('buyers.csv')
        return df['Buyer_Name'].dropna().tolist()
    except Exception as e:
        print(f"შემსყიდველების ფაილის (buyers.csv) წაკითხვის შეცდომა: {e}")
        return []

BUYERS_LIST = load_buyers()

# --- შემსყიდველების ძიების ფუნქცია ---
def search_buyers(term, buyers):
    term = term.lower()
    matches = []
    for buyer in buyers:
        # მოვაშოროთ ბრჭყალები და სასვენი ნიშნები, დავშალოთ სიტყვებად
        clean_buyer = re.sub(r'[^\w\s]', ' ', buyer)
        words = clean_buyer.lower().split()
        # ვამოწმებთ, რომელიმე სიტყვა ხომ არ იწყება საძიებო ტერმინით
        if any(w.startswith(term) for w in words):
            matches.append(buyer)
    return matches

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
        
        # --- რესურსების ბლოკირება აჩქარებისთვის ---
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())

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
                    match = re.search(r'([A-Z]{3}\d{7,10})', row_text)
                    if match: 
                        tender_no = match.group(1)

                    current_row.click()
                    try: 
                        page.wait_for_selector("a[onclick*='ShowProfile']", timeout=8000)
                    except: 
                        pass

                    extracted = page.evaluate("() => { let buyer='უცნობი'; const pl=document.querySelector('a[onclick*=\"ShowProfile\"]'); if(pl) buyer=pl.textContent.trim(); let link=window.location.href; const pres=document.querySelectorAll('pre'); for(let pre of pres){ if(pre.textContent.includes('შესყიდვის ბმული')){ const m=pre.textContent.match(/http[s]?:\\/\\/[^\\s]+/); if(m){link=m[0].trim(); break;} } } let regDate='ვერ მოიძებნა'; const tds=Array.from(document.querySelectorAll('td')); for(let j=0; j<tds.length; j++){ let t=tds[j].textContent.trim(); if((t==='რეგისტრაციის თარიღი'||t==='გამოცხადების თარიღი'||t==='შესყიდვის გამოცხადების თარიღი')&&tds[j+1]) { regDate=tds[j+1].textContent.trim(); break; } } return {buyer:buyer, link:link, regDate:regDate}; }")
                    
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
                    
                    go_back_to_list(page)
                    i += 1
                
                page_idx += 1
                if page_idx < total_pages:
                    next_btn = page.locator("span.ui-icon-seek-next")
                    if next_btn.count() > 0:
                        next_btn.first.click()
                        try: 
                            page.wait_for_selector("tr[id^='A']", timeout=8000)
                        except: 
                            pass
                    else: 
                        break

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
            if search_btn.count() > 0: 
                search_btn.click()
            else: 
                page.evaluate("document.querySelector('#qep_search_btn').click()")

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
                    match = re.search(r'([A-Z]{3}\d{7,10})', row_text)
                    if match: 
                        tender_no = match.group(1)

                    current_row.click()
                    try: 
                        page.wait_for_selector("a[onclick*='ShowProfile']", timeout=8000)
                    except: 
                        pass

                    extracted = page.evaluate("() => { let buyer='უცნობი', purchaseObj='-', regDate='-'; const tds=Array.from(document.querySelectorAll('td')); for(let j=0; j<tds.length; j++){ let t=tds[j].textContent.trim(); if(t==='შესყიდვის ობიექტის აღწერა'&&tds[j+1]) purchaseObj=tds[j+1].textContent.trim(); if(t==='რეგისტრაციის თარიღი'&&tds[j+1]) { regDate=tds[j+1].textContent.trim(); break; } } const pl=document.querySelector('a[onclick*=\"ShowProfile\"]'); if(pl) buyer=pl.textContent.trim(); return {buyer:buyer, purchaseObj:purchaseObj, regDate:regDate}; }")
                    
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
                    
                    go_back_to_list(page)
                    i += 1
                
                page_idx += 1
                if page_idx < total_pages:
                    next_btn = page.locator("span.ui-icon-seek-next")
                    if next_btn.count() > 0:
                        next_btn.first.click()
                        try: 
                            page.wait_for_selector("tr[id^='A']", timeout=8000)
                        except: 
                            pass
                    else: 
                        break

        browser.close()
        
    return found_tenders, found_mrs

def render_result_card(item, item_type="tender"):
    with st.container(border=True):
        col1, col2 = st.columns([3, 2])
        
        with col1:
            st.markdown(f"#### {item['tender_no']}")
        with col2:
            if item.get('is_priority'):
                st.error("🔥 პრიორიტეტი")
                
        st.markdown(f"**CPV:** {get_cpv_display(item['cpv'])}")
        st.markdown(f"**შემსყიდველი:** {item['buyer']}")
        
        if item_type == "tender":
            st.markdown(f"**თარიღი:** {item['reg_date']}")
            st.link_button("🔗 ბმულზე გადასვლა", item['link'])
        else:
            st.markdown(f"**ობიექტი:** {item['purchase_obj']}")
            st.markdown(f"**თარიღი:** {item['reg_date']}")
            st.link_button("🔗 საიტზე გადასვლა", "https://tenders.procurement.gov.ge/public/?lang=ka")

# თბილისის დროის დამდგენი ფუნქცია (Cloud-ის UTC სერვერისთვის)
def get_tbilisi_time():
    return datetime.utcnow() + timedelta(hours=4)

# --- Streamlit ინტერფეისი ---
st.set_page_config(page_title="ტენდერების მონიტორინგი", layout="wide")
st.title("ტენდერების და MRS შემოწმება")

with st.sidebar:
    # ეკრანის ჩამოსქროლვისას ისრების/ღილაკის დამაგრება (Sticky / Fixed)
    st.markdown(
        """
        <style>
        /* ღია მარცხენა პანელის დახურვის ისარი/ღილაკი */
        [data-testid="stSidebarHeader"], 
        [data-testid="stSidebar"] > div:first-child > div:first-child {
            position: sticky !important;
            top: 0px !important;
            z-index: 9999 !important;
            background-color: inherit !important;
        }
        /* დახურული პანელის გამოსახსნელი ისარი */
        [data-testid="collapsedControl"] {
            position: fixed !important;
            top: 15px !important;
            z-index: 9999 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    st.subheader("დროის შუალედი")
    
    # Session State-ის გამოყენება თარიღების დასამახსოვრებლად (თბილისის დროით)
    if "time_initialized" not in st.session_state:
        init_now = get_tbilisi_time()
        st.session_state.default_to = init_now
        st.session_state.default_from = init_now - timedelta(hours=4)
        st.session_state.time_initialized = True

    now_current = get_tbilisi_time()
    min_allowed_date = (now_current - timedelta(hours=72)).date()

    # დაზღვევა, რომ ძველი სესიის თარიღი არ ჩამოცდეს 72 საათიან ლიმიტს
    safe_start_date = max(st.session_state.default_from.date(), min_allowed_date)
    safe_end_date = min(st.session_state.default_to.date(), now_current.date())

    st.markdown("**საწყისი:**")
    col_from_d, col_from_t = st.columns(2)
    with col_from_d:
        from_date = st.date_input("საწყისი თარიღი", value=safe_start_date, min_value=min_allowed_date, max_value=now_current.date(), label_visibility="collapsed")
    with col_from_t:
        from_time = st.time_input("საწყისი დრო", value=st.session_state.default_from.time(), label_visibility="collapsed")
        
    st.write("") 

    st.markdown("**საბოლოო:**")
    col_to_d, col_to_t = st.columns(2)
    with col_to_d:
        to_date = st.date_input("საბოლოო თარიღი", value=safe_end_date, min_value=min_allowed_date, max_value=now_current.date(), label_visibility="collapsed")
    with col_to_t:
        to_time = st.time_input("საბოლოო დრო", value=st.session_state.default_to.time(), label_visibility="collapsed")

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

    # --- პრიორიტეტული შემსყიდველების ახალი ლოგიკა ---
    st.markdown('### პრიორიტეტული შემსყიდველები <span style="font-size: 0.6em; color: gray; font-weight: normal;">(არასავალდებულო)</span>', unsafe_allow_html=True)
    
    # ვინახავთ არჩეულ კლიენტებს სესიაში
    if "priority_buyers" not in st.session_state:
        st.session_state.priority_buyers = []

    search_term = st.text_input("🔎 მოძებნეთ შემსყიდველი (მინ. 3 ასო)")

    if search_term and len(search_term.strip()) >= 3:
        term = search_term.strip()
        matches = search_buyers(term, BUYERS_LIST)
        
        if matches:
            # ვფილტრავთ იმ შედეგებს, რაც უკვე სიაში გვაქვს
            available_matches = [m for m in matches if m not in st.session_state.priority_buyers]
            if available_matches:
                selected_to_add = st.multiselect("ნაპოვნია (აირჩიეთ და დაამატეთ):", available_matches)
                if selected_to_add:
                    if st.button("➕ სიაში დამატება"):
                        st.session_state.priority_buyers.extend(selected_to_add)
                        st.rerun()
            else:
                st.caption("ნაპოვნი შემსყიდველები უკვე დამატებულია თქვენს სიაში.")
        else:
            st.caption("მსგავსი შემსყიდველი ვერ მოიძებნა.")
            
    elif search_term and len(search_term.strip()) > 0 and len(search_term.strip()) < 3:
        st.caption("ჩაწერეთ მინიმუმ 3 სიმბოლო მოსაძებნად...")

    # ვაჩვენოთ უკვე არჩეული კლიენტების სია
    if st.session_state.priority_buyers:
        st.write("")
        st.markdown("**📌 თქვენი სია:**")
        updated_buyers = st.multiselect(
            "წასაშლელად გააუქმეთ მონიშვნა (X):",
            options=st.session_state.priority_buyers,
            default=st.session_state.priority_buyers,
            label_visibility="collapsed"
        )
        # თუ მომხმარებელმა სიაში რამე წაშალა, ვაახლებთ მეხსიერებას
        if set(updated_buyers) != set(st.session_state.priority_buyers):
            st.session_state.priority_buyers = updated_buyers
            st.rerun()

st.write("")
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
            # აქ უკვე გადაეცემა st.session_state.priority_buyers
            tenders, mrs = run_scraping_job(selected_cpvs, st.session_state.priority_buyers, progress_bar, status_text, from_datetime, to_datetime)
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