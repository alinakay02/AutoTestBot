# -*- coding: utf-8 -*-
import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains

from authorization import run_authorization
from navigation import run_navigation
from table_export2 import process_table_and_export

try:
    import chromedriver_binary
except ImportError:
    chromedriver_binary = None
try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    ChromeDriverManager = None

_stop_event = threading.Event()
_keyboard_listener = None

DEFAULT_YANDEX_PATH = os.path.expandvars(
    r"%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe"
)
DEFAULT_USER_DATA_DIR = os.path.expandvars(
    r"%LOCALAPPDATA%\Yandex\YandexBrowser\User Data"
)
BASE_URL = os.environ.get("EB_BASE_URL", "").strip()
CHROMEDRIVER_VERSION = os.environ.get("CHROMEDRIVER_VERSION", "142.0.7444.162")


def _init_ctrl_x_stop():
    # остановка по Ctrl+X (pynput)
    global _keyboard_listener
    try:
        from pynput.keyboard import GlobalHotKeys
        def hotkey_activate():
            _stop_event.set()
        _keyboard_listener = GlobalHotKeys({'<ctrl>+x': hotkey_activate})
        _keyboard_listener.start()
        return True
    except ImportError:
        return False
    except Exception:
        return False


def _stop_requested():
    return _stop_event.is_set()


def _shutdown_keyboard_listener():
    global _keyboard_listener
    if _keyboard_listener is not None:
        try:
            _keyboard_listener.stop()
        except Exception:
            pass
        _keyboard_listener = None


def get_chrome_service():
    
    if chromedriver_binary is not None:
        driver_path = getattr(chromedriver_binary, "chromedriver_filename", None)
        if driver_path and os.path.isfile(driver_path):
            return Service(executable_path=driver_path)
    if ChromeDriverManager is None:
        return None
    path = ChromeDriverManager(driver_version=CHROMEDRIVER_VERSION).install()
    return Service(executable_path=path)


def create_yandex_driver(yandex_path=None, user_data_dir=None, headless=False, download_dir=None):
    # WebDriver для Яндекс.Браузера
    path = yandex_path or DEFAULT_YANDEX_PATH
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Яндекс.Браузер не найден: {path}\n"
            "Укажите путь в переменной YANDEX_BROWSER или в коде."
        )

    options = Options()
    options.binary_location = path
    if headless:
        options.add_argument("--headless=new")

    if download_dir:
        d = os.path.abspath(download_dir)
        os.makedirs(d, exist_ok=True)
        options.add_experimental_option(
            "prefs",
            {
                "download.default_directory": d,
                "download.prompt_for_download": False,
                "safebrowsing.enabled": True,
            },
        )

    use_profile = user_data_dir if user_data_dir is not None else os.environ.get("YANDEX_USER_DATA")
    if use_profile:
        ud = use_profile if os.path.isabs(use_profile) else os.path.expandvars(use_profile)
        if os.path.isdir(ud):
            options.add_argument(f"--user-data-dir={ud}")
            options.add_argument("--profile-directory=Default")
        else:
            pass

    service = get_chrome_service()
    if service is not None:
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    if download_dir:
        try:
            d = os.path.abspath(download_dir)
            driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": d,
            })
        except Exception:
            pass

    return driver


def close_yandex_processes():
    try:
        subprocess.run(
            ["taskkill", "/IM", "browser.exe", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        time.sleep(1.5)
    except Exception:
        pass


def _do_click(driver, element):
    # клик: scrollIntoView, click / ActionChains / JS
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.4)
    except Exception:
        pass
    try:
        element.click()
        return True
    except Exception:
        pass
    try:
        ActionChains(driver).move_to_element(element).click().perform()
        return True
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        pass
    return False


_driver_ref = []


def _close_browser():
    # закрыть драйвер и слушатель клавиш
    _shutdown_keyboard_listener()
    if _driver_ref:
        try:
            _driver_ref[0].quit()
        except Exception:
            pass
        _driver_ref.clear()
        
        time.sleep(0.5)
        close_yandex_processes()


def main():
    global _driver_ref
    _log_dir = os.path.dirname(os.path.abspath(__file__))
    _log_path = os.path.join(_log_dir, "eb_robot.log")
    logging.basicConfig(
        level=logging.INFO,
        filename=_log_path,
        encoding="utf-8",
        format="%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    _stop_event.clear()
    _init_ctrl_x_stop()

    if not BASE_URL:
        logging.error("EB_BASE_URL не задан. Задайте переменную окружения EB_BASE_URL")
        sys.exit(1)

    yandex_path = os.environ.get("YANDEX_BROWSER", DEFAULT_YANDEX_PATH)
    user_data = os.environ.get("YANDEX_USER_DATA", DEFAULT_USER_DATA_DIR)
    headless = "--headless" in sys.argv

    close_yandex_processes()
    driver = create_yandex_driver(
        yandex_path=yandex_path,
        user_data_dir=user_data,
        headless=headless,
        download_dir=None,
    )
    _driver_ref.append(driver)
    atexit.register(_close_browser)

    try:
        driver.maximize_window()
    except Exception:
        pass

    def _on_signal(signum, frame):
        _stop_event.set()
        _close_browser()
        sys.exit(0)
    try:
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
    except Exception:
        pass

    driver.implicitly_wait(5)
    driver.set_page_load_timeout(90)

    
    for _ in range(50):
        if driver.window_handles:
            break
        time.sleep(0.2)
    if not driver.window_handles:
        logging.error("Нет ни одной вкладки браузера, выход")
        sys.exit(1)

    # Открываем новую вкладку
    n_before = len(driver.window_handles)
    try:
        driver.execute_cdp_cmd("Target.createTarget", {"url": "about:blank"})
    except Exception:
        pass
    time.sleep(0.5)
    if len(driver.window_handles) > n_before:
        try:
            driver.switch_to.window(driver.window_handles[-1])
        except Exception:
            pass
    else:
        try:
            import win32gui
            import win32con
            import win32api
            found = []
            def _cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    t = (win32gui.GetWindowText(hwnd) or "").lower()
                    if "yandex" in t or "яндекс" in t:
                        found.append(hwnd)
                        return False
                return True
            win32gui.EnumWindows(_cb, None)
            if found:
                win32gui.SetForegroundWindow(found[0])
                time.sleep(0.15)
                win32api.keybd_event(0x11, 0, 0, 0)  # Ctrl
                win32api.keybd_event(0x54, 0, 0, 0)  # T
                win32api.keybd_event(0x54, 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(0x11, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.5)
                if len(driver.window_handles) > n_before:
                    driver.switch_to.window(driver.window_handles[-1])
        except Exception as e:
            logging.warning("Ctrl+T не сработал: %s", e)
        if len(driver.window_handles) == n_before:
            try:
                driver.switch_to.window(driver.window_handles[0])
                driver.get("about:blank")
                time.sleep(0.3)
                driver.execute_script("window.open('');")
                time.sleep(0.5)
                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
            except Exception as e:
                logging.warning("Открытие вкладки через JS: %s", e)

    try:
        run_authorization(driver, BASE_URL, _stop_requested)
        if _stop_requested():
            return
        nav_ok = run_navigation(driver, _stop_requested, _do_click)
        if not nav_ok:
            logging.error("Навигация завершилась с ошибкой, выход")
            sys.exit(1)
        if not _stop_requested():
            process_table_and_export(
                driver,
                download_dir=os.environ.get("BROWSER_DOWNLOADS_DIR"),
                stop_check=_stop_requested,
                do_click=_do_click,
            )
    except Exception as e:
        logging.exception("Ошибка при выполнении сценария")
        sys.exit(1)
    finally:
        _close_browser()


if __name__ == "__main__":
    main()
