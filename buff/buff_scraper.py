import json
import os
import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm

COOKIE_FILE = "buff_cookies.json"

def load_cookies(context):
    if not os.path.exists(COOKIE_FILE):
        print("⚠️ 未找到 Cookie，请先登录...")
        return False

    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        try:
            cookies = json.load(f)
            context.add_cookies(cookies)
            print("✅ 已加载本地 Cookie")
            return True
        except Exception as e:
            print("❌ Cookie 加载失败:", e)
            return False

def save_login_cookies(context):
    print("🔑 请登录后按任意键继续...")
    input()
    cookies = context.cookies()
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print("✅ Cookie 已保存")

def get_max_page(content):
    soup = BeautifulSoup(content, "html.parser")
    pages = soup.select("a.page-link[href]")
    max_page = 1
    for page in pages:
        href = page.get("href")
        if href and "page_num=" in href:
            try:
                num = int(href.split("page_num=")[-1])
                if num > max_page:
                    max_page = num
            except:
                pass
    print(f"📄 确认总页数：{max_page}")
    return 10

def parse_items(content):
    soup = BeautifulSoup(content, "html.parser")
    items = []
    for li in soup.select("ul.card_csgo > li"):
        try:
            name = li.select_one("h3 a").text.strip()

            price_tag = li.select_one("strong.f_Strong")
            price_text = price_tag.text.strip().replace("¥", "").replace(",", "")  # 去除￥和逗号

            # 用正则找价格数字，例如匹配 '19.24', '3.8' 等格式
            match = re.search(r"\d+(\.\d+)?", price_text)
            if match:
                price = float(match.group())
            else:
                raise ValueError(f"无法解析价格: '{price_text}'")

            amount_text = li.select_one("span.l_Right").text.strip()
            amount = int("".join(filter(str.isdigit, amount_text)))

            items.append({"名称": name, "最低价": price, "在售数量": amount})

        except Exception as e:
            print(f"⚠️ 解析错误：{e}")
    return items


def scrape_buff_items():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        if not load_cookies(context):
            page.goto("https://buff.163.com/market/csgo#tab=selling")
            save_login_cookies(context)
        else:
            page.goto("https://buff.163.com/market/csgo#tab=selling")
            page.wait_for_timeout(3000)

        content = page.content()
        max_pages = get_max_page(content)

        data = []

        for i in tqdm(range(1, max_pages + 1), desc="抓取中"):
            url = f"https://buff.163.com/market/csgo#tab=selling&page_num={i}"
            page.goto(url)
            page.wait_for_timeout(2000)
            content = page.content()
            items = parse_items(content)
            if items:
                data.extend(items)
            else:
                print(f"⚠️ 第 {i} 页没有抓到数据")

        browser.close()

        if data:
            df = pd.DataFrame(data)
            filename = f"buff_csgo_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            df.to_csv(filename, index=False, encoding="utf-8-sig")
            print(f"✅ 共抓取饰品数：{len(data)}，数据已保存为 {filename}")
        else:
            print("⚠️ 没有抓到任何饰品数据")

if __name__ == "__main__":
    scrape_buff_items()
