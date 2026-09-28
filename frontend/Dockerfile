# Мини-приложение: статика и nginx перед бэкендом.
#
# Контекст сборки — корень репозитория (он задан в compose): кроме
# frontend/ нужны конфигурации nginx из deploy/nginx/. Что именно
# попадает в контекст, решает корневой .dockerignore.
#
# По умолчанию образ настроен на локальный запуск — обычный HTTP на 80.
# На сервере docker-compose.prod.yml подкладывает вместо default.conf
# конфигурацию my-olymp.ru с TLS; статика и proxy.conf те же.

FROM nginx:1.30-alpine

COPY deploy/nginx/proxy.conf /etc/nginx/proxy.conf
COPY deploy/nginx/local.conf /etc/nginx/conf.d/default.conf
COPY frontend/ /srv/frontend/
