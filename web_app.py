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

            # CPV არჩევა
            page.evaluate(f"() => {{ const sel = document.querySelector('#app_basecode'); if(!sel) return; for(let i=0; i<sel.options.length; i++) {{ if(sel.options[i].text.startsWith('{cpv}') || sel.options[i].text.includes(' {cpv}')) {{ sel.selectedIndex = i; sel.dispatchEvent(new Event('change')); break; }} }} }}")
            time.sleep(1) 
            
            # ძებნის ღილაკზე დაჭერა
            page.evaluate("() => { const btns = Array.from(document.querySelectorAll('span.ui-button-text')); const btn = btns.find(b => b.textContent.includes('ძებნა')); if(btn) btn.click(); }")
                
            time.sleep(3) # ველოდებით ცხრილის სერვერიდან ჩატვირთვას

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

                    # ვამოწმებთ, ემთხვევა თუ არა რომელიმე ვალიდურ თარიღს ტექსტი
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

                    extracted = page.evaluate("""() => { 
                        let buyer='უცნობი'; 
                        const pl=document.querySelector('a[onclick*="ShowProfile"]'); 
                        if(pl) buyer=pl.textContent.trim(); 
                        
                        let link=window.location.href; 
                        const pres=document.querySelectorAll('pre'); 
                        for(let pre of pres){ 
                            if(pre.textContent.includes('შესყიდვის ბმული')){ 
                                const m=pre.textContent.match(/http[s]?:\\/\\/[^\\s]+/); 
                                if(m){link=m[0].trim(); break;} 
                            } 
                        } 
                        
                        let regDate='ვერ მოიძებნა'; 
                        const tds=Array.from(document.querySelectorAll('td')); 
                        for(let j=0; j<tds.length; j++){ 
                            let t=tds[j].textContent.trim(); 
                            // უფრო მოქნილი ძებნა თარიღისთვის
                            if((t.includes('რეგისტრაციის თარიღი') || t.includes('გამოცხადების თარიღი') || t.includes('მიღება იწყება') || t.includes('გამოქვეყნების თარიღი')) && tds[j+1]) {
                                regDate=tds[j+1].textContent.trim();
                                break;
                            } 
                        } 
                        return {buyer:buyer, link:link, regDate:regDate}; 
                    }""")
                    
                    match_dt = re.search(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", extracted["regDate"])
                    if match_dt:
                        card_dt = datetime.strptime(match_dt.group(1), "%d.%m.%Y %H:%M")
                        # შემოწმება არის თუ არა თარიღი მითითებულ შუალედში
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
                        time.sleep(1.5) # პაუზა შემდეგ გვერდზე გადასვლისას გავზარდეთ
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
            time.sleep(1)
            
            page.evaluate("document.querySelector('#qep_search_btn') && document.querySelector('#qep_search_btn').click()")

            time.sleep(3) 

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

                    extracted = page.evaluate("""() => { 
                        let buyer='უცნობი', purchaseObj='-', regDate='-'; 
                        const tds=Array.from(document.querySelectorAll('td')); 
                        for(let j=0; j<tds.length; j++){ 
                            let t=tds[j].textContent.trim(); 
                            if(t.includes('შესყიდვის ობიექტის') && tds[j+1]) purchaseObj=tds[j+1].textContent.trim(); 
                            if((t.includes('რეგისტრაციის თარიღი') || t.includes('გამოცხადების თარიღი')) && tds[j+1]) {
                                regDate=tds[j+1].textContent.trim();
                                break;
                            }
                        } 
                        const pl=document.querySelector('a[onclick*="ShowProfile"]'); 
                        if(pl) buyer=pl.textContent.trim(); 
                        return {buyer:buyer, purchaseObj:purchaseObj, regDate:regDate}; 
                    }""")
                    
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
                        time.sleep(1.5)
                        try: 
                            page.wait_for_selector("tr[id^='A']", timeout=8000)
                        except: 
                            pass
                    else: 
                        break

        browser.close()
        
    return found_tenders, found_mrs