import os
import time
import shutil
import zipfile
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple, List

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
    WebDriverException,
)

# папка загрузок
DEFAULT_DOWNLOAD_DIR = os.path.abspath(os.path.join(os.getcwd(), "downloads"))

X_TH9_CONTEXT = "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[2]/div/div/table/tbody/tr/td/table/tbody/tr/td/div[1]/div[1]/div/div/div/div[1]/div/div/div/div[1]/table/tbody/tr[1]/th[9]"
X_CTX_MENU_LI1 = "/html/body/div[4]/ul/li[1]/a"
X_APPLY_COLUMNS_BTN = "/html/body/div[5]/div[2]/div/div[2]/div[1]/div/div/div[1]/button[1]"

X_FILTER_TOGGLE_IMG = "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[2]/div/div/table/tbody/tr/td/table/tbody/tr/td/div[1]/div[1]/div/div/div/div[1]/div/div/div/div[1]/table/tbody/tr[1]/th[1]/div/table/tbody/tr/td/table/tbody/tr/td/img"

X_BTN_PRINT_LIST = "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[1]/div[1]/div/div/div[2]/div/div[3]/div/table/tbody/tr/td/table/tbody/tr/td[1]/table/tbody/tr/td/table/tbody/tr/td[21]/table/tbody/tr/td/table/tbody/tr/td[3]/button"
X_CTX_MENU_LI3 = "/html/body/div[4]/ul/li[3]/a"
X_PRINT_TABLE_FIRST_ROW = "/html/body/div[5]/div[2]/div/div[2]/div/div/div/div[2]/div/div/div/div[2]/table/tbody[1]/tr[1]/td"
X_PRINT_OK_BTN = "/html/body/div[5]/div[2]/div/div[1]/div[1]/div/div/div[1]/button[1]"

X_GRITTER_TITLE_SPAN = "/html/body/div[4]/div/div[2]/div[1]/span"


X_SINGLE_CHECKBOX_SPAN = "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[2]/div/div/table/tbody/tr/td/table/tbody/tr/td/div[1]/div[1]/div/div/div/div[1]/div/div/div/div[2]/table/tbody[1]/tr[1]/td[1]/div/span"


X_BTN_EXPORT_TXT = "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[1]/div[1]/div/div/div[2]/div/div[3]/div/table/tbody/tr/td/table/tbody/tr/td[1]/table/tbody/tr/td/table/tbody/tr/td[9]/button"

# таблица колонок div[5], tr с z-listitem-selected
X_COLUMNS_TABLE = "/html/body/div[5]/div[2]/div/div[1]/div/div/div/div[2]/table"
# xpath строк таблицы
ROWS_TABLE_XPATHS = [
    X_COLUMNS_TABLE + "//tbody/tr",
    "/html/body/div[5]//table//tbody/tr",
    "/html/body/div[1]/div[1]/div[2]/div[3]/div[2]/div/div/div/div/div[2]/div[2]/div/div/table/tbody/tr/td/table/tbody/tr/td/div[1]/div[1]/div/div/div/div[1]/div/div/div/div[2]/table/tbody[1]/tr",
    "//div[contains(@class,'z-window')]//table//tbody/tr",
]
# фон выделенной строки
SELECTED_ROW_BG = "#90B6E4"
SELECTED_ROW_BG_RGB = "rgb(144, 182, 228)"


@dataclass
class WaitCfg:
    short: int = 5
    medium: int = 15
    long: int = 45
    poll: float = 0.2


def _now() -> float:
    return time.time()


def _safe_sleep(seconds: float, stop_check: Optional[Callable[[], bool]] = None):
    t0 = _now()
    while _now() - t0 < seconds:
        if stop_check and stop_check():
            return
        time.sleep(0.1)


def _make_outputs_dir(project_root: str, name: str) -> str:
    out_dir = os.path.join(project_root, name)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _unique_path(dst_dir: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dst_dir, filename)
    if not os.path.exists(candidate):
        return candidate
    i = 1
    while True:
        candidate = os.path.join(dst_dir, f"{base}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _list_files(dir_path: str) -> List[str]:
    try:
        return [os.path.join(dir_path, f) for f in os.listdir(dir_path)]
    except Exception:
        return []


def _is_partial_download(path: str) -> bool:
    low = path.lower()
    return low.endswith(".crdownload") or low.endswith(".tmp") or low.endswith(".part")


def _wait_for_new_download(
    download_dir: str,
    exts: Sequence[str],
    since_ts: float,
    timeout: int,
    stop_check: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    
    deadline = _now() + timeout
    exts_low = tuple(e.lower() for e in exts)

    last_candidate = None
    last_size = None
    stable_since = None

    while _now() < deadline:
        if stop_check and stop_check():
            return None

        files = _list_files(download_dir)
        
        candidates = []
        for p in files:
            try:
                if os.path.isdir(p):
                    continue
                if _is_partial_download(p):
                    continue
                if not p.lower().endswith(exts_low):
                    continue
                mtime = os.path.getmtime(p)
                if mtime >= since_ts - 0.2:
                    candidates.append(p)
            except Exception:
                continue

        if candidates:
            candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            cand = candidates[0]

            try:
                size = os.path.getsize(cand)
            except Exception:
                size = None

            if cand != last_candidate:
                last_candidate = cand
                last_size = size
                stable_since = _now()
            else:
                if size is not None and last_size is not None and size == last_size:
                    
                    if stable_since and (_now() - stable_since) >= 1.2:
                        return cand
                else:
                    last_size = size
                    stable_since = _now()

        time.sleep(0.25)

    return None


def _wait(driver, timeout: int, poll: float = 0.2):
    return WebDriverWait(driver, timeout, poll_frequency=poll)


def _find(driver, by, selector, timeout: int, poll: float = 0.2):
    return _wait(driver, timeout, poll).until(EC.presence_of_element_located((by, selector)))


def _find_visible(driver, by, selector, timeout: int, poll: float = 0.2):
    return _wait(driver, timeout, poll).until(EC.visibility_of_element_located((by, selector)))


def _exists(driver, by, selector, timeout: int, poll: float = 0.2) -> bool:
    try:
        _find(driver, by, selector, timeout, poll)
        return True
    except TimeoutException:
        return False


def _switch_default(driver):
    try:
        driver.switch_to.default_content()
    except Exception:
        pass


def _ensure_table_context(driver, wait_cfg: WaitCfg, stop_check=None) -> bool:
    try:
        _wait(driver, 3, wait_cfg.poll).until(
            EC.presence_of_element_located((By.XPATH, X_TH9_CONTEXT))
        )
        return True
    except TimeoutException:
        pass
    _switch_default(driver)
    try:
        _wait(driver, min(10, wait_cfg.medium), wait_cfg.poll).until(
            EC.presence_of_element_located((By.XPATH, X_TH9_CONTEXT))
        )
        return True
    except TimeoutException:
        pass
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        frames = []
    for i, frame_el in enumerate(frames):
        if stop_check and stop_check():
            return False
        try:
            _switch_default(driver)
            driver.switch_to.frame(frame_el)
            _wait(driver, 6, wait_cfg.poll).until(
                EC.presence_of_element_located((By.XPATH, X_TH9_CONTEXT))
            )
            return True
        except TimeoutException:
            pass
    _switch_default(driver)
    return False


def _scroll_into_view(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
    except Exception:
        pass


def _js_click(driver, el) -> bool:
    try:
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception:
        return False


def _robust_click(driver, el) -> bool:
    #Клик: scroll -> обычный click -> ActionChains -> JS click
    try:
        _scroll_into_view(driver, el)
        time.sleep(0.15)
    except Exception:
        pass

    try:
        el.click()
        return True
    except (ElementClickInterceptedException, ElementNotInteractableException, WebDriverException):
        pass

    try:
        ActionChains(driver).move_to_element(el).pause(0.05).click().perform()
        return True
    except WebDriverException:
        pass

    return _js_click(driver, el)


def _context_click(driver, el) -> bool:
    try:
        _scroll_into_view(driver, el)
        time.sleep(0.15)
    except Exception:
        pass
    try:
        ActionChains(driver).move_to_element(el).pause(0.05).context_click(el).perform()
        return True
    except WebDriverException:
        try:
            ActionChains(driver).move_to_element(el).pause(0.05).context_click().perform()
            return True
        except WebDriverException:
            return False


def _is_checkbox_checked(span_el) -> bool:
    try:
        cls = (span_el.get_attribute("class") or "").lower()
        if "checked" in cls or "selected" in cls:
            return True
    except Exception:
        pass

    try:
        icons = span_el.find_elements(By.CSS_SELECTOR, "i.z-icon-check")
        if icons:
            return True
    except Exception:
        pass

    return False


def _tr_is_selected(tr_el) -> bool:
    try:
        cls = (tr_el.get_attribute("class") or "").lower()
        return "z-listitem-selected" in cls
    except Exception:
        return False


def _element_has_selected_background(driver, el) -> bool:
    """Проверяет, что у элемента (или у родительского tr) фон выделения background: #90B6E4"""
    def _check_bg(e):
        try:
            bg = driver.execute_script(
                "var s = window.getComputedStyle(arguments[0]); return s.backgroundColor || '';",
                e,
            )
            if not bg:
                return False
            bg_low = bg.strip().lower().replace(" ", "")
            if "90b6e4" in bg_low or "144,182,228" in bg_low:
                return True
            if "rgb(144,182,228)" in bg_low:
                return True
            return False
        except Exception:
            return False

    if _check_bg(el):
        return True
    try:
        tag = el.tag_name.lower() if hasattr(el, "tag_name") else ""
        if tag == "td":
            tr = el.find_element(By.XPATH, "..")
            if tr and tr.tag_name.lower() == "tr":
                return _check_bg(tr)
    except Exception:
        pass
    return False


def _ensure_checkbox_checked(driver, span_el, wait_cfg: WaitCfg, stop_check=None) -> bool:
    #Ставит галку только если её нет. Возвращает True если после операции чекбокс checked
    try:
        if _is_checkbox_checked(span_el):
            return True
    except StaleElementReferenceException:
        return False

    ok = _robust_click(driver, span_el)
    if not ok:
        return False

    t0 = _now()
    while _now() - t0 < wait_cfg.short:
        if stop_check and stop_check():
            return False
        try:
            if _is_checkbox_checked(span_el):
                return True
        except StaleElementReferenceException:
            return True
        time.sleep(0.15)

    try:
        return _is_checkbox_checked(span_el)
    except Exception:
        return False


def _ensure_filters_on(driver, wait_cfg: WaitCfg, stop_check=None) -> bool:
    # клик только при filter_on
    try:
        img = _find(driver, By.XPATH, X_FILTER_TOGGLE_IMG, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return False

    def get_src():
        try:
            el = driver.find_element(By.XPATH, X_FILTER_TOGGLE_IMG)
            return (el.get_attribute("src") or "").strip().lower()
        except Exception:
            return ""

    src = get_src()
    # filter_off.png — не нажимать
    if "filter_off" in src or src.endswith("filter_off.png"):
        return True
    # filter_on.png — нажимаем
    if "filter_on" not in src and not src.endswith("filter_on.png"):
        return False

    _robust_click(driver, img)
    t0 = _now()
    while _now() - t0 < wait_cfg.medium:
        if stop_check and stop_check():
            return False
        src = get_src()
        if "filter_off" in src or src.endswith("filter_off.png"):
            return True
        time.sleep(0.2)

    src = get_src()
    return "filter_off" in src or src.endswith("filter_off.png")


def _catch_print_success_toast(driver, wait_cfg: WaitCfg) -> bool:
    deadline = _now() + 12
    poll = 0.08
    while _now() < deadline:
        try:
            title_el = driver.find_element(By.XPATH, X_GRITTER_TITLE_SPAN)
            title_txt = (title_el.text or "").strip()
            if 'Операция "Печать списка"' in title_txt or "Печать списка" in title_txt:
                container = title_el.find_element(By.XPATH, "./ancestor::div[contains(@class,'gritter-item')]")
                ps = container.find_elements(By.XPATH, ".//p")
                for p in ps:
                    txt = (p.text or "").strip()
                    if "Успешно завершена" in txt and "Диспетчере задач" in txt:
                        print("Печать списка успешно завершена")
                        return True
        except Exception:
            pass
        time.sleep(poll)
    return False


def _open_columns_menu_and_check_all(driver, wait_cfg: WaitCfg, stop_check=None) -> bool:
    """
      - ПКМ по th[9]
      - выбор меню li[1]/a
      - пройтись по всем чекбоксам в появившейся таблице и поставить галки только где нет
      - нажать Apply кнопку
    """
    try:
        th9 = _find(driver, By.XPATH, X_TH9_CONTEXT, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return False
    if not _context_click(driver, th9):
        return False

    _safe_sleep(0.25, stop_check)

    # выбрать пункт контекстного меню li[1]/a
    try:
        menu_item = _find_visible(driver, By.XPATH, X_CTX_MENU_LI1, wait_cfg.short, wait_cfg.poll)
    except TimeoutException:
        if stop_check and stop_check():
            return False
        _safe_sleep(0.5, stop_check)
        try:
            th9 = driver.find_element(By.XPATH, X_TH9_CONTEXT)
            _context_click(driver, th9)
            _safe_sleep(0.3, stop_check)
        except Exception:
            pass
        try:
            menu_item = _find_visible(driver, By.XPATH, X_CTX_MENU_LI1, wait_cfg.short, wait_cfg.poll)
        except TimeoutException:
            return False
    if not _robust_click(driver, menu_item):
        return False

    _safe_sleep(0.8, stop_check)
    rows_xpath = None
    for candidate in ROWS_TABLE_XPATHS:
        try:
            _wait(driver, 8, wait_cfg.poll).until(
                lambda d, xp=candidate: len(d.find_elements(By.XPATH, xp)) > 0
            )
            rows_xpath = candidate
            break
        except TimeoutException:
            continue
    if not rows_xpath:
        return False

    # Проходим по tr: выделенная строка имеет класс z-listitem-selected; кликаем только по невыделенным
    # Проверяем по свежему элементу по индексу, чтобы не снять выделение с уже выделенной строки (мигание последней строки).
    max_passes = 50
    for _ in range(max_passes):
        if stop_check and stop_check():
            return False
        rows = driver.find_elements(By.XPATH, rows_xpath)
        if not rows:
            break
        found_unselected = False
        for idx in range(1, len(rows) + 1):
            try:
                tr = driver.find_element(By.XPATH, rows_xpath + f"[{idx}]")
                if _tr_is_selected(tr):
                    continue
                found_unselected = True
                _robust_click(driver, tr)
                _safe_sleep(0.5, stop_check)
                break
            except (StaleElementReferenceException, Exception):
                break
        if not found_unselected:
            break

    try:
        apply_btn = _find_visible(driver, By.XPATH, X_APPLY_COLUMNS_BTN, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return False
    if not _robust_click(driver, apply_btn):
        return False

    _safe_sleep(0.6, stop_check)
    return True


def _print_list_and_download_excel(driver, wait_cfg: WaitCfg, download_dir: str, stop_check=None) -> Optional[str]:
    start_ts = _now()

    # кнопка "печать списка"
    try:
        btn = _find_visible(driver, By.XPATH, X_BTN_PRINT_LIST, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return None
    if not _robust_click(driver, btn):
        return None

    # контекстное меню li[3]/a
    try:
        mi = _find_visible(driver, By.XPATH, X_CTX_MENU_LI3, wait_cfg.short, wait_cfg.poll)
    except TimeoutException:
        _safe_sleep(0.3, stop_check)
        try:
            mi = _find_visible(driver, By.XPATH, X_CTX_MENU_LI3, wait_cfg.short, wait_cfg.poll)
        except TimeoutException:
            return None
    _robust_click(driver, mi)

    try:
        row = _find_visible(driver, By.XPATH, X_PRINT_TABLE_FIRST_ROW, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return None
    _robust_click(driver, row)
    _safe_sleep(0.35, stop_check)
    for attempt in range(1, 10):
        if stop_check and stop_check():
            return None
        try:
            row = driver.find_element(By.XPATH, X_PRINT_TABLE_FIRST_ROW)
        except Exception:
            return None
        if _element_has_selected_background(driver, row):
            break
        _robust_click(driver, row)
        _safe_sleep(0.35, stop_check)
    else:
        try:
            row = driver.find_element(By.XPATH, X_PRINT_TABLE_FIRST_ROW)
            _robust_click(driver, row)
            _safe_sleep(0.4, stop_check)
            if not _element_has_selected_background(driver, row):
                pass
        except Exception:
            pass

    try:
        ok = _find_visible(driver, By.XPATH, X_PRINT_OK_BTN, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return None
    _robust_click(driver, ok)

    toast_ok = _catch_print_success_toast(driver, wait_cfg)

    xlsx = _wait_for_new_download(
        download_dir=download_dir,
        exts=[".xlsx", ".xls"],
        since_ts=start_ts,
        timeout=wait_cfg.long,
        stop_check=stop_check,
    )
    return xlsx


def _is_row_selected_by_title_or_class(tr_el) -> bool:
    try:
        title = (tr_el.get_attribute("title") or "").strip()
        if "выделено: 1" in title.lower() or title.endswith(": 1"):
            return True
    except Exception:
        pass
    try:
        cls = (tr_el.get_attribute("class") or "").lower()
        return "z-listitem-selected" in cls
    except Exception:
        return False


def _ensure_row_selected_before_txt(driver, wait_cfg: WaitCfg, stop_check=None) -> bool:
    """
    Перед экспортом: убедиться, что строка с чекбоксом выделена
    Не выделена: нет класса z-listitem-selected
    Выделена: есть z-listitem-selected
    Если не выделена — клик по ячейке
    """
    try:
        span = _find(driver, By.XPATH, X_SINGLE_CHECKBOX_SPAN, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return False
    try:
        tr = span.find_element(By.XPATH, "ancestor::tr")
    except Exception:
        return False

    if _is_row_selected_by_title_or_class(tr):
        _safe_sleep(1.5, stop_check)
        return True

    _robust_click(driver, span)
    deadline = _now() + wait_cfg.short
    while _now() < deadline:
        if stop_check and stop_check():
            return False
        try:
            tr = driver.find_element(By.XPATH, X_SINGLE_CHECKBOX_SPAN).find_element(By.XPATH, "ancestor::tr")
            if _is_row_selected_by_title_or_class(tr):
                _safe_sleep(2.0, stop_check)
                return True
        except Exception:
            pass
        time.sleep(0.2)
    _safe_sleep(1.5, stop_check)
    return True


def _extract_zip_to_dir(zip_path: str, dest_dir: str) -> List[str]:
    """Извлекает zip в dest_dir. Возвращает список путей извлеченных файлов"""
    extracted = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                zf.extract(name, dest_dir)
                extracted.append(os.path.join(dest_dir, name))
        return extracted
    except Exception:
        return extracted


def _download_zip(driver, wait_cfg: WaitCfg, download_dir: str, stop_check=None) -> Optional[str]:
    """Клик по кнопке экспорта, ожидание скачивания ZIP"""
    start_ts = _now()
    try:
        btn = _find_visible(driver, By.XPATH, X_BTN_EXPORT_TXT, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return None
    if not _robust_click(driver, btn):
        return None

    zip_path = _wait_for_new_download(
        download_dir=download_dir,
        exts=[".zip"],
        since_ts=start_ts,
        timeout=wait_cfg.long,
        stop_check=stop_check,
    )
    return zip_path


def _ensure_single_checkbox_active(driver, wait_cfg: WaitCfg, stop_check=None) -> bool:
    # найти конкретный чекбокс span и включить, если выключен
    try:
        span = _find(driver, By.XPATH, X_SINGLE_CHECKBOX_SPAN, wait_cfg.medium, wait_cfg.poll)
    except TimeoutException:
        return False

    # если уже checked — пропуск
    try:
        if _is_checkbox_checked(span):
            return True
    except StaleElementReferenceException:
        pass

    if not _robust_click(driver, span):
        return False

    t0 = _now()
    while _now() - t0 < wait_cfg.short:
        if stop_check and stop_check():
            return False
        try:
            span2 = driver.find_element(By.XPATH, X_SINGLE_CHECKBOX_SPAN)
            if _is_checkbox_checked(span2):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _move_to_outputs(src_path: str, dst_dir: str) -> str:
    filename = os.path.basename(src_path)
    dst_path = _unique_path(dst_dir, filename)
    shutil.copy2(src_path, dst_path)
    return dst_path


def process_table_and_export(
    driver,
    download_dir: str = DEFAULT_DOWNLOAD_DIR,
    stop_check: Optional[Callable[[], bool]] = None,
    do_click: Optional[Callable] = None,
):
    
    wait_cfg = WaitCfg()

    os.makedirs(download_dir, exist_ok=True)

    try:
        original_implicit = driver.timeouts.implicit_wait
    except Exception:
        original_implicit = None

    try:
        try:
            driver.implicitly_wait(0)
        except Exception:
            pass

        project_root = os.path.dirname(os.path.abspath(__file__))
        excel_out_dir = _make_outputs_dir(project_root, "Excel outputs")
        txt_out_dir = _make_outputs_dir(project_root, "TXT Outputs")

        _ensure_table_context(driver, wait_cfg, stop_check)
        if stop_check and stop_check():
            return

        for attempt in range(1, 4):
            if stop_check and stop_check():
                return
            ok = _open_columns_menu_and_check_all(driver, wait_cfg, stop_check)
            if ok:
                break
            _safe_sleep(0.8, stop_check)
        else:
            raise RuntimeError("Шаги 1-3 не выполнены после 3 попыток")

        # -----------------
        # фильтры
        # -----------------
        for attempt in range(1, 4):
            if stop_check and stop_check():
                return
            ok = _ensure_filters_on(driver, wait_cfg, stop_check)
            if ok:
                break
            _safe_sleep(0.8, stop_check)
        else:
            raise RuntimeError("Фильтры не удалось привести в состояние ON")

        # -----------------
        # Excel
        # -----------------
        xlsx_path = None
        for attempt in range(1, 4):
            if stop_check and stop_check():
                return
            xlsx_path = _print_list_and_download_excel(driver, wait_cfg, download_dir, stop_check)
            if xlsx_path and os.path.exists(xlsx_path):
                break
            _safe_sleep(1.0, stop_check)

            _ensure_filters_on(driver, wait_cfg, stop_check)

        if not xlsx_path or not os.path.exists(xlsx_path):
            raise RuntimeError("Не удалось дождаться скачивания Excel")

        saved_excel = _move_to_outputs(xlsx_path, excel_out_dir)

        # -----------------
        # чекбокс
        # -----------------
        for attempt in range(1, 4):
            if stop_check and stop_check():
                return
            ok = _ensure_single_checkbox_active(driver, wait_cfg, stop_check)
            if ok:
                break
            _safe_sleep(0.6, stop_check)
        else:
            raise RuntimeError("Шаг 10: чекбокс не удалось установить в активное состояние")

        _ensure_row_selected_before_txt(driver, wait_cfg, stop_check)
        if stop_check and stop_check():
            return

        # -----------------
        # ZIP - извлечь в TXT Outputs
        # -----------------
        zip_path = None
        for attempt in range(1, 4):
            if stop_check and stop_check():
                return
            zip_path = _download_zip(driver, wait_cfg, download_dir, stop_check)
            if zip_path and os.path.exists(zip_path):
                break
            _safe_sleep(1.0, stop_check)

        if not zip_path or not os.path.exists(zip_path):
            raise RuntimeError("Не удалось дождаться скачивания ZIP")

        extracted = _extract_zip_to_dir(zip_path, txt_out_dir)

        _safe_sleep(5.0, stop_check)

    finally:
        try:
            if original_implicit is not None:
                driver.implicitly_wait(int(original_implicit))
            else:
                driver.implicitly_wait(5)
        except Exception:
            pass
