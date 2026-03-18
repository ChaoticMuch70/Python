import csv
import logging
import queue
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
]


class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.log_queue.put(("log", msg))
        except Exception:
            self.handleError(record)


class MobileRankChecker:
    def __init__(
        self,
        app_dir: Path,
        log_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.app_dir = app_dir
        self.log_file = app_dir / "domain_rank.log"
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"chinaz_mobile_rank_gui_{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh = logging.FileHandler(self.log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        if self.log_callback is not None:
            class CallbackHandler(logging.Handler):
                def __init__(self, cb: Callable[[str], None]):
                    super().__init__()
                    self.cb = cb

                def emit(self, record: logging.LogRecord) -> None:
                    try:
                        self.cb(self.format(record))
                    except Exception:
                        self.handleError(record)

            ch = CallbackHandler(self.log_callback)
            ch.setFormatter(formatter)
            logger.addHandler(ch)

        return logger

    def init_driver(self, headless: bool = False) -> webdriver.Chrome | None:
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1600,1200")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--lang=zh-CN")
        options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        try:
            service = Service()
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            return driver
        except WebDriverException as exc:
            self.logger.error("Chrome 启动失败：%s", exc)
            self.logger.error("请确认已安装 Google Chrome，并允许 Selenium Manager 自动下载驱动。")
            return None

    @staticmethod
    def normalize_domains(raw_text: str) -> list[str]:
        domains: list[str] = []
        for line in raw_text.splitlines():
            domain = line.strip()
            if not domain or domain.startswith("#"):
                continue
            domain = re.sub(r"^https?://", "", domain, flags=re.I)
            domain = domain.split("/")[0].strip()
            if domain:
                domains.append(domain)
        return list(dict.fromkeys(domains))

    def wait_page_ready(self, driver: webdriver.Chrome, timeout: int = 15) -> None:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    def extract_mobile_rank(self, driver: webdriver.Chrome) -> str | None:
        js = r'''
        const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
        const rankRegex = /baidu(\d+)\.png/i;
        const badRegex = /loading\.gif/i;

        const elements = Array.from(document.querySelectorAll('*'));
        const scored = [];

        for (const el of elements) {
            const text = clean(el.textContent);
            if (!text || (!text.includes('移动端') && !text.includes('移动端预估流量'))) {
                continue;
            }

            let node = el;
            for (let depth = 0; depth < 5 && node; depth++, node = node.parentElement) {
                const html = node.innerHTML || '';
                if (badRegex.test(html) && !rankRegex.test(html)) {
                    continue;
                }
                const matches = [...html.matchAll(/baidu(\d+)\.png/ig)].map(x => x[1]);
                if (matches.length) {
                    scored.push({rank: matches[0], score: depth, text: text.slice(0, 100)});
                }
            }
        }

        scored.sort((a, b) => a.score - b.score);
        if (scored.length) {
            return scored[0].rank;
        }

        const html = document.documentElement.outerHTML || '';
        const idx = html.indexOf('移动端');
        if (idx !== -1) {
            const segment = html.slice(idx, idx + 20000);
            const m = segment.match(rankRegex);
            if (m) {
                return m[1];
            }
        }

        return null;
        '''
        try:
            return driver.execute_script(js)
        except Exception as exc:
            self.logger.debug("JS 提取移动端权重失败：%s", exc)
            return None

    def fetch_rank(self, driver: webdriver.Chrome, domain: str, max_retries: int = 4) -> tuple[str, str]:
        url = f"https://rank.chinaz.com/baidumobile/{domain}"
        last_error = "未知错误"

        for attempt in range(1, max_retries + 1):
            try:
                delay = random.uniform(1.5, 3.5)
                self.logger.info("%s: 第 %s/%s 次尝试，等待 %.1f 秒", domain, attempt, max_retries, delay)
                time.sleep(delay)
                driver.get(url)
                self.wait_page_ready(driver, timeout=15)

                body_text = driver.find_element(By.TAG_NAME, "body").text
                page_source = driver.page_source

                if "暂无数据" in body_text or "暂无数据" in page_source:
                    return "0", "无数据"

                time.sleep(1.2)
                rank = self.extract_mobile_rank(driver)
                if rank and rank.isdigit():
                    return rank, "成功"

                idx = page_source.find("移动端")
                if idx != -1:
                    nearby = page_source[idx: idx + 20000]
                    match = re.search(r"baidu(\d+)\.png", nearby, flags=re.I)
                    if match:
                        return match.group(1), "成功"

                last_error = "未能稳定定位到移动端权重图标"
                self.logger.warning("%s: %s", domain, last_error)
            except TimeoutException:
                last_error = "页面加载超时"
                self.logger.warning("%s: %s", domain, last_error)
            except Exception as exc:
                last_error = f"页面访问或解析异常: {exc}"
                self.logger.warning("%s: %s", domain, last_error)

        return "失败", last_error

    @staticmethod
    def save_results(results: list[list[str]], output_file: Path) -> None:
        with output_file.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["域名", "移动权重", "状态"])
            writer.writerows(results)

    def run(self, domains: list[str], output_file: Path, headless: bool = False) -> tuple[int, int, Path]:
        if not domains:
            raise ValueError("域名列表为空")

        driver = self.init_driver(headless=headless)
        if not driver:
            raise RuntimeError("无法初始化 Chrome 浏览器")

        results: list[list[str]] = []
        success_count = 0
        start_time = time.time()

        self.logger.info("=" * 70)
        self.logger.info("开始查询，共 %s 个域名", len(domains))
        self.logger.info("输出文件：%s", output_file)
        self.logger.info("浏览器模式：%s", "无头" if headless else "可见")
        self.logger.info("=" * 70)
        if self.status_callback:
            self.status_callback("正在启动查询...")

        try:
            for idx, domain in enumerate(domains, start=1):
                if self.status_callback:
                    self.status_callback(f"正在查询：{domain} ({idx}/{len(domains)})")
                self.logger.info("处理域名 (%s/%s): %s", idx, len(domains), domain)
                rank, status = self.fetch_rank(driver, domain)
                if rank.isdigit():
                    success_count += 1
                results.append([domain, rank, status])

                elapsed = time.time() - start_time
                avg = elapsed / idx
                remaining = avg * (len(domains) - idx)
                self.logger.info(
                    "结果：%s | 权重=%s | 状态=%s | 已用时=%.1fs | 预计剩余=%.1fs",
                    domain,
                    rank,
                    status,
                    elapsed,
                    remaining,
                )
                if self.progress_callback:
                    self.progress_callback(idx, len(domains), domain)
        finally:
            driver.quit()

        self.save_results(results, output_file)
        self.logger.info("=" * 70)
        self.logger.info("查询完成：成功 %s/%s", success_count, len(domains))
        self.logger.info("结果已保存到：%s", output_file)
        self.logger.info("日志文件：%s", self.log_file)
        self.logger.info("=" * 70)
        if self.status_callback:
            self.status_callback(f"完成：成功 {success_count}/{len(domains)}")
        return success_count, len(domains), output_file


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("站长之家移动权重批量查询")
        self.root.geometry("980x700")
        self.root.minsize(900, 620)

        self.app_dir = self.get_app_dir()
        self.log_queue: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self.status_var = tk.StringVar(value="就绪")
        self.output_var = tk.StringVar(value=str(self.app_dir / "domain_ranks.csv"))
        self.headless_var = tk.BooleanVar(value=False)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.summary_var = tk.StringVar(value="尚未开始")

        self._build_ui()
        self._load_default_domains()
        self.root.after(120, self._poll_queue)

    @staticmethod
    def get_app_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        input_box = ttk.LabelFrame(main, text="域名列表", padding=10)
        input_box.pack(fill="both", expand=False)

        tip = ttk.Label(
            input_box,
            text="每行一个域名，也可以直接粘贴完整网址。程序会自动清洗成域名。",
        )
        tip.pack(anchor="w", pady=(0, 8))

        btn_row = ttk.Frame(input_box)
        btn_row.pack(fill="x", pady=(0, 8))

        ttk.Button(btn_row, text="从文件载入", command=self.load_domains_file).pack(side="left")
        ttk.Button(btn_row, text="保存当前域名列表", command=self.save_domains_file).pack(side="left", padx=8)
        ttk.Button(btn_row, text="填入示例", command=self.fill_demo_domains).pack(side="left")
        ttk.Button(btn_row, text="清空", command=self.clear_domains).pack(side="left", padx=8)

        self.domain_text = scrolledtext.ScrolledText(input_box, height=12, font=("Consolas", 11))
        self.domain_text.pack(fill="both", expand=True)

        config_box = ttk.LabelFrame(main, text="运行设置", padding=10)
        config_box.pack(fill="x", pady=10)

        output_row = ttk.Frame(config_box)
        output_row.pack(fill="x", pady=(0, 8))
        ttk.Label(output_row, text="结果 CSV：", width=10).pack(side="left")
        ttk.Entry(output_row, textvariable=self.output_var).pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text="选择位置", command=self.choose_output_file).pack(side="left", padx=(8, 0))

        opt_row = ttk.Frame(config_box)
        opt_row.pack(fill="x")
        ttk.Checkbutton(opt_row, text="无头模式（更安静，但有时更容易被拦截）", variable=self.headless_var).pack(side="left")

        action_row = ttk.Frame(main)
        action_row.pack(fill="x", pady=(0, 10))
        self.start_btn = ttk.Button(action_row, text="开始查询", command=self.start_query)
        self.start_btn.pack(side="left")
        ttk.Button(action_row, text="打开结果目录", command=self.open_output_folder).pack(side="left", padx=8)
        ttk.Button(action_row, text="打开日志文件目录", command=self.open_log_folder).pack(side="left")

        progress_box = ttk.LabelFrame(main, text="进度", padding=10)
        progress_box.pack(fill="x")
        self.progress = ttk.Progressbar(progress_box, variable=self.progress_var, maximum=100)
        self.progress.pack(fill="x")
        ttk.Label(progress_box, textvariable=self.summary_var).pack(anchor="w", pady=(6, 0))
        ttk.Label(progress_box, textvariable=self.status_var).pack(anchor="w")

        log_box = ttk.LabelFrame(main, text="运行日志", padding=10)
        log_box.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = scrolledtext.ScrolledText(log_box, height=16, font=("Consolas", 10), state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "progress":
                    current, total, domain = item[1], item[2], item[3]
                    pct = 0 if total == 0 else current * 100 / total
                    self.progress_var.set(pct)
                    self.summary_var.set(f"已完成 {current}/{total} | 当前域名：{domain}")
                elif kind == "status":
                    self.status_var.set(item[1])
                elif kind == "done":
                    self.start_btn.configure(state="normal")
                    success, total, output_file = item[1], item[2], item[3]
                    self.progress_var.set(100)
                    self.summary_var.set(f"查询完成：成功 {success}/{total}")
                    self.status_var.set(f"结果已保存：{output_file}")
                    messagebox.showinfo("完成", f"查询完成\n成功 {success}/{total}\n\n结果文件：\n{output_file}")
                elif kind == "error":
                    self.start_btn.configure(state="normal")
                    self.status_var.set("运行失败")
                    messagebox.showerror("运行失败", item[1])
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._poll_queue)

    def _load_default_domains(self) -> None:
        default_file = self.app_dir / "domains.txt"
        if default_file.exists():
            try:
                content = default_file.read_text(encoding="utf-8")
                self.domain_text.delete("1.0", "end")
                self.domain_text.insert("1.0", content)
                return
            except Exception:
                pass
        self.fill_demo_domains()

    def fill_demo_domains(self) -> None:
        demo = "\n".join([
            "baidu.com",
            "qq.com",
            "bilibili.com",
        ])
        self.domain_text.delete("1.0", "end")
        self.domain_text.insert("1.0", demo)

    def clear_domains(self) -> None:
        self.domain_text.delete("1.0", "end")

    def load_domains_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择域名文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.domain_text.delete("1.0", "end")
            self.domain_text.insert("1.0", content)
            self.status_var.set(f"已载入：{path}")
        except Exception as exc:
            messagebox.showerror("读取失败", f"无法读取文件：\n{exc}")

    def save_domains_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存域名文件",
            defaultextension=".txt",
            initialfile="domains.txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(self.domain_text.get("1.0", "end").strip() + "\n", encoding="utf-8")
            self.status_var.set(f"已保存域名文件：{path}")
        except Exception as exc:
            messagebox.showerror("保存失败", f"无法保存文件：\n{exc}")

    def choose_output_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择 CSV 保存位置",
            defaultextension=".csv",
            initialfile="domain_ranks.csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if path:
            self.output_var.set(path)

    def open_output_folder(self) -> None:
        path = Path(self.output_var.get()).expanduser().resolve().parent
        self.open_folder(path)

    def open_log_folder(self) -> None:
        self.open_folder(self.app_dir)

    @staticmethod
    def open_folder(path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("打开失败", f"无法打开目录：\n{exc}")

    def start_query(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("正在运行", "当前已有任务正在执行，请稍候。")
            return

        raw_text = self.domain_text.get("1.0", "end")
        domains = MobileRankChecker.normalize_domains(raw_text)
        if not domains:
            messagebox.showwarning("域名为空", "请先输入域名，每行一个。")
            return

        output_file = Path(self.output_var.get()).expanduser()
        if not output_file.suffix.lower() == ".csv":
            output_file = output_file.with_suffix(".csv")
            self.output_var.set(str(output_file))

        self.progress_var.set(0)
        self.summary_var.set(f"准备开始，共 {len(domains)} 个域名")
        self.status_var.set("正在启动...")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.start_btn.configure(state="disabled")

        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(domains, output_file, self.headless_var.get()),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_worker(self, domains: list[str], output_file: Path, headless: bool) -> None:
        try:
            checker = MobileRankChecker(
                app_dir=self.app_dir,
                log_callback=lambda msg: self.log_queue.put(("log", msg)),
                progress_callback=lambda cur, total, domain: self.log_queue.put(("progress", cur, total, domain)),
                status_callback=lambda msg: self.log_queue.put(("status", msg)),
            )
            success, total, saved = checker.run(domains, output_file, headless=headless)
            self.log_queue.put(("done", success, total, str(saved)))
        except Exception as exc:
            self.log_queue.put(("error", str(exc)))


def main() -> None:
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
