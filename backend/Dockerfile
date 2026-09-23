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

# Зависимости ставятся до копирования кода: слой кэшируется и
# переустанавливается только при изменении requirements.txt.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
# Выгрузка источника едет в образе: проверка решения должна
# воспроизводиться одной командой, без ручного подкладывания файлов.
COPY data ./data

# Каталог для сертификатов Минцифры. В compose сюда монтируется ./certs.
RUN mkdir -p /app/certs

# Процесс не должен работать от root.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --- Образ для разработки и тестов ---
FROM runtime AS dev

USER root
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY pytest.ini ./
COPY tests ./tests
RUN chown -R appuser:appuser /app
USER appuser

CMD ["pytest"]
