#!/usr/bin/env python3
"""
M&A Press Release Monitoring Script with Smart Deduplication
Automatically pulls M&A press releases from Business Wire via Official RSS Feed,
extracts contact info using Selenium (headless Chrome) to bypass blocks,
generates enhanced reports, and commits to GitHub.

Runs twice daily at 8 AM and 1 PM Eastern Time
Only adds NEW acquisitions to avoid duplicates
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
# Official Business Wire RSS Feed for Mergers & Acquisitions
RSS_URL = "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFtRWA=="
GITHUB_REPO_PATH = "/home/ubuntu/acquisitions"
MAKE_WEBHOOK_URL = "https://hook.us2.make.com/e5racqynovtehtqosma6geutfi6ksy26"

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def log(message):
    """Print timestamped log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_today_date():
    """Get today's date in YYYY-MM-DD format"""
    return datetime.now().strftime("%Y-%m-%d")

def get_existing_urls_from_report(report_path):
    """
    Extract URLs of acquisitions already in the report
    Returns set of URLs
    """
    if not os.path.exists(report_path):
        return set()
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        urls = set(re.findall(r'https://www\.businesswire\.com/news/home/\d+/[^\s\)]+', content))
        # Also check for Google News redirect URLs just in case
        google_urls = set(re.findall(r'https://news\.google\.com/rss/articles/[^\s\)]+', content))
        urls.update(google_urls)
        
        log(f"Found {len(urls)} existing acquisitions in report")
        return urls
    
    except Exception as e:
        log(f"Error reading existing report: {e}")
        return set()

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
                'summary': description,
                'original_url': link
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
    
    # Try to use ChromeDriverManager, fallback to system chromedriver
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except:
        driver = webdriver.Chrome(options=chrome_options)
        
    return driver

def extract_contact_info_selenium(driver, url):
    """
    Extract contact information using Selenium
    """
    log(f"  Navigating to: {url}")
    
    try:
        driver.get(url)
        
        # Wait for body to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Wait for potential Business Wire content
        time.sleep(2)
        
        # Get page source
        content = driver.page_source
        
        # Check for access denied
        if "Access Denied" in content or "Please enable JS" in content:
            log("  Access Denied/Challenge via Selenium")
            return None
            
        return content
        
    except Exception as e:
        log(f"  Selenium error: {e}")
        return None

def extract_contact_info(pr_data, driver):
    """
    Extract contact information from a single press release
    """
    url = pr_data['url']
    log(f"  Extracting contacts from: {pr_data['title'][:30]}...")
    
    content = extract_contact_info_selenium(driver, url)
    
    if not content:
        log(f"  Failed to fetch content for {url}")
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': pr_data['summary'],
            'contacts': [],
            'success': True
        }
    
    try:
        soup = BeautifulSoup(content, 'html.parser')
        
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
        full_text = soup.get_text()
        
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', full_text)
        phones = re.findall(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', full_text)
        
        contact_section = soup.find('div', class_=re.compile(r'bw-release-contact|contacts'))
        
        if contact_section:
            contact_text = contact_section.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in contact_text.split('\n') if line.strip()]
            
            for i, line in enumerate(lines):
                email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', line)
                if email_match:
                    contact = {'email': email_match.group()}
                    if i > 0:
                        prev_line = lines[i-1]
                        if not re.search(r'@|http|www', prev_line) and len(prev_line) < 50:
                            contact['name'] = prev_line
                    phone_match = re.search(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', line)
                    if phone_match:
                        contact['phone'] = phone_match.group()
                    contacts.append(contact)
        
        if not contacts and emails:
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ['info@', 'press@', 'news@', 'contact@'])]
            if not valid_emails and emails:
                valid_emails = emails
            contacts = [{'email': email} for email in valid_emails[:3]]
            
        if not contacts:
            log(f"  No contacts found. Content length: {len(full_text)}")
        
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': summary,
            'contacts': contacts,
            'success': True
        }
        
    except Exception as e:
        log(f"  Error parsing content: {e}")
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': pr_data['summary'],
            'contacts': [],
            'success': True
        }

def is_private_company_acquisition(title, summary):
    """
    Determine if this is a private company acquisition
    """
    public_indicators = [
        'NYSE:', 'NASDAQ:', 'OTCQX:', 'TSX:', 'LSE:',
        'publicly traded', 'public company',
        'Euronext', 'ASX:'
    ]
    
    non_acquisition_indicators = [
        'opposition to', 'opposes', 'against', 'lawsuit', 'investigation', 'class action'
    ]
    
    combined_text = f"{title} {summary}".lower()
    
    for indicator in public_indicators:
        if indicator.lower() in combined_text:
            return False
    
    for indicator in non_acquisition_indicators:
        if indicator.lower() in combined_text:
            return False
    
    acquisition_keywords = ['acquires', 'acquisition', 'joins', 'partnership', 'acquired', 'launches', 'merger', 'invests', 'investment']
    has_acquisition = any(keyword in combined_text for keyword in acquisition_keywords)
    
    return has_acquisition

def generate_markdown_report(acquisitions, date_str):
    """
    Generate markdown report from acquisitions list
    """
    report = f"# M&A Acquisitions Report - {date_str}\n\n"
    report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += f"Total Acquisitions: {len(acquisitions)}\n\n"
    
    for acq in acquisitions:
        # Use old format: ## Title
        report += f"## {acq['title']}\n\n"
        
        # Add Date and URL fields expected by parser
        report += f"**Date:** {date_str}\n"
        report += f"**Link:** [{acq['title']}]({acq['url']})\n\n"
        
        report += f"**Summary:** {acq['summary']}\n\n"
        
        # Use old contact header and format
        if acq['contacts']:
            report += "**Contact Information:**\n"
            for contact in acq['contacts']:
                name = contact.get('name', 'Media Contact')
                email = contact.get('email', '')
                phone = contact.get('phone', '')
                
                # Format as block
                report += f"{name}\n"
                if email:
                    report += f"{email}\n"
                if phone:
                    report += f"Tel: {phone}\n"
                report += "\n"
        else:
            report += "**Contact Information:**\nNone found\n"
            
        report += "\n---\n\n"
        
    return report

def main():
    log("Starting M&A Press Release Monitor (Official RSS Feed Version)")
    
    today_date = get_today_date()
    report_filename = f"{today_date}.md"
    report_path = os.path.join(GITHUB_REPO_PATH, report_filename)
    
    # Ensure repo directory exists
    if not os.path.exists(GITHUB_REPO_PATH):
        os.makedirs(GITHUB_REPO_PATH)
        
    # Get existing URLs to avoid duplicates
    existing_urls = get_existing_urls_from_report(report_path)
    
    # Fetch from RSS
    all_releases = fetch_from_rss_feed()
    
    if not all_releases:
        log("No releases found. Exiting.")
        return
    
    # Filter for new and relevant acquisitions
    new_acquisitions = []
    driver = None
    
    try:
        driver = setup_driver()
        
        for release in all_releases:
            # Check if already processed
            if release['url'] in existing_urls:
                log(f"Skipping existing: {release['title'][:30]}...")
                continue
                
            # Check if relevant (private equity/acquisition)
            if is_private_company_acquisition(release['title'], release['summary']):
                # Extract details
                details = extract_contact_info(release, driver)
                new_acquisitions.append(details)
                
                # Be nice to the server
                time.sleep(2)
            else:
                log(f"Skipping non-relevant: {release['title'][:30]}...")
                
    except Exception as e:
        log(f"Error during processing: {e}")
    finally:
        if driver:
            driver.quit()
            
    if not new_acquisitions:
        log("No new relevant acquisitions found.")
        return
        
    log(f"Found {len(new_acquisitions)} new acquisitions. Updating report...")
    
    # Generate report content
    new_content = generate_markdown_report(new_acquisitions, today_date)
    
    # Append or create report
    if os.path.exists(report_path):
        with open(report_path, 'a', encoding='utf-8') as f:
            # Skip header for append
            lines = new_content.split('\n')
            f.write('\n'.join(lines[4:]))
    else:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
            
    log(f"Report updated: {report_path}")
    
    # Git operations would go here (handled by GitHub Actions usually, but can be added if running locally)
    # For now, we just save the file locally

if __name__ == "__main__":
    main()
