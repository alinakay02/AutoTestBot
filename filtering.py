# -*- coding: utf-8 -*-
"""
Модуль фильтрации таблицы.
1. Очищает все применённые фильтры
2. Устанавливает "Статус документа" = согласовано получателем
3. Устанавливает "Период по" = 31.12.2025
"""
import time
import logging
from dataclasses import dataclass
from typing import Callable, Optional, List, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, WebDriverException


logger = logging.getLogger(__name__)

# Контейнер применённых фильтров (applyingFiltersZonePane)
# Дочерние div — отдельные фильтры; кнопка очистки внутри каждого
X_APPLYING_FILTERS_CONTAINER = (
    "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[1]/div[1]/div/div/div[1]/div"
)
# Альтернатива по классу контейнера
X_APPLYING_FILTERS_BY_CLASS = "//div[contains(@class,'applyingFiltersZonePane')]"

REL_CLEAR_BTN_IN_FILTER = ".//button[contains(@class,'filter-plank-cancel-button')]"

# Кнопка раскрытия фильтра "Статус документа" (th[4])
X_STATUS_EXPAND_BTN = (
    "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[2]/div/div/table/tbody/tr/td/"
    "table/tbody/tr/td/div[1]/div[1]/div/div/div/div[1]/div/div/div/div[1]/table/tbody/tr[2]/th[4]/div/"
    "table/tbody/tr/td/table/tbody/tr/td/span/a/i"
)
# Родительский <a> — иногда клик по <i> не срабатывает
X_STATUS_EXPAND_ANCHOR = (
    "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[2]/div/div/table/tbody/tr/td/"
    "table/tbody/tr/td/div[1]/div[1]/div/div/div/div[1]/div/div/div/div[1]/table/tbody/tr[2]/th[4]/div/"
    "table/tbody/tr/td/table/tbody/tr/td/span/a"
)
# Fallback: th с текстом "Статус документа" и кнопка внутри
X_STATUS_BY_TEXT = (
    "//th[contains(., 'Статус документа')]//div[.//a/i]//a | "
    "//th[contains(., 'Статус документа')]//a[.//i] | "
    "//th[contains(., 'Статус документа')]//span/a"
)

# Контейнер строк попапа "Статус документа" — нужная строка не всегда под одним номером, ищем по title
X_STATUS_POPUP_TBODY = (
    "/html/body/div[4]/div/table/tbody/tr/td/table/tbody/tr[3]/td/div/div/table/tbody[1]"
)
# Строка "согласовано получателем" — tr[13] (используется как первая проверка)
X_STATUS_POPUP_ROW = "/html/body/div[4]/div/table/tbody/tr/td/table/tbody/tr[3]/td/div/div/table/tbody[1]/tr[13]"
STATUS_TITLE_NEEDLE = "Согласовано получателем"

STATUS_TABLE_BASE_XPATHS = [
    "/html/body/div[4]//table//tbody/tr",
    "//div[contains(@class,'z-combobox-popup')]//table//tbody/tr",
    "//div[contains(@class,'z-listbox')]//table//tbody/tr",
    "//div[contains(@class,'z-window')]//table//tbody/tr",
]
STATUS_ROW_INDEX = 13

X_OK_BUTTON = "/html/body/div[4]/div/table/tbody/tr/td/table/tbody/tr[5]/td/table/tbody/tr/td/table/tbody/tr/td/table/tbody/tr/td/table/tbody/tr/td/table/tbody/tr/td[1]/button"
X_OK_BUTTON_ALT = "//div[4]//button[normalize-space(.)='ОК' or normalize-space(.)='OK']"
X_OK_BUTTON_ALT2 = "//div[contains(@class,'z-window')]//button[normalize-space(.)='ОК' or normalize-space(.)='OK']"

# Поле ввода "Период по" (th[5])
X_PERIOD_TO_INPUT = (
    "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[2]/div/div/table/tbody/tr/td/"
    "table/tbody/tr/td/div[1]/div[1]/div/div/div/div[1]/div/div/div/div[1]/table/tbody/tr[2]/th[5]/div/"
    "table/tbody/tr/td/table/tbody/tr/td/span/input"
)
X_PERIOD_TO_BY_TEXT = "//th[contains(., 'Период по')]//input"

# Варианты XPath для поиска элементов (не переключаем контекст — работаем в текущем frame)
STATUS_EXPAND_XPATHS = [X_STATUS_EXPAND_BTN, X_STATUS_EXPAND_ANCHOR, X_STATUS_BY_TEXT]
PERIOD_INPUT_XPATHS = [X_PERIOD_TO_INPUT, X_PERIOD_TO_BY_TEXT]
FILTER_CONTAINER_XPATHS = [X_APPLYING_FILTERS_CONTAINER, X_APPLYING_FILTERS_BY_CLASS]


@dataclass
class WaitCfg:
    short: int = 5
    medium: int = 15
    poll: float = 0.2


def _wait(driver, timeout: int, poll: float):
    return WebDriverWait(driver, timeout, poll_frequency=poll)


def _safe_sleep(seconds: float, stop_check: Optional[Callable[[], bool]] = None):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if stop_check and stop_check():
            return
        time.sleep(0.1)


def _robust_click(driver, el) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.1)
    except Exception:
        pass
    try:
        el.click()
        return True
    except WebDriverException:
        pass
    try:
        driver.execute_script("arguments[0].click();", el)
        return True
    except WebDriverException:
        return False


def _find_any(driver, xpaths: List[str], timeout: int, poll: float, by=By.XPATH):
    """Ищет элемент по одному из XPath. Не переключает контекст (важно для iframe)."""
    for i, xpath in enumerate(xpaths):
        try:
            el = _wait(driver, timeout, poll).until(
                EC.presence_of_element_located((by, xpath))
            )
            logger.debug("filtering: элемент найден по xpath[%d], всего попыток: %d", i, len(xpaths))
            return el
        except TimeoutException:
            logger.debug("filtering: xpath[%d] не найден: %s", i, xpath[:60] + "..." if len(xpath) > 60 else xpath)
            continue
    return None


def _find_clickable_any(driver, xpaths: List[str], timeout: int, poll: float):
    """Ищет кликабельный элемент по одному из XPath."""
    for i, xpath in enumerate(xpaths):
        try:
            el = _wait(driver, timeout, poll).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            logger.debug("filtering: кликабельный элемент найден по xpath[%d]", i)
            return el
        except TimeoutException:
            continue
    return None


def _click_xpath_any(driver, xpaths: List[str], cfg: WaitCfg, stop_check=None, attempts: int = 3) -> bool:
    for attempt in range(attempts):
        if stop_check and stop_check():
            return False
        el = _find_clickable_any(driver, xpaths, cfg.short, cfg.poll)
        if el and _robust_click(driver, el):
            _safe_sleep(0.35, stop_check)
            return True
        _safe_sleep(0.25, stop_check)
    return False


def clear_all_filters(driver, cfg: WaitCfg = WaitCfg(), stop_check=None) -> bool:
    """Очищает все фильтры из зоны применённых фильтров (applyingFiltersZonePane)."""
    logger.info("filtering: очистка фильтров")
    container = None
    for xpath in FILTER_CONTAINER_XPATHS:
        try:
            container = _wait(driver, cfg.short, cfg.poll).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            logger.debug("filtering: контейнер фильтров найден")
            break
        except TimeoutException:
            continue
    if container is None:
        logger.info("filtering: контейнер фильтров не найден — считаем, фильтров нет")
        return True

    for round_num in range(1, 30):
        if stop_check and stop_check():
            return False

        try:
            container = _find_any(driver, FILTER_CONTAINER_XPATHS, cfg.short, cfg.poll)
            if container is None:
                return True
            children = container.find_elements(By.XPATH, "./div")
        except StaleElementReferenceException:
            logger.debug("filtering: stale при чтении дочерних div, повтор")
            _safe_sleep(0.2, stop_check)
            continue
        except Exception as e:
            logger.warning("filtering: ошибка при получении дочерних div: %s", e)
            return True

        if not children:
            logger.info("filtering: все фильтры очищены (контейнер пуст)")
            return True

        logger.debug("filtering: найдено фильтров: %d, round=%d", len(children), round_num)
        clicked = 0
        for ch in children:
            if stop_check and stop_check():
                return False
            try:
                btns = ch.find_elements(By.XPATH, REL_CLEAR_BTN_IN_FILTER)
                if not btns:
                    logger.debug("filtering: в блоке нет кнопки очистки")
                    continue
                if _robust_click(driver, btns[0]):
                    clicked += 1
                    logger.debug("filtering: клик по кнопке очистки, всего: %d", clicked)
                    _safe_sleep(1.0, stop_check)
            except Exception as e:
                logger.debug("filtering: ошибка клика по очистке: %s", e)
                continue

        if clicked == 0:
            if round_num <= 6:
                logger.debug("filtering: кнопки очистки не сработали, ждём и повторяем (round %d)", round_num)
                _safe_sleep(2.5, stop_check)
                continue
            logger.warning("filtering: ни одна кнопка очистки не сработала")
            return False

        _safe_sleep(1.2, stop_check)

    logger.warning("filtering: превышен лимит итераций очистки")
    return False


def _restore_table_context(driver, cfg: WaitCfg):
    """Возвращает контекст в frame с таблицей (если мы переключились на default для попапов)."""
    el = _find_any(driver, PERIOD_INPUT_XPATHS + FILTER_CONTAINER_XPATHS, 2, cfg.poll)
    if el is not None:
        return True
    try:
        driver.switch_to.default_content()
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for f in frames:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(f)
                el = _find_any(driver, PERIOD_INPUT_XPATHS + FILTER_CONTAINER_XPATHS, 2, cfg.poll)
                if el is not None:
                    logger.debug("filtering: контекст восстановлен (frame с таблицей)")
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _find_visible_popup_root(driver):
    """Ищет видимые ZK-попапы. Сначала текущий контекст, затем default_content."""
    roots = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'z-popup') or contains(@class,'z-window') or contains(@class,'z-combobox-popup') "
        "or contains(@class,'z-selectbox-popup') or contains(@class,'z-menupopup') or contains(@class,'z-menu-popup')]"
    )
    visible = [r for r in roots if _is_displayed(r)]
    if visible:
        return visible, False
    try:
        driver.switch_to.default_content()
        roots = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'z-popup') or contains(@class,'z-window') or contains(@class,'z-combobox-popup') "
            "or contains(@class,'z-selectbox-popup') or contains(@class,'z-menupopup') or contains(@class,'z-menu-popup')]"
        )
        visible = [r for r in roots if _is_displayed(r)]
        logger.debug("filtering: попапы в default_content: %d", len(visible))
        return visible, True
    except Exception:
        return [], False


def _is_displayed(el) -> bool:
    try:
        return el.is_displayed()
    except Exception:
        return False


def _tr_has_status_title(tr_el, needle: str = STATUS_TITLE_NEEDLE) -> bool:
    """Проверяет, что у tr есть title с текстом 'Согласовано получателем'."""
    try:
        title = (tr_el.get_attribute("title") or "").strip()
        return needle in title
    except Exception:
        return False


def _click_status_row_direct(driver, cfg: WaitCfg, stop_check=None) -> bool:
    """
    Выбор строки «Согласовано получателем» в попапе статуса.
    Сначала проверяем, что строка по текущему адресу (tr[13]) имеет title «Согласовано получателем».
    Если нет — ищем среди всех tr в контейнере tbody строку с таким title и кликаем её.
    """
    if stop_check and stop_check():
        return False

    def _scroll_and_click(tr_el):
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", tr_el
            )
        except Exception:
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", tr_el)
            except Exception:
                pass
        _safe_sleep(0.5, stop_check)
        if _robust_click(driver, tr_el):
            _safe_sleep(0.35, stop_check)
            return True
        return False

    def _try_click_in_context():
        # 1) Найти tbody контейнера статуса (строка не всегда под одним номером)
        tbody = None
        try:
            tbody = _wait(driver, 3, cfg.poll).until(
                EC.presence_of_element_located((By.XPATH, X_STATUS_POPUP_TBODY))
            )
        except TimeoutException:
            pass
        if tbody is not None:
            rows = tbody.find_elements(By.XPATH, "./tr")
            if rows:
                # 2) Сначала проверить строку по индексу
                idx = min(STATUS_ROW_INDEX - 1, len(rows) - 1)
                tr = rows[idx]
                if _tr_has_status_title(tr):
                    if _scroll_and_click(tr):
                        logger.info(
                            "filtering: выбран пункт tr[%d] (title 'Согласовано получателем')",
                            idx + 1,
                        )
                        return True
                # 3) Иначе ищем любую tr с нужным title в контейнере
                for i, tr in enumerate(rows):
                    if stop_check and stop_check():
                        return False
                    try:
                        if _tr_has_status_title(tr) and _scroll_and_click(tr):
                            logger.info(
                                "filtering: выбран пункт tr[%d] по title 'Согласовано получателем'",
                                i + 1,
                            )
                            return True
                    except StaleElementReferenceException:
                        rows = tbody.find_elements(By.XPATH, "./tr")
                        if i < len(rows) and _tr_has_status_title(rows[i]):
                            if _scroll_and_click(rows[i]):
                                return True
                        continue
                    except Exception:
                        continue

        # Fallback: клик по фиксированному XPath / по индексу без проверки title
        for base_xpath in [X_STATUS_POPUP_ROW] + [
            f"{bp}[{STATUS_ROW_INDEX}]" for bp in STATUS_TABLE_BASE_XPATHS
        ]:
            if stop_check and stop_check():
                return False
            try:
                el = _wait(driver, 2, cfg.poll).until(
                    EC.presence_of_element_located((By.XPATH, base_xpath))
                )
                if _tr_has_status_title(el) and _scroll_and_click(el):
                    logger.info("filtering: выбран пункт по XPath (title совпал)")
                    return True
                # если по индексу нашли, но title не тот — уже искали по tbody выше
            except TimeoutException:
                continue

        for base_xpath in STATUS_TABLE_BASE_XPATHS:
            if stop_check and stop_check():
                return False
            try:
                _wait(driver, 2, cfg.poll).until(
                    lambda d, xp=base_xpath: len(d.find_elements(By.XPATH, xp)) > 0
                )
                rows = driver.find_elements(By.XPATH, base_xpath)
                # сначала по индексу, если title подходит
                if len(rows) >= STATUS_ROW_INDEX:
                    tr = rows[STATUS_ROW_INDEX - 1]
                    if _tr_has_status_title(tr) and _scroll_and_click(tr):
                        logger.info("filtering: выбран пункт tr[%d] (по индексу)", STATUS_ROW_INDEX)
                        return True
                # иначе перебор всех tr по title
                for i, tr in enumerate(rows):
                    if stop_check and stop_check():
                        return False
                    try:
                        if _tr_has_status_title(tr) and _scroll_and_click(tr):
                            logger.info("filtering: выбран пункт tr[%d] по title", i + 1)
                            return True
                    except (StaleElementReferenceException, Exception):
                        continue
            except (TimeoutException, Exception):
                continue
        return False

    if _try_click_in_context():
        return True
    try:
        driver.switch_to.default_content()
        if _try_click_in_context():
            return True
    except Exception:
        pass
    return False


def _click_text_in_filter_popup(driver, text: str, cfg: WaitCfg, stop_check=None) -> bool:
    """
    Кликает td/tr с текстом в popup. НЕ input/textarea — иначе ставится фокус вместо выбора.
    """
    logger.debug("filtering: ищем в попапе текст: %s", text)
    deadline = time.time() + cfg.medium
    needle = text.strip().lower()

    while time.time() < deadline:
        if stop_check and stop_check():
            return False

        roots, _ = _find_visible_popup_root(driver)
        candidates = []
        for root in roots:
            try:
                for it in root.find_elements(By.XPATH, ".//td | .//tr[.//td] | .//li"):
                    try:
                        if it.tag_name.lower() in ("input", "textarea"):
                            continue
                        if it.find_elements(By.XPATH, ".//input | .//textarea"):
                            continue
                        if not _is_displayed(it):
                            continue
                        t = (it.text or "").strip()
                        t_low = t.lower()
                        if not t or needle not in t_low or len(t) > 80:
                            continue
                        other = t_low.replace(needle, "").strip()
                        if other and len(other) > 15:
                            continue
                        candidates.append((len(t), it, t))
                    except Exception:
                        continue
            except Exception:
                continue
        candidates.sort(key=lambda x: x[0])
        for _, it, t in candidates:
            if _robust_click(driver, it):
                logger.info("filtering: выбран пункт '%s'", t[:60])
                _safe_sleep(0.35, stop_check)
                return True

        time.sleep(cfg.poll)

    return False


def _popup_filter_visible(driver) -> bool:
    """Проверяет, есть ли видимый popup фильтра (combobox/selectbox)."""
    roots, _ = _find_visible_popup_root(driver)
    for r in roots:
        try:
            c = (r.get_attribute("class") or "").lower()
            if "combobox" in c or "selectbox" in c or "z-listbox" in c:
                if _is_displayed(r):
                    return True
        except Exception:
            pass
    return False


def _click_ok_direct(driver, cfg: WaitCfg, stop_check=None) -> bool:
    """Нажимает ОК — сначала в текущем контексте, затем в default."""
    for xpath in (X_OK_BUTTON, X_OK_BUTTON_ALT, X_OK_BUTTON_ALT2):
        try:
            btn = _wait(driver, 2, cfg.poll).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            if _robust_click(driver, btn):
                logger.info("filtering: нажата кнопка ОК")
                _safe_sleep(0.35, stop_check)
                return True
        except TimeoutException:
            continue
    return False


def _click_ok_in_filter_popup(driver, cfg: WaitCfg, stop_check=None) -> bool:
    """Нажимает ОК в popup — ищет button с текстом 'ОК'/'OK'."""
    deadline = time.time() + min(3, cfg.short)
    while time.time() < deadline:
        if stop_check and stop_check():
            return False
        roots, _ = _find_visible_popup_root(driver)
        for root in roots:
            try:
                btns = root.find_elements(By.XPATH, ".//button")
                for b in btns:
                    try:
                        if not _is_displayed(b):
                            continue
                        t = (b.text or "").strip()
                        if t.upper() in ("ОК", "OK"):
                            if _robust_click(driver, b):
                                logger.info("filtering: нажата кнопка ОК")
                                _safe_sleep(0.35, stop_check)
                                return True
                    except Exception:
                        continue
            except Exception:
                continue
        time.sleep(cfg.poll)
    return False


def set_status_filter(driver, cfg: WaitCfg = WaitCfg(), stop_check=None) -> bool:
    """Устанавливает фильтр Статус документа = согласовано получателем."""
    logger.info("filtering: установка фильтра 'Статус документа' = согласовано получателем")

    if not _click_xpath_any(driver, STATUS_EXPAND_XPATHS, cfg, stop_check, attempts=5):
        logger.error("filtering: не удалось нажать раскрытие фильтра 'Статус документа'")
        return False
    logger.info("filtering: фильтр статуса раскрыт")

    _safe_sleep(0.6, stop_check)

    row_clicked = _click_status_row_direct(driver, cfg, stop_check)
    if not row_clicked:
        row_clicked = _click_text_in_filter_popup(driver, "согласовано получателем", cfg, stop_check)
    if not row_clicked:
        logger.error("filtering: не удалось выбрать значение 'Согласовано получателем'")
        return False

    _safe_sleep(0.4, stop_check)
    ok_clicked = _click_ok_direct(driver, cfg, stop_check)
    if not ok_clicked and _popup_filter_visible(driver):
        ok_clicked = _click_ok_in_filter_popup(driver, cfg, stop_check)
    if not ok_clicked:
        logger.debug("filtering: попап мог закрыться автоматически")

    _restore_table_context(driver, cfg)
    logger.info("filtering: фильтр 'Статус документа' установлен")
    return True


def set_period_to_filter(driver, date_str: str = "31.12.2025", cfg: WaitCfg = WaitCfg(), stop_check=None) -> bool:
    """Устанавливает фильтр Период по через ввод даты в поле."""
    logger.info("filtering: установка фильтра 'Период по' = %s", date_str)

    for attempt in range(3):
        if stop_check and stop_check():
            return False
        inp = _find_clickable_any(driver, PERIOD_INPUT_XPATHS, cfg.medium, cfg.poll)
        if inp is None:
            logger.debug("filtering: поле 'Период по' не найдено, попытка %d/3", attempt + 1)
            _safe_sleep(0.35, stop_check)
            continue
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
            _safe_sleep(0.2, stop_check)
            try:
                inp.click()
            except Exception:
                try:
                    driver.execute_script("arguments[0].focus();", inp)
                except Exception:
                    pass
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(Keys.DELETE)
            inp.send_keys(date_str)
            inp.send_keys(Keys.ENTER)
            _safe_sleep(0.5, stop_check)
            logger.info("filtering: в поле 'Период по' введено: %s", date_str)
            return True
        except Exception as e:
            logger.debug("filtering: ошибка ввода даты: %s", e)
            _safe_sleep(0.2, stop_check)

    logger.error("filtering: не удалось установить фильтр 'Период по'")
    return False


def _wait_table_ready(driver, cfg: WaitCfg, stop_check=None) -> bool:
    """Ждёт готовности таблицы/фильтров (контейнер или кнопка раскрытия статуса)."""
    for _ in range(int(cfg.medium / 0.5)):
        if stop_check and stop_check():
            return False
        el = _find_any(driver, FILTER_CONTAINER_XPATHS + STATUS_EXPAND_XPATHS, 2, cfg.poll)
        if el is not None:
            _safe_sleep(1.5, stop_check)
            return True
        _safe_sleep(0.5, stop_check)
    return False


def run_filtering(driver, cfg: WaitCfg = WaitCfg(), stop_check=None) -> bool:
    """
    1. Очищает все применённые фильтры
    2. Устанавливает "Статус документа" = согласовано получателем
    3. Устанавливает "Период по" = 31.12.2025
    Не переключает контекст драйвера — работает в текущем (в т.ч. iframe).
    """
    logger.info("filtering: запуск фильтрации")

    if not _wait_table_ready(driver, cfg, stop_check):
        logger.warning("filtering: таблица/фильтры не готовы, продолжаем попытки")
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

        ok = clear_all_filters(driver, cfg, stop_check)
        if not ok:
            logger.error("filtering: не удалось очистить фильтры")
            return False

        ok = set_status_filter(driver, cfg, stop_check)
        if not ok:
            logger.error("filtering: не удалось установить фильтр статуса документа")
            return False

        _restore_table_context(driver, cfg)

        ok = set_period_to_filter(driver, "31.12.2025", cfg, stop_check)
        if not ok:
            logger.error("filtering: не удалось установить фильтр 'Период по'")
            return False

        logger.info("filtering: фильтрация успешно завершена")
        return True

    finally:
        try:
            if original_implicit is not None:
                driver.implicitly_wait(int(original_implicit))
            else:
                driver.implicitly_wait(5)
        except Exception:
            pass


def apply_settings_hide_always(driver, cfg: WaitCfg = WaitCfg(), stop_check=None) -> bool:
    """Заглушка для совместимости."""
    return True
