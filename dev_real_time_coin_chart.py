import sys
import time
import logging
import os
import psutil
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QLineEdit, QPushButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from seleniumbase import SB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

CHECK_INTERVAL_SEC = 2
REFRESH_THRESHOLD_SEC = 30
REFRESH_THRESHOLD_COUNT = REFRESH_THRESHOLD_SEC // CHECK_INTERVAL_SEC

class PriceFetcher(QThread):
    update_price = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = True

    def run(self):
        try:
            logging.info("[Fetcher] Starting WebDriver...")
            with SB(uc=True, headed=True, headless=True) as driver:
                driver.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                    "source": """
                        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                        window.chrome = { runtime: {} };
                        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    """
                })
                driver.open(self.url)
                time.sleep(5)

                UNCHANGED_COUNT = 0
                PREVIOUS_PRICE = None

                while self.running:
                    try:
                        raw_text = driver.get_text("//span[contains(@class,'priceWrapper')]")
                        logging.info(f"[Fetcher] Raw text: {raw_text}")
                        price = raw_text.strip().splitlines()[0]

                        self.update_price.emit(price)
                        self.print_memory()

                        if price == PREVIOUS_PRICE:
                            UNCHANGED_COUNT += 1
                        else:
                            UNCHANGED_COUNT = 0

                        PREVIOUS_PRICE = price

                        if UNCHANGED_COUNT >= REFRESH_THRESHOLD_COUNT:
                            logging.warning("[Fetcher] Price stuck. Refreshing page...")
                            driver.refresh()
                            time.sleep(5)
                            UNCHANGED_COUNT = 0

                    except Exception as e:
                        logging.error(f"[Fetcher] Error during fetch: {e}")
                        self.update_price.emit("Loading...")

                    time.sleep(CHECK_INTERVAL_SEC)

        except Exception as e:
            logging.error(f"[Fetcher] Thread crashed: {e}")
        finally:
            logging.info("[Fetcher] Exiting thread")

    def stop(self):
        logging.info("[Fetcher] Stopping thread...")
        self.running = False
        self.quit()
        self.wait()

    def print_memory(self):
        process = psutil.Process(os.getpid())
        mem_mb = process.memory_info().rss / 1024 ** 2
        logging.debug(f"[Memory] Using {mem_mb:.2f} MB")


class PriceWindow(QWidget):
    def __init__(self, url):
        super().__init__()
        self.setWindowTitle("🌟 Real-time SOL Tracker")
        self.setGeometry(300, 300, 400, 300)
        self.previous_price = None
        self.last_update_time = time.time()
        self.price_history = []

        # Price Label
        self.label = QLabel("Fetching value...", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("font-size: 28px; font-weight: bold; color: #333;")

        # Memory Label
        self.memory_label = QLabel("Memory: -- MB", self)
        self.memory_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.memory_label.setStyleSheet("font-size: 14px; color: #666;")

        # Chart
        self.plot_widget = pg.PlotWidget()
        self.plot_curve = self.plot_widget.plot(self.price_history, pen='b')
        self.plot_widget.setBackground('#f8f8f8')
        self.plot_widget.setYRange(0, 1000)
        self.plot_widget.setTitle("Price Trend")

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.addWidget(self.label)
        layout.addWidget(self.memory_label)
        layout.addWidget(self.plot_widget)
        self.setLayout(layout)
        self.setStyleSheet("background-color: #f8f8f8; border-radius: 10px;")

        self.url = url
        self.start_fetcher()

        self.watchdog = QTimer()
        self.watchdog.timeout.connect(self.check_timeout)
        self.watchdog.start(10000)

    def start_fetcher(self):
        logging.info("[UI] Launching fetcher thread")
        self.fetcher = PriceFetcher(self.url)
        self.fetcher.update_price.connect(self.update_label)
        self.fetcher.start()

    def restart_fetcher(self):
        self.fetcher.stop()
        self.start_fetcher()

    def check_timeout(self):
        if time.time() - self.last_update_time > 30:
            logging.warning("[Watchdog] No price update in 30s. Restarting thread.")
            self.restart_fetcher()

    def update_label(self, price_str):
        self.last_update_time = time.time()
        self.update_memory()
        try:
            current_price = float(price_str.replace(",", ""))
            if self.previous_price is not None:
                color = "green" if current_price > self.previous_price else "red" if current_price < self.previous_price else "#333"
            else:
                color = "#333"
            self.label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
            self.label.setText(f"Tracking Value: {price_str}")
            self.previous_price = current_price

            # Update chart
            self.price_history.append(current_price)
            if len(self.price_history) > 50:
                self.price_history.pop(0)
            self.plot_curve.setData(self.price_history)

        except Exception:
            self.label.setText("Tracking Value: ?")

    def update_memory(self):
        process = psutil.Process(os.getpid())
        mem_mb = process.memory_info().rss / 1024 ** 2
        self.memory_label.setText(f"Memory: {mem_mb:.2f} MB")

    def closeEvent(self, event):
        self.fetcher.stop()
        self.watchdog.stop()
        event.accept()


class UrlPrompt(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Enter Trading URL")
        self.setGeometry(300, 300, 400, 100)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Paste TradingView URL here...")
        self.button = QPushButton("Start", self)
        self.button.clicked.connect(self.launch_price_window)

        layout = QVBoxLayout()
        layout.addWidget(self.input)
        layout.addWidget(self.button)
        self.setLayout(layout)

    def launch_price_window(self):
        url = self.input.text()
        if url:
            self.hide()
            self.price_window = PriceWindow(url)
            self.price_window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    prompt = UrlPrompt()
    prompt.show()
    sys.exit(app.exec())
