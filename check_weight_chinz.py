import httpx
import asyncio
from bs4 import BeautifulSoup
import re
import time
import random
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('chinaz_rank')

# 用户代理列表，随机选择以避免被识别为爬虫
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
]


def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://rank.chinaz.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "DNT": "1",
    }


async def fetch_rank(domain, semaphore, retry=2):
    url = f"https://rank.chinaz.com/baidumobile/{domain}"

    for attempt in range(retry + 1):
        async with semaphore:
            try:
                # 随机延时避免反爬 (3~6秒)
                delay = random.uniform(3, 6)
                logger.debug(f"{domain}: 等待 {delay:.2f}秒")
                await asyncio.sleep(delay)

                headers = get_random_headers()

                async with httpx.AsyncClient(
                        headers=headers,
                        timeout=30,
                        follow_redirects=True,
                        verify=False  # 忽略SSL验证，避免证书问题
                ) as client:
                    logger.info(f"{domain}: 开始请求")
                    response = await client.get(url)

                    # 检查响应状态
                    if response.status_code != 200:
                        logger.warning(f"{domain} 请求失败: HTTP {response.status_code}")
                        if attempt < retry:
                            continue
                        return domain, "请求失败", response.status_code

                    # 检测反爬验证页面
                    if "验证-站长工具" in response.text:
                        logger.warning(f"{domain} 触发反爬验证")
                        if attempt < retry:
                            continue
                        return domain, "需手动验证", "验证页面"

                    # 检测无数据情况
                    if "暂无数据" in response.text:
                        logger.info(f"{domain}: 无数据")
                        return domain, "0", "无数据"

                    soup = BeautifulSoup(response.text, 'html.parser')

                    # 方法1：直接查找移动权重图片
                    mobile_weight_img = soup.find('img', src=re.compile(r'baidu\d+\.png'))
                    if mobile_weight_img:
                        # 检查是否在移动权重区域
                        parent_ul = mobile_weight_img.find_parent('ul', class_='_chinaz-rank-ncb')
                        if parent_ul:
                            # 检查是否是移动端权重
                            mobile_text = parent_ul.find('i', class_='_chinaz-rank-ncbi', string='移动端')
                            if mobile_text:
                                match = re.search(r'baidu(\d+)\.png', mobile_weight_img['src'])
                                if match:
                                    rank = match.group(1)
                                    logger.info(f"{domain}: 成功获取移动权重 {rank} (方法1)")
                                    return domain, rank, "成功"

                    # 方法2：从移动端标题区域提取
                    mobile_title = soup.find('i', class_='_chinaz-rank-ncbi', string='移动端')
                    if mobile_title:
                        # 查找最近的权重图片
                        mobile_img = mobile_title.find_next('img', src=re.compile(r'baidu\d+\.png'))
                        if mobile_img:
                            match = re.search(r'baidu(\d+)\.png', mobile_img['src'])
                            if match:
                                rank = match.group(1)
                                logger.info(f"{domain}: 成功获取移动权重 {rank} (方法2)")
                                return domain, rank, "成功"

                    # 方法3：从页面标题中提取
                    title_tag = soup.select_one('title')
                    if title_tag and "百度移动权重" in title_tag.text:
                        match = re.search(r'百度移动权重(\d+)', title_tag.text)
                        if match:
                            rank = match.group(1)
                            logger.info(f"{domain}: 成功获取移动权重 {rank} (方法3)")
                            return domain, rank, "成功"

                    # 方法4：从流量数据区域提取
                    flow_section = soup.find('div', class_='_chinaz-rank-title bor-t1s04')
                    if flow_section:
                        # 查找移动权重图片
                        mobile_img = flow_section.find_previous('img', src=re.compile(r'baidu\d+\.png'))
                        if mobile_img:
                            match = re.search(r'baidu(\d+)\.png', mobile_img['src'])
                            if match:
                                rank = match.group(1)
                                logger.info(f"{domain}: 成功获取移动权重 {rank} (方法4)")
                                return domain, rank, "成功"

                    logger.warning(f"{domain} 未找到权重元素")
                    return domain, "N/A", "未找到元素"

            except httpx.RequestError as e:
                logger.error(f"{domain} 网络错误: {str(e)}")
                if attempt < retry:
                    continue
                return domain, f"网络错误", str(e)
            except Exception as e:
                logger.exception(f"{domain} 解析异常")
                if attempt < retry:
                    continue
                return domain, f"解析错误", str(e)

    return domain, "重试失败", ""


async def main(domains):
    # 更严格的并发控制 (1个请求/秒)
    semaphore = asyncio.Semaphore(1)
    tasks = [fetch_rank(domain, semaphore, retry=3) for domain in domains]
    results = await asyncio.gather(*tasks)

    # 输出结果
    print("\n" + "=" * 70)
    print(f"{'域名':<25} | {'移动权重':<8} | 状态")
    print("-" * 70)

    success_count = 0
    for domain, rank, status in results:
        if rank.isdigit():
            success_count += 1
            status_str = "✅ 成功"
        else:
            status_str = f"❌ {status}"
        print(f"{domain:<25} | {rank:<8} | {status_str}")

    print("=" * 70)
    print(f"查询完成: 成功 {success_count}/{len(domains)} | 失败 {len(domains) - success_count}")
    return results


if __name__ == "__main__":
    # 配置域名列表
    domain_list = [
        "szjunchi.net", "baidu.com", "qq.com",
        "taobao.com", "jd.com", "weibo.com",
        "zhihu.com", "bilibili.com",
        "github.com", "microsoft.com", "apple.com",
        "amazon.com", "wikipedia.org", "python.org"
    ]

    logger.info(f"开始查询 {len(domain_list)} 个域名的移动权重...")
    start_time = time.time()

    results = asyncio.run(main(domain_list))

    # 保存结果到文件
    with open("domain_ranks.csv", "w", encoding="utf-8") as f:
        f.write("域名,移动权重,状态\n")
        for domain, rank, status in results:
            f.write(f"{domain},{rank},{status}\n")

    logger.info(f"查询完成! 耗时: {time.time() - start_time:.2f}秒")
    logger.info(f"结果已保存到 domain_ranks.csv")