import re
import time
import random
import logging
import csv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("domain_rank.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('chinaz_rank')


def init_driver():
    """初始化Chrome浏览器驱动"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # 无头模式
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--window-size=1920,1080')

    # 设置用户代理
    user_agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ]
    chrome_options.add_argument(f'user-agent={random.choice(user_agents)}')

    # 减少自动化特征
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    try:
        # 自动检测ChromeDriver路径
        service = Service()
        driver = webdriver.Chrome(service=service, options=chrome_options)

        # 设置浏览器执行脚本
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        return driver
    except WebDriverException as e:
        logger.error(f"无法启动Chrome浏览器: {str(e)}")
        logger.info("请确保已安装Chrome浏览器和对应版本的ChromeDriver")
        logger.info("下载地址: https://sites.google.com/chromium.org/driver/")
        return None


def fetch_rank(driver, domain, max_retries=10):
    """使用Selenium查询域名的移动权重"""
    url = f"https://rank.chinaz.com/baidumobile/{domain}"
    attempt = 0
    last_error = ""

    while attempt < max_retries:
        attempt += 1
        try:
            # 随机延时避免反爬
            delay = random.uniform(1, 3)  # 缩短延迟时间
            logger.info(f"{domain}: 尝试 {attempt}/{max_retries} - 等待 {delay:.1f}秒...")
            time.sleep(delay)

            # 访问页面
            driver.get(url)
            logger.info(f"{domain}: 已访问页面")

            # 检测无数据情况
            if "暂无数据" in driver.page_source:
                logger.info(f"{domain}: 无数据")
                return "0", "无数据"

            # 等待权重元素加载 - 最多等待5秒
            try:
                # 尝试多种定位方式
                weight_element = None

                # 方式1: 通过移动端文本定位 - 最可靠的方法
                try:
                    mobile_element = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//i[contains(@class, '_chinaz-rank-ncbi') and text()='移动端']"))
                    )
                    # 查找同一ul下的权重图片
                    ul_element = mobile_element.find_element(By.XPATH,
                                                             "./ancestor::ul[contains(@class, '_chinaz-rank-ncb')]")
                    weight_element = ul_element.find_element(By.XPATH, ".//img[contains(@src, 'baidu')]")
                except (TimeoutException, NoSuchElementException) as e:
                    logger.debug(f"{domain}: 方法1定位失败: {str(e)}")

                # 方式2: 直接定位权重图片
                if not weight_element:
                    try:
                        weight_element = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located(
                                (By.XPATH, "//img[contains(@src, 'baidu') and contains(@src, '.png')]"))
                        )
                    except TimeoutException as e:
                        logger.debug(f"{domain}: 方法2定位失败: {str(e)}")

                if weight_element:
                    img_src = weight_element.get_attribute("src")
                    match = re.search(r'baidu(\d+)\.png', img_src)
                    if match:
                        rank = match.group(1)
                        logger.info(f"{domain}: 成功获取移动权重 {rank} (尝试 {attempt}/{max_retries})")
                        return rank, "成功"

                # 方式3: 检查权重为0的情况
                try:
                    zero_element = driver.find_element(By.XPATH, "//img[contains(@src, 'baidu0.png')]")
                    if zero_element:
                        logger.info(f"{domain}: 权重为0")
                        return "0", "权重为0"
                except NoSuchElementException:
                    pass

                # 所有方式都失败
                logger.warning(f"{domain}: 未找到权重元素 (尝试 {attempt}/{max_retries})")
                last_error = "未找到权重元素"

                # 尝试滚动页面触发内容加载
                if attempt == 1:
                    logger.debug(f"{domain}: 尝试滚动页面触发加载")
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
                    time.sleep(1)  # 等待可能的动态加载

            except Exception as e:
                logger.error(f"{domain}: 元素定位错误: {str(e)}")
                last_error = f"元素定位错误: {str(e)}"

        except Exception as e:
            logger.error(f"{domain}: 页面访问错误: {str(e)}")
            last_error = f"页面访问错误: {str(e)}"

    # 所有尝试都失败
    logger.error(f"{domain}: 所有尝试失败")
    return "失败", last_error


def main():
    # 域名列表
    domains = [
        "szjunchi.net", "baidu.com", "qq.com",
        "taobao.com", "jd.com", "weibo.com",
        "zhihu.com", "bilibili.com",
        "github.com", "microsoft.com", "apple.com",
        "amazon.com", "wikipedia.org", "python.org"
    ]

    # 初始化浏览器
    driver = init_driver()
    if not driver:
        logger.error("无法初始化浏览器，程序退出")
        return

    logger.info("=" * 70)
    logger.info(f"开始查询 {len(domains)} 个域名的移动权重")
    logger.info("=" * 70)

    # 结果列表
    results = []
    success_count = 0

    # 处理每个域名
    start_time = time.time()
    for i, domain in enumerate(domains):
        logger.info(f"处理域名 ({i + 1}/{len(domains)}): {domain}")
        rank, status = fetch_rank(driver, domain)

        # 记录结果
        if rank.isdigit():
            success_count += 1
            status_str = "✅ 成功"
        else:
            status_str = f"❌ {status}"

        results.append([domain, rank, status])
        logger.info(f"结果: {domain} - 权重: {rank} - 状态: {status_str}")

        # 显示进度
        elapsed = time.time() - start_time
        avg_time = elapsed / (i + 1)
        remaining = avg_time * (len(domains) - i - 1)
        logger.info(f"进度: {i + 1}/{len(domains)} | 用时: {elapsed:.1f}秒 | 预计剩余: {remaining:.1f}秒")

    # 关闭浏览器
    driver.quit()

    # 保存结果到CSV (使用utf-8-sig解决Excel乱码问题)
    csv_file = "domain_ranks.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['域名', '移动权重', '状态'])
        writer.writerows(results)

    logger.info("=" * 70)
    logger.info(f"查询完成! 成功 {success_count}/{len(domains)} | 失败 {len(domains) - success_count}")
    logger.info(f"总用时: {time.time() - start_time:.1f}秒")
    logger.info(f"结果已保存到: {csv_file}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
