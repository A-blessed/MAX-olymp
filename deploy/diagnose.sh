#!/usr/bin/env bash
# Один снимок состояния сервера — вместо переписки по кускам.
#
# Запускать на самой машине, из каталога с репозиторием:
#
#     bash deploy/diagnose.sh
#
# Скрипт ничего не меняет и ничего не перезапускает: только читает. На
# выходе — один файл diagnostics-<дата>.txt, который целиком можно
# показать тому, кто помогает чинить. Смысл именно в «целиком»: половина
# поломок деплоя видна не в той строке, на которую смотришь, а в соседней
# — в дате сертификата, в чужом IP у домена, в том, что контейнер не
# запущен вовсе. Пересказ такое теряет, файл — нет.
#
# Значения BOT_TOKEN, WEBHOOK_SECRET, POSTGRES_PASSWORD и CERTBOT_EMAIL
# в файл не попадают: они заменены на «<скрыто>» и в самом .env, и в
# логах, куда могли просочиться. Файл предназначен для пересылки, а
# секреты пересылать нельзя.

set -u

cd "$(dirname "$0")/.." || exit 1

COMPOSE_FILE=docker-compose.prod.yml
OUT="diagnostics-$(date +%Y%m%d-%H%M%S).txt"

# --- Подготовка -------------------------------------------------------

# Значение переменной из .env: без кавычек и без CR, который дописывает
# Windows, если файл редактировали там.
env_value() {
    [ -r .env ] || return 0
    sed -n "s/^$1=//p" .env | head -1 | tr -d '\r' | sed 's/^["'\'']//; s/["'\'']$//'
}

DOMAIN="$(env_value DOMAIN)"
[ -n "$DOMAIN" ] || DOMAIN=my-olymp.ru

# Compose v2 — подкоманда docker, v1 — отдельная программа. На сервере
# может оказаться любая, а различать их в каждой строке ниже не хочется.
if docker compose version >/dev/null 2>&1; then
    DC="docker compose -f $COMPOSE_FILE"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose -f $COMPOSE_FILE"
else
    DC=""
fi

# Список замен для секретов. Короткие значения не маскируем: подстрока из
# трёх символов встретится в выводе где угодно и изрешетит весь файл.
MASK="$(mktemp)"
trap 'rm -f "$MASK"' EXIT
if [ -r .env ]; then
    for key in BOT_TOKEN WEBHOOK_SECRET POSTGRES_PASSWORD CERTBOT_EMAIL; do
        value="$(env_value "$key")"
        [ "${#value}" -ge 8 ] || continue
        printf 's|%s|<скрыто>|g\n' \
            "$(printf '%s' "$value" | sed 's|[\\/&|]|\\&|g')" >> "$MASK"
    done
fi

section() {
    printf '\n\n===== %s =====\n' "$1"
    shift
    sh -c "$*" 2>&1 || printf '[команда не выполнилась]\n'
}

# --- Сбор -------------------------------------------------------------

collect() {

printf 'Снимок состояния MAX-olymp\n'
printf 'Снят: %s\n' "$(date -Is 2>/dev/null || date)"
printf 'Домен: %s\n' "$DOMAIN"
printf 'Каталог: %s\n' "$(pwd)"

section 'Машина' 'uname -a; echo; hostname; echo; id'
section 'Docker' 'docker version --format "клиент {{.Client.Version}}, сервер {{.Server.Version}}" || docker --version'

if [ -z "$DC" ]; then
    printf '\n\n===== Compose =====\n'
    printf 'Ни «docker compose», ни «docker-compose» не найдены.\n'
    printf 'Всё, что ниже зависит от контейнеров, собрать не получится.\n'
fi

section 'Версия кода' \
    'git rev-parse --short HEAD; git log -1 --format="%s (%ci)"; echo; echo "Незакоммиченные изменения:"; git status --porcelain'

# .env печатаем построчно, а не через cat: секретные значения нельзя
# показывать даже замаскированными — по длине строки токен угадывается.
printf '\n\n===== Переменные окружения (.env) =====\n'
if [ -r .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in
            ''|'#'*) continue ;;
            BOT_TOKEN=*|WEBHOOK_SECRET=*|POSTGRES_PASSWORD=*|CERTBOT_EMAIL=*)
                key="${line%%=*}"
                value="${line#*=}"
                if [ -n "$value" ]; then
                    printf '%s=<скрыто, %s символов>\n' "$key" "${#value}"
                else
                    printf '%s=<ПУСТО>\n' "$key"
                fi
                ;;
            *) printf '%s\n' "$line" ;;
        esac
    done < .env
    printf '\nНе заданы вовсе (есть в .env.example, нет в .env):\n'
    for key in $(sed -n 's/^\([A-Z_][A-Z_0-9]*\)=.*/\1/p' .env.example | sort -u); do
        grep -q "^$key=" .env || printf '  %s\n' "$key"
    done
else
    printf 'Файла .env нет — бэкенд не увидит ни токена бота, ни секрета вебхука.\n'
fi

printf '\n\n===== Сертификаты Минцифры (certs/) =====\n'
ls -l certs/ 2>&1 | grep -v '^total' || printf 'каталога нет\n'

[ -n "$DC" ] && {
section 'Контейнеры' "$DC ps -a"
section 'Перезапуски и состояние' \
    'docker ps -a --filter label=com.docker.compose.project --format "{{.Names}}\t{{.Status}}\t{{.Image}}"'

# Логи — последними: они длинные, а всё, что выше, обычно и объясняет
# причину. По 80 строк хватает, чтобы увидеть и старт, и падение.
for svc in db backend nginx certbot; do
    section "Логи: $svc (последние 80 строк)" "$DC logs --tail 80 --no-color $svc"
done

section 'Проверка конфигурации nginx' "$DC exec -T nginx nginx -t"
section 'Сертификат домена' "$DC run --rm --entrypoint certbot certbot certificates"
section 'Место, занятое Docker' 'docker system df'
}

# Кто слушает 80 и 443. Без root имена процессов не покажутся — это
# нормально, номера портов всё равно видны.
section 'Порты 80 и 443' \
    '(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ":(80|443)\b" || echo "никто не слушает — nginx не поднялся или порты заняты не им"'

# dig входит в пакет dnsutils, а его на сервере ставят не всегда.
# getent есть в любой системе с glibc и показывает то же самое — куда
# резолвится домен прямо сейчас, с этой машины.
section "DNS: куда ведёт $DOMAIN" \
    "echo 'A-записи (IPv4):'; (dig +short $DOMAIN A 2>/dev/null || getent ahostsv4 $DOMAIN | awk '{print \$1}' | sort -u); echo; echo 'AAAA (лишняя запись ломает сайт «через раз»):'; (dig +short $DOMAIN AAAA 2>/dev/null || getent ahostsv6 $DOMAIN | awk '{print \$1}' | sort -u); echo; echo 'NS (эта панель и обслуживает домен):'; (dig +short $DOMAIN NS 2>/dev/null || echo 'нужен dig: apt install dnsutils')"

section 'Внешний IP этой машины' \
    'curl -s --max-time 10 https://api.ipify.org || echo "не удалось определить"'

section 'Проверка с самого сервера: /health' \
    "curl -sS --max-time 15 -w '\nHTTP %{http_code}\n' https://$DOMAIN/health"

section 'Проверка с самого сервера: корень' \
    "curl -sS --max-time 15 -o /dev/null -D - https://$DOMAIN/"

section 'Проверка в обход DNS (прямо в nginx на 127.0.0.1)' \
    "curl -sk --max-time 10 -o /dev/null -w 'HTTP %{http_code}\n' -H 'Host: $DOMAIN' https://127.0.0.1/health"

# Кончившееся место — частая и незаметная причина: Postgres перестаёт
# писать, certbot не сохраняет сертификат, а в логах видно только
# следствия.
section 'Место на диске' 'df -h /'

printf '\n\n===== Конец снимка =====\n'

}

collect 2>&1 | sed -f "$MASK" > "$OUT"

printf 'Готово: %s\n' "$OUT"
printf 'Секреты в файле заменены на «<скрыто>», его можно пересылать целиком.\n'
