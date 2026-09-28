# Два целевых образа:
#   runtime — то, что крутится в бою и в compose по умолчанию;
#   dev     — то же плюс pytest, для прогона тестов.
# Разделение держит рабочий образ без лишних зависимостей.

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Процесс не должен работать от root. Код при этом остаётся за root и
# процессу доступен только на чтение — писать в /app приложению нечего,
# поэтому ни chown -R, ни лишнего слоя с копией всех файлов не нужно.
# Каталог для сертификатов Минцифры: в compose сюда монтируется ./certs.
RUN useradd --create-home --uid 1000 appuser && mkdir -p /app/certs

# Зависимости ставятся до копирования кода: слой кэшируется и
# переустанавливается только при изменении requirements.txt.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Миграции схемы едут в образе: сервис применяет их при старте.
COPY alembic.ini ./
COPY migrations ./migrations
# Выгрузки источников едут в образе: при первом старте ими наполняется
# пустой каталог (scripts/seed.py), без ручного подкладывания файлов.
COPY data ./data
COPY scripts ./scripts
COPY app ./app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --- Образ для разработки и тестов ---
FROM runtime AS dev

USER root
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY pytest.ini ./
COPY tests ./tests
USER appuser

# Код принадлежит root, и кэшу pytest писать некуда. Между прогонами в
# одноразовом контейнере он всё равно не живёт — отключаем, а не чиним.
ENV PYTEST_ADDOPTS="-p no:cacheprovider"

CMD ["pytest"]
