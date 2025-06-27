import httpx
import asyncio
from bs4 import BeautifulSoup
import re
import time
import random
import logging
import PySimpleGUI as sg
import sys
import platform
import math

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('chinaz_rank')

# 用户代理列表，随机选择以避免被识别为爬虫
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
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


async def fetch_rank(domain, semaphore, max_retries=5, window=None):
    url = f"https://rank.chinaz.com/baidumobile/{domain}"
    attempt = 0
    last_error = ""

    while attempt < max_retries:
        async with semaphore:
            try:
                attempt += 1
                # 随机延时避免反爬 (3~6秒)
                delay = random.uniform(3, 6)
                logger.debug(f"{domain}: 尝试 {attempt}/{max_retries} - 等待 {delay:.2f}秒")
                if window:
                    window.write_event_value('UPDATE_STATUS',
                                             f'{domain}: 尝试 {attempt}/{max_retries} - 等待 {delay:.1f}秒...')
                await asyncio.sleep(delay)

                headers = get_random_headers()

                async with httpx.AsyncClient(
                        headers=headers,
                        timeout=30,
                        follow_redirects=True,
                        verify=False  # 忽略SSL验证，避免证书问题
                ) as client:
                    logger.info(f"{domain}: 开始请求 (尝试 {attempt}/{max_retries})")
                    if window:
                        window.write_event_value('UPDATE_STATUS',
                                                 f'{domain}: 查询中 (尝试 {attempt}/{max_retries})...')
                    response = await client.get(url)

                    # 检查响应状态
                    if response.status_code != 200:
                        logger.warning(f"{domain} 请求失败: HTTP {response.status_code}")
                        last_error = f"HTTP错误: {response.status_code}"
                        continue

                    # 检测反爬验证页面
                    if "验证-站长工具" in response.text:
                        logger.warning(f"{domain} 触发反爬验证")
                        last_error = "需手动验证"
                        continue

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
                                    logger.info(f"{domain}: 成功获取移动权重 {rank} (尝试 {attempt}/{max_retries})")
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
                                logger.info(f"{domain}: 成功获取移动权重 {rank} (尝试 {attempt}/{max_retries})")
                                return domain, rank, "成功"

                    # 方法3：从页面标题中提取
                    title_tag = soup.select_one('title')
                    if title_tag and "百度移动权重" in title_tag.text:
                        match = re.search(r'百度移动权重(\d+)', title_tag.text)
                        if match:
                            rank = match.group(1)
                            logger.info(f"{domain}: 成功获取移动权重 {rank} (尝试 {attempt}/{max_retries})")
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
                                logger.info(f"{domain}: 成功获取移动权重 {rank} (尝试 {attempt}/{max_retries})")
                                return domain, rank, "成功"

                    # 如果未找到权重元素，记录错误并重试
                    logger.warning(f"{domain} 未找到权重元素 (尝试 {attempt}/{max_retries})")
                    last_error = "未找到权重元素"

            except httpx.RequestError as e:
                logger.error(f"{domain} 网络错误: {str(e)}")
                last_error = f"网络错误: {str(e)}"
            except Exception as e:
                logger.exception(f"{domain} 解析异常")
                last_error = f"解析错误: {str(e)}"

    # 所有尝试都失败
    logger.error(f"{domain} 所有尝试失败")
    return domain, "失败", last_error


async def run_query(domains, window, max_retries=5):
    # 更严格的并发控制 (1个请求/秒)
    semaphore = asyncio.Semaphore(1)
    tasks = [fetch_rank(domain, semaphore, max_retries=max_retries, window=window)
             for domain in domains]
    results = await asyncio.gather(*tasks)

    # 保存结果到文件
    with open("domain_ranks.csv", "w", encoding="utf-8") as f:
        f.write("域名,移动权重,状态\n")
        for domain, rank, status in results:
            f.write(f"{domain},{rank},{status}\n")

    return results


def main_gui():
    # 兼容旧版PySimpleGUI的主题设置
    if hasattr(sg, 'theme'):
        sg.theme('LightBlue2')
    else:
        # 旧版使用ChangeLookAndFeel
        sg.ChangeLookAndFeel('LightBlue2')

    # 布局
    layout = [
        [sg.Text('域名移动权重查询工具', font=('Helvetica', 16), justification='center')],
        [sg.Text('输入域名 (每行一个):', font=('Helvetica', 12))],
        [sg.Multiline(size=(60, 10), key='-DOMAINS-', font=('Helvetica', 12))],
        [sg.Text('最大重试次数:'),
         sg.Slider(range=(1, 10), default_value=5, orientation='h', size=(20, 15), key='-RETRIES-')],
        [sg.Button('开始查询', size=(15, 1), font=('Helvetica', 12), button_color=('white', '#4CAF50')),
         sg.Button('退出', size=(15, 1), font=('Helvetica', 12), button_color=('white', '#F44336'))],
        [sg.Text('', size=(60, 1), key='-STATUS-', font=('Helvetica', 11), text_color='blue')],
        [sg.ProgressBar(100, orientation='h', size=(60, 20), key='-PROGRESS-', visible=False)],
        [sg.Text('查询结果:', font=('Helvetica', 12))],
        [sg.Table(values=[],
                  headings=['域名', '移动权重', '状态'],
                  max_col_width=25,
                  auto_size_columns=False,
                  display_row_numbers=False,
                  justification='left',
                  num_rows=15,
                  key='-RESULTS-',
                  col_widths=[25, 10, 15],
                  font=('Helvetica', 11),
                  alternating_row_color='#F0F0F0')],
        [sg.Text('结果已保存到: domain_ranks.csv', key='-SAVED-', visible=False, font=('Helvetica', 10))]
    ]

    # 创建窗口
    window = sg.Window('站长之家移动权重查询工具', layout, finalize=True, element_justification='c')

    # 事件循环
    while True:
        event, values = window.read()

        if event in (sg.WIN_CLOSED, '退出'):
            break

        if event == '开始查询':
            # 获取域名列表
            domain_input = values['-DOMAINS-'].strip()
            if not domain_input:
                sg.popup_error('请输入至少一个域名!')
                continue

            domains = [d.strip() for d in domain_input.split('\n') if d.strip()]
            max_retries = int(values['-RETRIES-'])

            # 更新UI状态
            window['-STATUS-'].update(f'开始查询 {len(domains)} 个域名的移动权重 (最大重试次数: {max_retries})...')
            window['-PROGRESS-'].update(0, visible=True)
            window['开始查询'].update(disabled=True)
            window['-RESULTS-'].update(values=[])
            window['-SAVED-'].update(visible=False)
            window.refresh()

            # 运行查询
            try:
                # 创建新事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # 运行异步查询
                start_time = time.time()
                results = loop.run_until_complete(run_query(domains, window, max_retries))

                # 显示结果
                table_data = []
                success_count = 0
                for i, (domain, rank, status) in enumerate(results):
                    # 更新进度
                    progress = int((i + 1) / len(domains) * 100)
                    window['-PROGRESS-'].update(progress)

                    # 确定状态和颜色
                    if rank.isdigit():
                        status_str = "✅ 成功"
                        success_count += 1
                    elif rank == "失败":
                        status_str = f"❌ {status}"
                    else:
                        status_str = f"⚠️ {rank} ({status})"

                    table_data.append([domain, rank, status_str])

                    # 更新状态
                    window['-STATUS-'].update(f'已处理 {i + 1}/{len(domains)} 个域名...')
                    window.refresh()

                # 更新结果表格
                window['-RESULTS-'].update(values=table_data)

                # 完成状态
                elapsed = time.time() - start_time
                window['-STATUS-'].update(f'查询完成! 成功 {success_count}/{len(domains)} | 耗时: {elapsed:.1f}秒')
                window['-PROGRESS-'].update(visible=False)
                window['-SAVED-'].update(visible=True)

            except Exception as e:
                logger.exception("查询出错")
                sg.popup_error(f'查询过程中出错: {str(e)}')
            finally:
                window['开始查询'].update(disabled=False)
                if loop:
                    loop.close()

    window.close()


if __name__ == "__main__":
    # 检查操作系统
    if platform.system() == 'Darwin':
        # Mac特定设置
        import multiprocessing

        multiprocessing.freeze_support()

    main_gui()
