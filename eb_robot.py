# -*- coding: utf-8 -*-
import atexit
import os
import signal
import subprocess
import sys
import threading
import time

# Остановка по Ctrl+X (нужен pynput: pip install pynput)
_stop_event = threading.Event()
_keyboard_listener = None

def _init_ctrl_x_stop():
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

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    import chromedriver_binary
except ImportError:
    chromedriver_binary = None
try:
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    ChromeDriverManager = None

DEFAULT_YANDEX_PATH = os.path.expandvars(
    r"%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe"
)
DEFAULT_USER_DATA_DIR = os.path.expandvars(
    r"%LOCALAPPDATA%\Yandex\YandexBrowser\User Data"
)
BASE_URL = "https://eb.cert.roskazna.ru/"
DEFAULT_TIMEOUT = 10


CHROMEDRIVER_VERSION = "142.0.7444.162"


def get_chrome_service():
    """Возвращает Service для ChromeDriver (chromedriver_binary или webdriver_manager)."""
    if chromedriver_binary is not None:
        driver_path = getattr(chromedriver_binary, "chromedriver_filename", None)
        if driver_path and os.path.isfile(driver_path):
            return Service(executable_path=driver_path)
    if ChromeDriverManager is None:
        return None
    path = ChromeDriverManager(driver_version=CHROMEDRIVER_VERSION).install()
    return Service(executable_path=path)


def create_yandex_driver(yandex_path=None, user_data_dir=None, headless=False):
    """Создаёт WebDriver для Яндекс.Браузера с указанным путём и профилем"""
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


CERT_DIALOG_TITLE = "Выбор сертификата"


def _click_cert_ok_win32_api():
    """Нажимает OK в нативном окне выбора сертификата через Win32 API"""
    try:
        import win32gui
        import win32con
        import win32api
    except ImportError:
        return False

    found_dialog = []

    def enum_callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return True
            t = title.lower()
            if "сертификат" in t and ("выбор" in t or "certificate" in t):
                found_dialog.append(hwnd)
                return False
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(enum_callback, None)
    except Exception:
        pass

    if not found_dialog:

        def enum_top(hwnd, _):
            try:
                title = (win32gui.GetWindowText(hwnd) or "").lower()
                if "yandex" not in title and "яндекс" not in title and "chrome" not in title:
                    return True
                def enum_child(child_hwnd, _):
                    try:
                        t = (win32gui.GetWindowText(child_hwnd) or "").strip().lower()
                        if "сертификат" in t and ("выбор" in t or "certificate" in t):
                            found_dialog.append(child_hwnd)
                            return False
                    except Exception:
                        pass
                    return True
                win32gui.EnumChildWindows(hwnd, enum_child, None)
                if found_dialog:
                    return False
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_top, None)
        except Exception:
            pass

    if not found_dialog:
        return False

    dlg_hwnd = found_dialog[0]
    ok_button_hwnd = [None]

    def enum_children(hwnd, _):
        try:
            if win32gui.GetClassName(hwnd).lower() != "button":
                return True
            text = (win32gui.GetWindowText(hwnd) or "").strip()
            if text in ("OK", "ОК"):
                ok_button_hwnd[0] = hwnd
                return False
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(dlg_hwnd, enum_children, None)
    except Exception:
        pass

    try:
        win32gui.SetForegroundWindow(dlg_hwnd)
        time.sleep(0.2)
        if ok_button_hwnd[0] is not None:
            win32api.PostMessage(ok_button_hwnd[0], 0x00F5, 0, 0)
            return True
        win32api.keybd_event(0x0D, 0, 0, 0)
        win32api.keybd_event(0x0D, 0, win32con.KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def _find_cert_dialog(backend="uia"):
    """Ищет окно диалога выбора сертификата через pywinauto (uia или win32)"""
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend=backend)
        for win in desktop.windows():
            try:
                title = (win.window_text() or "").strip()
                if CERT_DIALOG_TITLE in title or title == CERT_DIALOG_TITLE:
                    return win
            except Exception:
                continue
        for win in desktop.windows():
            try:
                wt = (win.window_text() or "")
                if "Yandex" not in wt and "Яндекс" not in wt and "Chrome" not in wt:
                    continue
                for child in win.descendants():
                    try:
                        title = (child.window_text() or "").strip()
                        if CERT_DIALOG_TITLE in title or title == CERT_DIALOG_TITLE:
                            return child
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass
    return None


def _try_click_ok_in_window(win, backend="uia"):
    """Нажимает кнопку OK/ОК в переданном окне через pywinauto"""
    for btn_title in ("OK", "ОК"):
        try:
            if backend == "uia":
                ok_btn = win.child_window(title=btn_title, control_type="Button")
            else:
                ok_btn = win.child_window(title=btn_title, class_name="Button")
            ok_btn.wait("ready", timeout=2)
            ok_btn.click()
            return True
        except Exception:
            continue
    return False


def _send_enter_to_window(win):
    """Отправляет Enter в окно (фокус + type_keys)"""
    try:
        win.set_focus()
        time.sleep(0.15)
        win.type_keys("{ENTER}")
        return True
    except Exception:
        return False


def click_native_ok(timeout=15, window_title_substrings=None):
    """В течение timeout нажимает OK в нативном диалоге выбора сертификата (Win32 + pywinauto)"""
    try:
        from pywinauto import Desktop
        from pywinauto.findwindows import ElementNotFoundError
    except ImportError:
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _click_cert_ok_win32_api():
            return True

        win = _find_cert_dialog(backend="uia")
        if win is not None:
            try:
                win.set_focus()
                time.sleep(0.2)
                if _try_click_ok_in_window(win, backend="uia"):
                    return True
                _send_enter_to_window(win)
                return True
            except Exception:
                try:
                    _send_enter_to_window(win)
                    return True
                except Exception:
                    pass

        win = _find_cert_dialog(backend="win32")
        if win is not None:
            try:
                win.set_focus()
                time.sleep(0.2)
                if _try_click_ok_in_window(win, backend="win32"):
                    return True
                _send_enter_to_window(win)
                return True
            except Exception:
                try:
                    _send_enter_to_window(win)
                    return True
                except Exception:
                    pass

        time.sleep(0.5)

    if window_title_substrings is None:
        window_title_substrings = [
            "сертификат", "certificate", "выбор", "выберите",
            "Выбор", "Certificate", "аутентификац"
        ]
    desktop = Desktop(backend="uia")
    try:
        for win in desktop.windows():
            try:
                title = (win.window_text() or "").strip()
                if not title or "Yandex" in title or "Яндекс" in title:
                    continue
                if any(s.lower() in title.lower() for s in window_title_substrings):
                    win.set_focus()
                    time.sleep(0.2)
                    if _try_click_ok_in_window(win, "uia"):
                        return True
                    _send_enter_to_window(win)
                    return True
            except Exception:
                continue
    except ElementNotFoundError:
        pass

    try:
        desktop = Desktop(backend="uia")
        w = desktop.window(focused=True)
        title = (w.window_text() or "").strip()
        if "сертификат" in title.lower() or "certificate" in title.lower():
            w.type_keys("{ENTER}")
            return True
    except Exception:
        pass

    for _ in range(3):
        try:
            desktop = Desktop(backend="uia")
            desktop.window(focused=True).type_keys("{ENTER}")
            time.sleep(0.25)
        except Exception:
            pass
    return False


def wait_page_ready(driver, timeout=30):
    def document_ready(d):
        try:
            return d.execute_script("return document.readyState") == "complete"
        except Exception:
            return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _stop_requested():
            return
        try:
            if document_ready(driver):
                time.sleep(0.2)
                return
        except Exception:
            pass
        time.sleep(0.3)


def _do_click(driver, element):
    """Кликает по элементу: scrollIntoView, затем click / ActionChains / JS click"""
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


BUTTON_XPATHS = [
    "/html/body/div[1]/section/div[2]/main/div/div/div[2]/div/div[2]/ul/li[7]/div/a",
    "/html/body/div[1]/section/div[2]/main/div[1]/app-tree/div/ul/li[7]/div/div[1]/a[1]",
    "/html/body/div[1]/section/div[2]/main/div[1]/app-tree/div/ul/li[7]/div/div[2]/app-tree/div/ul/li[4]/div/div[1]/a[1]",
    "/html/body/div[1]/section/div[2]/main/div[1]/app-tree/div/ul/li[7]/div/div[2]/app-tree/div/ul/li[4]/div/div[2]/app-tree/div/ul/li[2]/div/div/a",
    "/html/body/div[1]/section/div[2]/main/div[2]/div/div/div/ul/li[3]/div/a",
]


def _click_one_xpath(driver, xpath, timeout=5):
    """Один раз находит элемент по XPath и нажимает по нему"""
    try:
        wait = WebDriverWait(driver, timeout=timeout)
        el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        el = driver.find_element(By.XPATH, xpath)
        return _do_click(driver, el)
    except Exception:
        return False


def click_by_xpath(driver, xpath, max_retries=5, previous_xpaths=None):
    """Кликает по элементу по XPath; при retry сначала проходит previous_xpaths """
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    prev = previous_xpaths or []
    for attempt in range(max_retries):
        if _stop_requested():
            return False
        try:
            wait_page_ready(driver, timeout=4)
        except Exception:
            time.sleep(0.5)
            continue
        # При retry сначала проходим путь с предыдущего пункта
        if attempt > 0 and prev:
            for prev_xpath in prev:
                if _stop_requested():
                    return False
                time.sleep(0.4)
                _click_one_xpath(driver, prev_xpath, timeout=5)
                time.sleep(0.6)
        try:
            if _click_one_xpath(driver, xpath, timeout=5):
                return True
        except Exception:
            pass
        time.sleep(0.8)
    return False


_driver_ref = []


def _close_browser():
    """Закрывает драйвер, останавливает слушатель клавиш и при необходимости завершает процессы браузера"""
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
    _stop_event.clear()
    _init_ctrl_x_stop()

    yandex_path = os.environ.get("YANDEX_BROWSER", DEFAULT_YANDEX_PATH)
    user_data = os.environ.get("YANDEX_USER_DATA", DEFAULT_USER_DATA_DIR)
    headless = "--headless" in sys.argv

    close_yandex_processes()
    driver = create_yandex_driver(
        yandex_path=yandex_path,
        user_data_dir=user_data,
        headless=headless,
    )
    _driver_ref.append(driver)
    atexit.register(_close_browser)

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

    cert_done = threading.Event()

    def cert_clicker():
        for _ in range(60):
            if cert_done.is_set() or _stop_requested():
                return
            if click_native_ok(timeout=2):
                break
            time.sleep(0.5)

    try:
        click_thread = threading.Thread(target=cert_clicker, daemon=True)
        click_thread.start()
        time.sleep(0.5)
        try:
            driver.get(BASE_URL)
        except Exception as e:
            print(e)
        cert_done.set()
        click_thread.join(timeout=2)
        if _stop_requested():
            return
        time.sleep(0.2)
        
        if _stop_requested():
            return
        # пауза после авторизации
        wait_page_ready(driver, timeout=2)
        for i, xpath in enumerate(BUTTON_XPATHS):
            if _stop_requested():
                break
            # При retry внутри click_by_xpath путь начнётся с предыдущих пунктов
            previous_xpaths = BUTTON_XPATHS[:i] if i > 0 else None
            click_by_xpath(driver, xpath, max_retries=5, previous_xpaths=previous_xpaths)
            # Пауза после клика, чтобы дерево/меню успело открыться
            if i < len(BUTTON_XPATHS) - 1:
                time.sleep(2)
        if not _stop_requested():
            time.sleep(3)
    finally:
        _close_browser()


if __name__ == "__main__":
    main()
