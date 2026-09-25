# Развёртывание на my-olymp.ru

Постоянный домен заменяет туннель. Всё решение живёт на одном адресе:

| Адрес                        | Что отдаёт                                  |
|------------------------------|---------------------------------------------|
| `https://my-olymp.ru/`       | мини-приложение, статика из `frontend/`      |
| `https://my-olymp.ru/api/*`  | API, авторизация по подписи данных запуска    |
| `https://my-olymp.ru/webhook`| события бота от платформы MAX                 |
| `https://my-olymp.ru/health` | проверка живости                              |

Один origin на фронтенд и API — это не только удобство: браузер не делает
preflight, CORS в бою не участвует вовсе, а заголовок-костыль
`ngrok-skip-browser-warning` больше не нужен и удалён.

---

## Что должно быть на сервере

* Linux с установленными Docker и Docker Compose v2;
* открытые извне порты **80** и **443** (80 нужен не только для
  редиректа — через него Let's Encrypt подтверждает владение доменом);
* A-запись `my-olymp.ru` на IP этого сервера. Если заводите ещё и `www`,
  A-запись для него тоже должна существовать **до** выпуска сертификата.

Проверить, что DNS уже разъехался, стоит заранее:

```bash
dig +short my-olymp.ru
```

---

## 1. Код и настройки

```bash
git clone https://github.com/A-blessed/MAX-olymp.git
cd MAX-olymp
cp .env.example .env
```

В `.env` заполнить:

| Переменная        | Значение                                            |
|-------------------|-----------------------------------------------------|
| `BOT_TOKEN`       | токен бота                                          |
| `BOT_USERNAME`    | ник бота без `@`                                    |
| `WEBHOOK_SECRET`  | произвольная строка 5–256 символов `[A-Za-z0-9_-]`  |
| `POSTGRES_PASSWORD` | не `app`: база хоть и не публикуется наружу, пароль из примера в проде не место |
| `CERTBOT_EMAIL`   | почта для писем об истечении сертификата            |

`PUBLIC_BASE_URL=https://my-olymp.ru` и `CORS_ORIGINS=https://my-olymp.ru`
уже стоят в шаблоне — менять их не нужно.

`APP_ENV` из `.env` в проде не читается: `docker-compose.prod.yml` жёстко
ставит `production`, иначе схема API открылась бы наружу молча.

Сертификаты Минцифры положить в `certs/` — без них бэкенд не установит
TLS-соединение с `platform-api2.max.ru`. Это отдельная история от
сертификата домена, они не взаимозаменяемы:

| Сертификат          | Зачем                                    | Откуда           |
|---------------------|------------------------------------------|------------------|
| Минцифры, `certs/`  | бэкенд → `platform-api2.max.ru`          | Госуслуги        |
| Let's Encrypt       | браузер и MAX → `my-olymp.ru`            | certbot, шаг 2   |

---

## 2. Сертификат домена

Курица и яйцо: nginx не поднимется без файла сертификата, а certbot не
сможет подтвердить домен через nginx, пока тот не поднялся. Поэтому
**первый** выпуск делается в режиме `--standalone`, когда порт 80 ещё
свободен, — то есть до первого `up`:

```bash
docker compose -f docker-compose.prod.yml run --rm -p 80:80 \
  --entrypoint certbot certbot \
  certonly --standalone --non-interactive --agree-tos \
  --email ВАША@ПОЧТА --no-eff-email \
  -d my-olymp.ru -d www.my-olymp.ru
```

Если A-записи для `www` нет — уберите `-d www.my-olymp.ru`, иначе выпуск
упадёт на проверке домена. В этом случае удалите и серверный блок `www`
из [`deploy/nginx/my-olymp.ru.conf`](../deploy/nginx/my-olymp.ru.conf):
без сертификата на `www` он отдаёт браузеру ошибку.

Сертификат ложится в том `letsencrypt` — не в репозиторий: закрытый ключ
не должен попасть в git даже случайно.

**Продление автоматическое.** Сервис `certbot` дважды в сутки вызывает
`renew` (до истечения срока больше 30 дней он ничего не делает), а nginx
раз в сутки перечитывает конфигурацию и подхватывает новый файл без
перезапуска и без обрыва соединений.

---

## 3. Запуск

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Поднимутся четыре сервиса: `db`, `backend`, `nginx`, `certbot`. Схему базы
Alembic применяет сам при старте бэкенда.

Наполнить каталог:

```bash
docker compose -f docker-compose.prod.yml run --rm backend python -m scripts.import_subjects
docker compose -f docker-compose.prod.yml run --rm backend python -m scripts.import_catalog
```

Проверить снаружи:

```bash
curl https://my-olymp.ru/health
```

Ожидается `{"status":"ok","env":"production","bot_configured":true,"webhook_secret_set":true}`.
Оба флага должны быть `true` — если нет, `.env` не доехал до контейнера.

И что отдаётся само приложение:

```bash
curl -I https://my-olymp.ru/
```

---

## 4. Подписка на события бота

Адрес вебхука сменился с туннельного на постоянный, поэтому подписку
нужно оформить заново — старая продолжает указывать на ngrok:

```bash
docker compose -f docker-compose.prod.yml run --rm backend python -m scripts.setup_webhook
```

Проверить, что осталась только одна подписка и она на новый адрес:

```bash
docker compose -f docker-compose.prod.yml run --rm backend python -m scripts.setup_webhook --list
```

Если в списке остался туннельный адрес, удалить его:

```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.setup_webhook --delete --url https://СТАРЫЙ-АДРЕС/webhook
```

Это важнее, чем кажется: пока подписка висит на мёртвом адресе, MAX
считает события недоставленными, а через 8 часов неудач отписывает бота
сам.

---

## 5. Адрес мини-приложения в кабинете MAX

**Через код этого сделать нельзя** — в Bot API нет такого метода. Только
в кабинете партнёров: **Чат-боты** → нужный бот → **⋮** →
**Настройки** → поле URL мини-приложения:

```
https://my-olymp.ru
```

Пока там стоит адрес GitHub Pages, MAX будет открывать старую копию
приложения, и никакие изменения на сервере на это не повлияют. Если
доступа к кабинету нет — адрес нужно передать организаторам.

---

## Обновление кода

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build backend
```

Фронтенд подключён к nginx томом, а не вложен в образ: правки в
`frontend/` доезжают одним `git pull`, пересобирать ничего не нужно.
Статика отдаётся с `Cache-Control: no-cache`, иначе встроенный браузер
MAX держал бы старую версию и после деплоя.

---

## Если что-то не работает

| Симптом | Где смотреть |
|---|---|
| `nginx: host not found in upstream "backend"` | бэкенд не стал healthy; `docker compose -f docker-compose.prod.yml logs backend` |
| 502 на `/api/*` | бэкенд упал или ещё применяет миграции; те же логи |
| 404 на `/docs` | так и задумано: `APP_ENV=production` закрывает схему |
| Приложение открылось, но данные не грузятся | адрес в кабинете MAX ведёт не на `my-olymp.ru`, либо origin не совпал — сверьте адрес в строке браузера с `BASE_URL` в `frontend/api.js` |
| Бот не отвечает | подписка указывает на старый адрес; шаг 4 |
| Ошибка сертификата на `www` | сертификат выписан без `www`; либо добавьте его в certbot, либо удалите блок `www` из конфига nginx |
| `Address family not supported by protocol` в логах nginx | на хосте отключён IPv6, а в конфиге появились строки `listen [::]` |
