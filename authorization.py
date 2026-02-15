# авторизация
import logging
import threading
import time

CERT_DIALOG_TITLE = "Выбор сертификата"


def _click_cert_ok_win32_api():
    # OK в нативном окне сертификата
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
    # поиск диалога сертификата (pywinauto)
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
    # клик OK в окне
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
    # Enter в окно
    try:
        win.set_focus()
        time.sleep(0.15)
        win.type_keys("{ENTER}")
        return True
    except Exception:
        return False


def click_native_ok(timeout=15, window_title_substrings=None):
    # OK в нативном диалоге сертификата
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


def wait_page_ready(driver, timeout=30, stop_check=None):
    def document_ready(d):
        try:
            return d.execute_script("return document.readyState") == "complete"
        except Exception:
            return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if stop_check and stop_check():
            return
        try:
            if document_ready(driver):
                time.sleep(0.2)
                return
        except Exception:
            pass
        time.sleep(0.3)


def run_authorization(driver, base_url, stop_check):
    cert_done = threading.Event()

    def cert_clicker():
        for _ in range(60):
            if cert_done.is_set() or (stop_check and stop_check()):
                return
            if click_native_ok(timeout=2):
                break
            time.sleep(0.5)

    click_thread = threading.Thread(target=cert_clicker, daemon=True)
    click_thread.start()
    time.sleep(0.5)

    if not (base_url and base_url.strip()):
        logging.error("BASE_URL пустой, страница не открыта")
        cert_done.set()
        return

    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    try:
        driver.get(base_url)
    except Exception:
        logging.exception("Ошибка при загрузке страницы")
    cert_done.set()
    click_thread.join(timeout=2)
    time.sleep(0.5)
    wait_page_ready(driver, timeout=10, stop_check=stop_check)
    time.sleep(2)
