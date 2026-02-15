# -*- coding: utf-8 -*-
import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


CLICK_DELAY = 0.7
RETRY_CLICK = 3
RETRY_STEP_ROUNDS = 3 
BACKTRACK_LIMIT = 12
POLL = 0.2
DELAY_BETWEEN_ROUNDS = 1.0  # пауза между повторами
WAIT_TREE_TIMEOUT = 8
FRAME_TRY_TIMEOUT = 6  # таймаут в iframe

# селекторы готовности дерева
TREE_READY_XPATHS = [
    "//app-tree",
    "//app-tree/div/ul/li[7]",
    "//section//main",
    "//main//ul",
    "//main//app-tree",
    "//ul/li[7]",
]

# шаг 1 — относительные пути, затем full path
FIRST_BUTTON_FALLBACK_XPATHS = [
    "//app-tree/div/ul/li[7]/div/div/a",
    "//app-tree//ul/li[7]//a",
    "//section//main//app-tree//ul/li[7]//a",
    "//section//main//app-tree/div/ul/li[7]/div/div/a",
    "//main//app-tree/div/ul/li[7]/div/div/a",
    "//app-tree/div/ul/li[7]/div/a",
    "//main//ul/li[7]//a",
    "/html/body/div[2]/section/div[2]/main/div/div/div[2]/div/div[2]/ul/li[7]/div/a",
    "/html/body/div[1]/section/div[2]/main/div[1]/app-tree/div/ul/li[7]/div/div/a",
    "/html/body/div[1]/section/div[2]/main/div/div/div[2]/div/div[2]/ul/li[7]/div/a",
]

# шаги 2..N — альтернативные xpath
BUTTON_XPATHS = [
    [
        "//app-tree/div/ul/li[7]/div/div[1]/a[1]",
        "//main//app-tree//ul/li[7]//div//a",
        "/html/body/div[1]/section/div[2]/main/div/div/div[2]/div/div[2]/ul/li[7]/div/a",
        "/html/body/div[1]/section/div[2]/main/div[1]/app-tree/div/ul/li[7]/div/div[1]/a[1]",
    ],
    # шаг 3
    [
        "//app-tree//ul/li[7]//app-tree//ul/li[4]//div[1]/a[1]",
        "//main//app-tree//ul/li[4]//div//a[1]",
        "/html/body/div[1]/section/div[2]/main/div[1]/app-tree/div/ul/li[7]/div/div[2]/app-tree/div/ul/li[4]/div/div[1]/a[1]",
    ],
    # шаг 4
    [
        "//app-tree//ul/li[7]//app-tree//ul/li[4]//app-tree//ul/li[2]//div/a",
        "//main//app-tree//ul/li[2]//div/a",
        "/html/body/div[1]/section/div[2]/main/div[1]/app-tree/div/ul/li[7]/div/div[2]/app-tree/div/ul/li[4]/div/div[2]/app-tree/div/ul/li[2]/div/div/a",
    ],
    # шаг 5
    [
        "//main//ul/li[3]/div/a",
        "//section//main//div//ul/li[3]/div/a",
        "/html/body/div[1]/section/div[2]/main/div[2]/div/div/div/ul/li[3]/div/a",
    ],
]


# контекст: None = default, иначе iframe
_nav_context_holder = [None]


def _wait(driver, timeout: float):
    return WebDriverWait(driver, timeout, poll_frequency=POLL)


def _switch_default(driver):
    try:
        driver.switch_to.default_content()
    except Exception:
        pass


def _switch_to_nav_context(driver):
    # переключить в контекст дерева (default или iframe)
    ctx = _nav_context_holder[0] if _nav_context_holder else None
    if ctx is not None:
        try:
            driver.switch_to.frame(ctx)
        except Exception:
            pass
    else:
        _switch_default(driver)


def _tree_found_in_current_context(driver, timeout: float = 2):
    for xpath in TREE_READY_XPATHS:
        try:
            _wait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
            return True
        except Exception:
            continue
    return False


def _find_nav_context(driver, stop_check):
    """
    Определяет, в default content или в iframe находится дерево
    Возвращает None (искать в default) или WebElement iframe
    """
    _switch_default(driver)
    deadline = time.time() + WAIT_TREE_TIMEOUT
    while time.time() < deadline:
        if stop_check and stop_check():
            return None
        if _tree_found_in_current_context(driver, timeout=2):
            return None
        time.sleep(POLL)
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        frames = []
    for i, frame_el in enumerate(frames):
        if stop_check and stop_check():
            return None
        try:
            _switch_default(driver)
            driver.switch_to.frame(frame_el)
            if _tree_found_in_current_context(driver, timeout=FRAME_TRY_TIMEOUT):
                return frame_el
        except Exception:
            pass
        _switch_default(driver)
    return None


def _get(driver, xpath: str, timeout: float):
    _switch_to_nav_context(driver)
    try:
        return _wait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
    except Exception:
        return None


def _click_el(driver, el, do_click) -> bool:
    try:
        return bool(do_click(driver, el))
    except Exception:
        return False


def _click_xpath(driver, xpath: str, do_click, stop_check, label: str) -> bool:
    for attempt in range(1, RETRY_CLICK + 1):
        if stop_check and stop_check():
            return False

        el = _get(driver, xpath, timeout=3)
        if not el:
            time.sleep(0.35)
            continue

        if _click_el(driver, el, do_click):
            time.sleep(CLICK_DELAY)
            return True
        time.sleep(0.35)

    return False


def _click_step_xpaths(driver, xpath_list, do_click, stop_check, label: str) -> bool:
    for i, xp in enumerate(xpath_list, start=1):
        if stop_check and stop_check():
            return False
        sub = f"{label} (вариант {i}/{len(xpath_list)})"
        if _click_xpath(driver, xp, do_click, stop_check, sub):
            return True
    return False


def _step1(driver, do_click, stop_check) -> bool:
    for round_idx in range(1, RETRY_CLICK + 1):
        if stop_check and stop_check():
            return False

        for i, xp in enumerate(FIRST_BUTTON_FALLBACK_XPATHS, start=1):
            label = f"шаг 1 (fallback {i}/{len(FIRST_BUTTON_FALLBACK_XPATHS)})"
            if _click_xpath(driver, xp, do_click, stop_check, label):
                return True
        time.sleep(0.6)

    return False


def run_navigation(driver, stop_check, do_click):
    original_implicit = None
    try:
        try:
            original_implicit = driver.timeouts.implicit_wait
        except Exception:
            original_implicit = None

        try:
            driver.implicitly_wait(0)
        except Exception:
            pass

        _nav_context_holder[0] = _find_nav_context(driver, stop_check)
        if stop_check and stop_check():
            return False

        if not _step1(driver, do_click, stop_check):
            logging.error("Навигация: шаг 1 не выполнен")
            return False

        idx = 0
        backtracks = 0

        while idx < len(BUTTON_XPATHS):
            if stop_check and stop_check():
                return False

            label = f"шаг {idx + 2}"
            xpath_list = BUTTON_XPATHS[idx]

            ok = False
            for round_num in range(1, RETRY_STEP_ROUNDS + 1):
                if stop_check and stop_check():
                    return False
                ok = _click_step_xpaths(driver, xpath_list, do_click, stop_check, label)
                if ok:
                    idx += 1
                    backtracks = 0
                    break
                if round_num < RETRY_STEP_ROUNDS:
                    time.sleep(DELAY_BETWEEN_ROUNDS)

            if ok:
                continue
            backtracks += 1
            if backtracks > BACKTRACK_LIMIT:
                logging.error("Навигация: слишком много откатов на %s — прекращаю", label)
                return False

            if idx > 0:
                idx -= 1
            else:
                if not _step1(driver, do_click, stop_check):
                    logging.error("Навигация: шаг 1 при откате не выполнен — прекращаю")
                    return False
                idx = 0

            time.sleep(0.8)
        return True

    except Exception:
        logging.exception("Навигация: ошибка")
        return False

    finally:
        try:
            if _nav_context_holder:
                _nav_context_holder[0] = None
        except Exception:
            pass
        try:
            if original_implicit is not None:
                driver.implicitly_wait(int(original_implicit))
            else:
                driver.implicitly_wait(5)
        except Exception:
            pass
