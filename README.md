## Что нужно

- Python 3.8+

## Настройка

1. Задать адрес страницы:
   - Скопировать `.env.example` в `.env`
   - В `.env` указать: `EB_BASE_URL=https://...` (полный URL страницы для входа)
   - Либо задать переменную окружения `EB_BASE_URL` в системе/терминале


## Запуск

python eb_robot.py

(предварительно: `pip install -r requirements.txt` или активировать venv и установить зависимости)


## Папки с файлами

- downloads — временные загрузки
- Excel outputs — сохранённые Excel-файлы
- TXT Outputs — распакованные TXT из ZIP