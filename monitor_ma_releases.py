
#!/usr/bin/env python3
"""
M&A Press Release Monitoring Script with Smart Deduplication
Automatically pulls M&A press releases from Business Wire via Official RSS Feed,
extracts contact info using Selenium (headless Chrome) to bypass blocks,
generates enhanced reports, and commits to GitHub.

Runs hourly via GitHub Actions.
"""

import os
import sys
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import subprocess
import re
import time
import random
import xml.etree.ElementTree as ET

# Auto-install dependencies if missing
try:
    import selenium
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium", "webdriver-manager"])

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configuration
RSS_URL = "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFtRWA=="
GITHUB_REPO_PATH = "/home/ubuntu/acquisitions"
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def log(message):
    """Print timestamped log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def trigger_webhook(report_date, total_acquisitions, report_file):
    """Trigger Make.com webhook with report data"""
    webhook_url = "https://hook.us2.make.com/4c7xqjcjt3yxhbdvnxkw5u6qxr6cqb3y"
    github_url = f"https://github.com/bdouglas73/acquisitions/blob/main/{report_file}"
    
    payload = {
        "report_date": report_date,
        "report_type": "enhanced",
        "total_acquisitions": total_acquisitions,
        "github_url": github_url,
        "report_file": report_file
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code == 200:
            log(f"Successfully triggered webhook for {report_file}")
            return True
        else:
            log(f"Webhook returned status {response.status_code}")
            return False
    except Exception as e:
        log(f"Failed to trigger webhook: {e}")
        return False

def get_today_date():
    """Get today's date in YYYY-MM-DD format"""
    return datetime.now().strftime("%Y-%m-%d")

def normalize_url(url):
    """Normalize URL for comparison (remove protocol, query params)"""
    if not url:
        return ""
    # Remove protocol
    url = re.sub(r'^https?://', '', url)
    # Remove query params
    url = url.split('?')[0]
    # Remove trailing slash
    if url.endswith('/'):
        url = url[:-1]
    return url.lower()

def get_existing_entries_from_report(report_path):
    """
    Extract existing entries from the report to preserve them
    Returns list of dicts
    """
    if not os.path.exists(report_path):
        return []
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        entries = []
        sections = content.split('\n---\n')
        
        for section in sections:
            if not section.strip():
                continue
                
            url_match = re.search(r'\*\*Link:\*\* \[.*?\]\((.*?)\)', section)
            title_match = re.search(r'## (.*?)\n', section)
            summary_match = re.search(r'\*\*Summary:\*\* (.*?)\n', section, re.DOTALL)
            
            if url_match and title_match:
                url = url_match.group(1)
                title = title_match.group(1)
                summary = summary_match.group(1).strip() if summary_match else ""
                
                # Extract contacts block
                contacts_block = ""
                if "**Contact Information:**" in section:
                    contacts_block = section.split("**Contact Information:**")[1].strip()
                
                entries.append({
                    'title': title,
                    'url': url,
                    'summary': summary,
                    'contacts_block': contacts_block,
                    'raw_section': section
                })
                
        log(f"Found {len(entries)} existing entries in report")
        return entries
    
    except Exception as e:
        log(f"Error reading existing report: {e}")
        return []

def fetch_from_rss_feed():
    """
    Fetch press releases from Business Wire Official RSS feed
    Returns list of dicts with title, url, time, summary
    """
    log(f"Fetching press releases from Business Wire RSS: {RSS_URL}")
    
    try:
        headers = {
            'User-Agent': USER_AGENT
        }
        response = requests.get(RSS_URL, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        press_releases = []
        
        for item in items:
            title = item.find('title').text
            link = item.find('link').text
            pub_date = item.find('pubDate').text
            description = item.find('description').text if item.find('description') is not None else ""
            
            # Clean up title if needed
            if " - Business Wire" in title:
                title = title.replace(" - Business Wire", "")
            
            # Clean up link (remove tracking params if present)
            if "?feedref=" in link:
                link = link.split("?feedref=")[0]
            
            press_releases.append({
                'title': title,
                'url': link,
                'time': pub_date,
                'summary': description
            })
            
        log(f"Found {len(press_releases)} press releases in RSS feed")
        return press_releases
        
    except Exception as e:
        log(f"Error fetching RSS feed: {e}")
        return []

def setup_driver():
    """Setup headless Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(f"user-agent={USER_AGENT}")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except:
        driver = webdriver.Chrome(options=chrome_options)
        
    return driver

def extract_contact_info(pr_data, driver):
    """
    Extract contact information from a single press release
    """
    url = pr_data['url']
    log(f"  Extracting contacts from: {pr_data['title'][:30]}...")
    
    try:
        driver.get(url)
        
        # Wait for body to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        time.sleep(2)
        content = driver.page_source
        
        if "Access Denied" in content or "Please enable JS" in content:
            log("  Access Denied/Challenge via Selenium")
            return None
            
        soup = BeautifulSoup(content, 'html.parser')
        
        # Update summary if possible
        summary = pr_data['summary']
        article_body = soup.find('div', class_=re.compile(r'bw-release-body|release-body|bw-release-main'))
        if not article_body:
            article_body = soup.find('div', itemprop='articleBody')
            
        if article_body:
            paragraphs = article_body.find_all('p')
            summary_parts = []
            for p in paragraphs[:3]:
                text = p.get_text(strip=True)
                if text and len(text) > 50:
                    summary_parts.append(text)
            if summary_parts:
                summary = ' '.join(summary_parts)[:800]
        
        contacts = []
        
        # Strategy 1: Look for structured contact divs (bw-release-contact)
        contact_sections = soup.find_all('div', id=lambda x: x and x.startswith('bw-release-contact'))
        if not contact_sections:
            contact_sections = soup.find_all('div', class_=re.compile(r'bw-release-contact|contacts'))
            
        if contact_sections:
            for section in contact_sections:
                contact_text = section.get_text(separator='\n', strip=True)
                lines = [line.strip() for line in contact_text.split('\n') if line.strip()]
                
                current_contact = {}
                
                for i, line in enumerate(lines):
                    # Check for email
                    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', line)
                    
                    if email_match:
                        email = email_match.group()
                        
                        if 'email' in current_contact:
                            contacts.append(current_contact)
                            current_contact = {}
                        
                        current_contact['email'] = email
                        
                        # Look backwards for name/title
                        if i > 0:
                            prev_line = lines[i-1]
                            
                            # Skip generic labels
                            if re.search(r'^(Email|Contact|Media Contact|Press Contact):?$', prev_line, re.IGNORECASE) or prev_line.endswith(':'):
                                if i > 1:
                                    prev_line = lines[i-2]
                                    name_idx = i-2
                                else:
                                    prev_line = ""
                                    name_idx = -1
                            else:
                                name_idx = i-1
                                
                            if prev_line and not re.search(r'@|http|www', prev_line) and len(prev_line) < 100:
                                
                                # Check if prev_line is likely a title
                                is_title = any(t in prev_line for t in ["Head", "VP", "Director", "Manager", "Officer", "Chief", "President", "Lead", "Partner"])
                                
                                if is_title and name_idx > 0:
                                    prev_prev = lines[name_idx-1]
                                    if not re.search(r'@|http|www|Contact:', prev_prev) and len(prev_prev) < 100:
                                        if not prev_prev.startswith("For "):
                                            current_contact['name'] = prev_prev
                                            current_contact['title'] = prev_line
                                        else:
                                            current_contact['name'] = prev_line
                                            current_contact['company'] = prev_prev
                                else:
                                    current_contact['name'] = prev_line
                                    if name_idx > 0:
                                        prev_prev = lines[name_idx-1]
                                        if not re.search(r'@|http|www|Contact:', prev_prev) and len(prev_prev) < 100:
                                            if prev_prev.startswith("For "):
                                                current_contact['company'] = prev_prev
                        
                        # Handle "Name for Company" pattern
                        if 'name' in current_contact and ' for ' in current_contact['name']:
                            parts = current_contact['name'].split(' for ')
                            if len(parts) == 2:
                                current_contact['name'] = parts[0]
                                current_contact['company'] = parts[1]

                        # Look for phone
                        phone_match = re.search(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', line)
                        if phone_match:
                            current_contact['phone'] = phone_match.group()
                        elif i + 1 < len(lines):
                            next_line = lines[i+1]
                            phone_match = re.search(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', next_line)
                            if phone_match:
                                current_contact['phone'] = phone_match.group()
                                
                        # Save raw block
                        raw_lines = []
                        start_idx = max(0, i-3)
                        end_idx = min(len(lines), i+2)
                        for k in range(start_idx, end_idx):
                            raw_lines.append(lines[k])
                        current_contact['raw_block'] = '\n'.join(raw_lines)
                        
                        contacts.append(current_contact)
                        current_contact = {}

        # Deduplicate contacts based on email
        unique_contacts = []
        seen_emails = set()
        for c in contacts:
            email = c.get('email', '').strip().lower()
            if email and email not in seen_emails:
                unique_contacts.append(c)
                seen_emails.add(email)
        contacts = unique_contacts
        
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': summary,
            'contacts': contacts,
            'success': True
        }
        
    except Exception as e:
        log(f"  Error extracting contacts: {e}")
        return None

def generate_markdown_report(acquisitions, date_str):
    """Generate Markdown report content"""
    report = f"# M&A Acquisitions Report - {date_str}\n\n"
    report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"Total Acquisitions: {len(acquisitions)}\n\n"
    
    for acq in acquisitions:
        report += f"## {acq['title']}\n\n"
        report += f"**Date:** {date_str}\n"
        report += f"**Link:** [{acq['title']}]({acq['url']})\n\n"
        report += f"**Summary:** {acq['summary']}\n\n"
        
        report += "**Contact Information:**\n"
        
        if 'contacts_block' in acq and acq['contacts_block']:
            # Use existing block if available (from existing entries)
            report += f"{acq['contacts_block']}\n"
        elif 'contacts' in acq and acq['contacts']:
            for contact in acq['contacts']:
                if 'raw_block' in contact:
                    clean_block = contact['raw_block'].replace('**', '').replace('##', '')
                    report += f"{clean_block}\n\n"
                else:
                    name = contact.get('name', 'Media Contact')
                    email = contact.get('email', '')
                    phone = contact.get('phone', '')
                    report += f"{name}\n"
                    if email:
                        report += f"{email}\n"
                    if phone:
                        report += f"Tel: {phone}\n"
                    report += "\n"
        else:
            report += "None found\n"
            
        report += "\n---\n\n"
        
    return report

def main():
    log("Starting M&A Press Release Monitor (Robust Version)")
    
    today = get_today_date()
    report_filename = f"{today}.md"
    report_path = os.path.join(GITHUB_REPO_PATH, report_filename)
    
    # 1. Load existing entries
    existing_entries = get_existing_entries_from_report(report_path)
    existing_urls = set(normalize_url(e['url']) for e in existing_entries)
    
    # 2. Fetch new releases
    rss_releases = fetch_from_rss_feed()
    
    # 3. Filter for new and relevant releases
    new_releases = []
    for release in rss_releases:
        # Filter logic
        title_lower = release['title'].lower()
        summary_lower = release['summary'].lower()
        
        is_relevant = (
            ('acqui' in title_lower or 'merger' in title_lower or 'invest' in title_lower or 'sale' in title_lower) and
            ('dividend' not in title_lower and 'earnings' not in title_lower)
        )
        
        if not is_relevant:
            log(f"Skipping non-relevant: {release['title'][:30]}...")
            continue
            
        norm_url = normalize_url(release['url'])
        if norm_url in existing_urls:
            log(f"Skipping existing: {release['title'][:30]}...")
            continue
            
        new_releases.append(release)
        
    log(f"Found {len(new_releases)} NEW relevant releases to process")
    
    if not new_releases:
        log("No new releases to process. Exiting.")
        return

    # 4. Process new releases
    driver = setup_driver()
    processed_new_entries = []
    
    try:
        for i, release in enumerate(new_releases):
            # Add random delay to avoid blocking
            delay = random.uniform(10, 25)
            log(f"Waiting {delay:.1f}s before processing...")
            time.sleep(delay)
            
            result = extract_contact_info(release, driver)
            
            if result:
                processed_new_entries.append(result)
            else:
                # If failed (e.g. blocked), save as is with empty contacts
                # so we don't lose the entry and don't retry it forever
                log(f"Failed to extract contacts for {release['title']}, saving basic info")
                processed_new_entries.append({
                    'title': release['title'],
                    'url': release['url'],
                    'summary': release['summary'],
                    'contacts': [],
                    'success': False
                })
                
    finally:
        driver.quit()
        
    # 5. Combine and Save
    # Combine existing + new
    all_entries = existing_entries + processed_new_entries
    
    # Generate report
    report_content = generate_markdown_report(all_entries, today)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    log(f"Successfully updated report with {len(processed_new_entries)} new entries. Total: {len(all_entries)}")
    
    # 6. Trigger webhook
    report_filename = os.path.basename(report_path)
    trigger_webhook(today, len(all_entries), report_filename)

if __name__ == "__main__":
    main()
