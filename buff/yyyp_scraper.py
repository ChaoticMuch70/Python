from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # 可见模式调试
    page = browser.new_page()

    # 启动拦截监听
    def handle_response(response):
        print('responseURL:',response.url)
        if "querySaleTemplate" in response.url and response.status == 200:
            try:
                data = response.json()
                print("✅ 捕获数据接口：", response.url)
                print(json.dumps(data, indent=2, ensure_ascii=False))
            except Exception as e:
                print("解析错误：", e)

    page.on("response", handle_response)

    # 访问目标页面
    page.goto("https://www.youpin898.com/market")

    print("请手动下拉网页加载数据...")
    page.wait_for_timeout(10000)  # 等待10秒加载数据

    # browser.close()
