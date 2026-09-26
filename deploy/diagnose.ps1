<#
    Один снимок состояния Windows-сервера — вместо переписки по кускам.

    Запускать на самом сервере (через RDP), из каталога с репозиторием:

        powershell -ExecutionPolicy Bypass -File deploy\diagnose.ps1

    Ключ -ExecutionPolicy Bypass нужен почти всегда: на Windows Server
    запуск скриптов закрыт по умолчанию, и без него команда молча
    откажет. Политику он меняет только для этого запуска.

    Скрипт ничего не меняет, не ставит и не перезапускает: только читает.
    На выходе — один файл diagnostics-<дата>.txt, который целиком можно
    показать тому, кто помогает чинить.

    Значения BOT_TOKEN, WEBHOOK_SECRET, POSTGRES_PASSWORD и
    CERTBOT_EMAIL в файл не попадают: они заменены на «<скрыто>» и в
    разборе .env, и в выводе команд, куда могли просочиться.

    Версия для Linux с Docker — deploy/diagnose.sh.
#>

param(
    [string]$Domain,
    [string]$Path
)

$ErrorActionPreference = 'Continue'

# Скрипт запускают двумя способами: из репозитория (тогда он лежит в
# deploy\) и скачанным отдельно, когда кода на машине может не быть
# вовсе. Слепой переход на каталог выше во втором случае уводил бы в
# случайную папку, и снимок выходил бы про неё — молча и неправильно.
# Раскладок две, и выглядят они совершенно по-разному.
#
#   repo     — клон или распакованный архив: docker-compose.prod.yml,
#              рядом каталоги backend\ и frontend\;
#   deployed — запуск без Docker: содержимое backend\ разложено в корень
#              (app\, migrations\, alembic.ini), frontend\ и certs\ лежат
#              рядом. Именно так описан C:\Server в документации.
#
# Искать только первую — значит пройти мимо рабочего сервера и заявить,
# что кода на машине нет.
function Get-RepoKind([string]$dir) {
    if (-not $dir) { return $null }
    if ((Test-Path (Join-Path $dir 'docker-compose.prod.yml')) -and
        (Test-Path (Join-Path $dir 'backend'))) { return 'repo' }
    if ((Test-Path (Join-Path $dir 'app')) -and
        (Test-Path (Join-Path $dir 'alembic.ini'))) { return 'deployed' }
    return $null
}

function Find-RepoRoot([string]$start) {
    if (-not $start) { return $null }
    $dir = $start
    for ($i = 0; $i -lt 6; $i++) {
        if (Get-RepoKind $dir) { return $dir }
        $parent = Split-Path $dir -Parent
        if (-not $parent -or $parent -eq $dir) { break }
        $dir = $parent
    }
    return $null
}

$repoRoot = $null
if ($Path) {
    $resolved = (Resolve-Path $Path -ErrorAction SilentlyContinue)
    if ($resolved) {
        $repoRoot = Find-RepoRoot $resolved.Path
        # Путь указали руками — значит знают лучше скрипта. Берём как
        # есть, даже без знакомых меток: пусть снимок выйдет неполным,
        # чем скрипт уйдёт собирать данные про другой каталог.
        if (-not $repoRoot) {
            $repoRoot = $resolved.Path
            Write-Host "Знакомых меток по этому пути нет, но беру его как есть."
        }
    }
    else { Write-Host "Каталога $Path не существует, ищу сам." }
}
if (-not $repoRoot) { $repoRoot = Find-RepoRoot $PSScriptRoot }
if (-not $repoRoot) { $repoRoot = Find-RepoRoot (Get-Location).Path }

if ($repoRoot) { Set-Location $repoRoot }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = "diagnostics-$stamp.txt"
$report = New-Object System.Text.StringBuilder

function Add-Line([string]$text) { [void]$report.AppendLine($text) }

function Add-Section([string]$title, [scriptblock]$body) {
    [void]$report.AppendLine()
    [void]$report.AppendLine()
    [void]$report.AppendLine("===== $title =====")
    try {
        # Ширина обязательна: Format-Table -AutoSize определяет её по
        # консоли, а при захвате вывода консоли нет — и таблица
        # приходит пустой. Именно так молча терялись целые разделы.
        $result = & $body 2>&1 | Out-String -Width 200
        [void]$report.AppendLine($result.TrimEnd())
    }
    catch {
        [void]$report.AppendLine("[не выполнилось: $($_.Exception.Message)]")
    }
}

# --- .env: значения и кодировка ---------------------------------------

$secretKeys = @('BOT_TOKEN', 'WEBHOOK_SECRET', 'POSTGRES_PASSWORD', 'CERTBOT_EMAIL')
$envValues = @{}

if (Test-Path .env) {
    # Читаем как UTF-8 намеренно: если файл на самом деле UTF-16 (его
    # делает PowerShell через «>» и Out-File), строки развалятся — и это
    # само по себе диагноз, ровно та ошибка, на которой падает старт.
    foreach ($line in [System.IO.File]::ReadAllLines((Resolve-Path .env), [System.Text.Encoding]::UTF8)) {
        $line = $line.TrimEnd("`r")
        if ($line -match '^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)$') {
            $envValues[$matches[1].ToUpper()] = $matches[2].Trim().Trim('"').Trim("'")
        }
    }
}

if (-not $Domain) {
    $Domain = $envValues['DOMAIN']
    if (-not $Domain) { $Domain = 'my-olymp.ru' }
}

# --- Сбор -------------------------------------------------------------

Add-Line 'Снимок состояния MAX-olymp (Windows)'
Add-Line ("Снят: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Add-Line "Домен: $Domain"
Add-Line ("Каталог: " + (Get-Location).Path)
if ($repoRoot) {
    switch (Get-RepoKind $repoRoot) {
        'repo'     { Add-Line "Код: репозиторий целиком (docker-compose.prod.yml и backend\)" }
        'deployed' { Add-Line "Код: раскладка для запуска без Docker (app\ и alembic.ini в корне)" }
        default    { Add-Line "Код: каталог указан вручную, знакомых меток в нём нет" }
    }
}
else {
    Add-Line "Репозиторий: НЕ НАЙДЕН — кода на этой машине нет или он лежит не здесь."
    Add-Line "             Разделы про версию кода, .env и сертификаты будут пустыми."
    Add-Line "             Укажите путь вручную: -Path C:\путь\к\MAX-olymp"
}

Add-Section 'Машина' {
    $os = Get-CimInstance Win32_OperatingSystem
    "$($os.Caption) ($($os.Version))"
    "Имя: $env:COMPUTERNAME"
    "Пользователь: $env:USERNAME"
    "Запущена с: $($os.LastBootUpTime)"
    "PowerShell: $($PSVersionTable.PSVersion)"
}

Add-Section 'Версия кода' {
    if (-not $repoRoot) { 'Репозиторий не найден — смотреть нечего.'; return }
    if (Test-Path (Join-Path $repoRoot '.git')) {
        git rev-parse --short HEAD
        git log -1 --format='%s (%ci)'
        ''
        'Незакоммиченные изменения:'
        git status --porcelain
    }
    else {
        # Определяет способ доставки правок, поэтому не мелочь.
        'Это НЕ git-клон: каталога .git нет.'
        'Код скопирован или распакован из архива, поэтому git pull сюда'
        'ничего не доставит, а какой версии этот срез — по файлам не'
        'определить.'
        ''
        'Даты изменения в корне (что правили и когда):'
        Get-ChildItem $repoRoot | Sort-Object LastWriteTime -Descending |
            Select-Object -First 12 Name, LastWriteTime | Format-Table -AutoSize
    }
}

# .env печатаем построчно: секретные значения нельзя показывать даже
# замаскированными — по длине строки токен угадывается.
if (-not $repoRoot) {
    Add-Section 'Поиск репозитория по диску' {
        'Ищу в C:\ (до 5 уровней вглубь), это займёт полминуты.'
        ''
        # Две метки на две раскладки: docker-compose.prod.yml у полного
        # репозитория, alembic.ini у развёрнутого без Docker.
        $found = @()
        foreach ($mark in 'docker-compose.prod.yml', 'alembic.ini') {
            $found += Get-ChildItem 'C:\' -Filter $mark -Recurse -Depth 5 -ErrorAction SilentlyContinue |
                ForEach-Object { $_.DirectoryName }
        }
        $found = $found | Sort-Object -Unique | Select-Object -First 10
        if ($found) {
            'Нашёл. Перезапустите скрипт с -Path на один из этих каталогов:'
            $found | ForEach-Object { "  -Path " + [char]34 + $_ + [char]34 }
            ''
            'Каталогов несколько — значит на машине лежит несколько копий'
            'кода, и стоит разобраться, какая из них рабочая.'
        }
        else { 'Не нашёл — кода на этой машине действительно нет.' }
    }
}

Add-Section 'Переменные окружения (.env)' {
    if (-not $repoRoot) { 'Репозиторий не найден — смотреть нечего.'; return }
    if (-not (Test-Path .env)) {
        'Файла .env нет. Без него не заданы ни токен бота, ни секрет вебхука.'
        return
    }

    $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path .env))
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        'ВНИМАНИЕ: файл в UTF-16. Так пишут «>» и Out-File в PowerShell 5.1.'
        'Приложение падает на старте с UnicodeDecodeError. Пересоздать из cmd.'
        ''
    }

    foreach ($key in ($envValues.Keys | Sort-Object)) {
        if ($secretKeys -contains $key) {
            $value = $envValues[$key]
            if ($value) { "$key=<скрыто, $($value.Length) символов>" }
            else { "$key=<ПУСТО>" }
        }
        else {
            "$key=$($envValues[$key])"
        }
    }

    if (Test-Path .env.example) {
        ''
        'Не заданы вовсе (есть в .env.example, нет в .env):'
        foreach ($line in Get-Content .env.example) {
            if ($line -match '^([A-Z_][A-Z_0-9]*)=') {
                if (-not $envValues.ContainsKey($matches[1])) { "  $($matches[1])" }
            }
        }
    }
    else {
        ''
        '(.env.example рядом нет — он лежит в корне репозитория, а в'
        ' раскладке без Docker туда не попадает. Сверка с полным списком'
        ' переменных пропущена, но разбор по существу ниже её заменяет.)'
    }
}

# Перечислить переменные мало: беда обычно не в том, что видно, а в том,
# чего нет. Эти проверки — про уже наступавшие грабли, а не абстрактные.
Add-Section 'Разбор .env по существу' {
    if (-not $repoRoot) { 'Репозиторий не найден — смотреть нечего.'; return }
    if (-not (Test-Path .env)) { 'Файла .env нет — проверять нечего.'; return }

    $problems = @()

    $dbUrl = $envValues['DATABASE_URL']
    if (-not $dbUrl) {
        $problems += 'DATABASE_URL не задан. Умолчание ведёт на хост db, который существует только в сети Docker: вне контейнера бэкенд упадёт на getaddrinfo. POSTGRES_USER, POSTGRES_PASSWORD и POSTGRES_PORT его НЕ заменяют — их читает только docker compose, приложение берёт адрес базы целиком из DATABASE_URL.'
    }
    elseif ($dbUrl -match '@db[:/]') {
        $problems += 'DATABASE_URL ведёт на хост db из Docker, вне контейнера такого хоста нет.'
    }

    $appEnv = $envValues['APP_ENV']
    if ($appEnv -and $appEnv -ne 'production') {
        $problems += "APP_ENV=$appEnv. На публичном сервере это отдаёт /docs и /openapi.json наружу. В Docker значение принудительно ставил compose-файл, без него не ставит никто."
    }

    if ($envValues['CORS_ORIGINS'] -eq '*') {
        $problems += 'CORS_ORIGINS=*, в шаблоне стоит адрес домена. Фронтенд отдаётся с того же origin, так что звёздочка ничего не решает, а ограничение снимает.'
    }

    $dbPass = $envValues['POSTGRES_PASSWORD']
    if ($dbPass -and $dbPass.Length -le 4) {
        $problems += "POSTGRES_PASSWORD длиной $($dbPass.Length) символа — похоже на пример из шаблона. Postgres слушает на всех интерфейсах, пароль стоит сменить."
    }

    foreach ($key in 'BOT_TOKEN', 'WEBHOOK_SECRET', 'PUBLIC_BASE_URL') {
        if (-not $envValues[$key]) { $problems += "$key не задан — без него работать не будет." }
    }

    if ($problems) {
        "Найдено проблем: $($problems.Count)"
        ''
        for ($i = 0; $i -lt $problems.Count; $i++) {
            "$($i + 1). $($problems[$i])"
            ''
        }
    }
    else { 'Ничего подозрительного.' }
}

Add-Section 'Python и зависимости' {
    "python: " + ((cmd /c 'python --version 2>&1') -join ' ')
    "где: " + ((cmd /c 'where python 2>&1') -join '; ')
    ''
    'Запущенные процессы python/uvicorn:'
    # Именно с командной строкой: без неё видно только «что-то работает»,
    # а нужно знать что, откуда запущено и с какими ключами.
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(python|pythonw|uvicorn)' }
    if ($procs) {
        foreach ($proc in $procs) {
            "  PID $($proc.ProcessId), запущен $($proc.CreationDate)"
            "    $($proc.CommandLine)"
        }
    }
    else { '  ни одного — бэкенд не запущен' }
}

Add-Section 'Сертификаты Минцифры (certs\)' {
    if (-not $repoRoot) { 'Репозиторий не найден — смотреть нечего.'; return }
    if (Test-Path certs) { Get-ChildItem certs | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize }
    else { 'каталога нет — запросы к platform-api2.max.ru упадут на TLS' }
}

Add-Section 'PostgreSQL' {
    $svc = Get-Service -Name '*postgres*' -ErrorAction SilentlyContinue
    if ($svc) { $svc | Select-Object Name, Status, StartType | Format-Table -AutoSize }
    else { 'служба не найдена — Postgres либо не установлен, либо named иначе' }
}

# Кто занимает порты. 80 и 443 — веб, 8000 — бэкенд, 5432/5433 — база.
# Занятый не тем процессом порт 80 (обычно это IIS) — самая частая
# причина, по которой certbot и Caddy не могут выпустить сертификат.
Add-Section 'Все слушающие порты' {
    $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $conns | Select-Object LocalAddress, LocalPort, OwningProcess,
            @{ n = 'Процесс'; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } } |
            Sort-Object LocalPort | Format-Table -AutoSize
        ''
        # Отдельной строкой, потому что отсутствие порта в списке выше
        # заметить труднее, чем присутствие.
        $busy = $conns.LocalPort
        foreach ($port in 80, 443, 8000) {
            if ($busy -contains $port) { "Порт ${port}: занят" }
            else { "Порт ${port}: СВОБОДЕН — на нём никто не слушает" }
        }
    }
    else { 'никто не слушает ничего — это странно' }
}

Add-Section 'IIS (частый захватчик порта 80)' {
    $w3 = Get-Service W3SVC -ErrorAction SilentlyContinue
    if ($w3) { "W3SVC: $($w3.Status). Если он занял 80, выпуск сертификата не пройдёт." }
    else { 'не установлен — порт 80 свободен от него' }
}

Add-Section 'Брандмауэр: правила для 80 и 443' {
    $rules = Get-NetFirewallRule -Enabled True -Direction Inbound -ErrorAction SilentlyContinue |
        Where-Object {
            $ports = ($_ | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue).LocalPort
            $ports -and ($ports -join ',') -match '(^|,)(80|443)(,|$)'
        }
    if ($rules) { $rules | Select-Object DisplayName, Action, Profile | Format-Table -AutoSize }
    else { 'разрешающих правил на 80/443 не нашлось — снаружи порты, скорее всего, закрыты' }
}

Add-Section "DNS: куда ведёт $Domain" {
    'A-записи (IPv4):'
    (Resolve-DnsName $Domain -Type A -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress } | ForEach-Object { '  ' + $_.IPAddress })
    ''
    'AAAA (лишняя запись ломает сайт «через раз»):'
    $aaaa = Resolve-DnsName $Domain -Type AAAA -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress }
    if ($aaaa) { $aaaa | ForEach-Object { '  ' + $_.IPAddress } } else { '  нет — это правильно' }
}

Add-Section 'Внешний IP этой машины' {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        (Invoke-WebRequest 'https://api.ipify.org' -UseBasicParsing -TimeoutSec 10).Content
        'Он должен совпадать с A-записью выше.'
    }
    catch { 'не удалось определить: ' + $_.Exception.Message }
}

Add-Section 'Бэкенд напрямую (http://127.0.0.1:8000/health)' {
    try {
        $r = Invoke-WebRequest 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 10
        "HTTP $($r.StatusCode)"
        $r.Content
    }
    catch { 'не отвечает: ' + $_.Exception.Message }
}

Add-Section "Снаружи (https://$Domain/health)" {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $r = Invoke-WebRequest "https://$Domain/health" -UseBasicParsing -TimeoutSec 20
        "HTTP $($r.StatusCode)"
        $r.Content
    }
    catch { 'не отвечает: ' + $_.Exception.Message }
}

Add-Section 'Место на диске' {
    Get-PSDrive -PSProvider FileSystem |
        Select-Object Name, @{ n = 'Занято, ГБ'; e = { [math]::Round($_.Used / 1GB, 1) } },
                            @{ n = 'Свободно, ГБ'; e = { [math]::Round($_.Free / 1GB, 1) } } |
        Format-Table -AutoSize
}

Add-Line ''
Add-Line ''
Add-Line '===== Конец снимка ====='

# --- Маскировка и запись ----------------------------------------------

$text = $report.ToString()

# Второй рубеж: значение секрета могло попасть в вывод команды или в
# текст ошибки. Короткие значения не трогаем — подстрока из трёх
# символов встретилась бы где угодно и изрешетила бы весь файл.
foreach ($key in $secretKeys) {
    $value = $envValues[$key]
    if ($value -and $value.Length -ge 8) {
        $text = $text.Replace($value, '<скрыто>')
    }
}

Set-Content -Path $out -Value $text -Encoding UTF8

$full = (Resolve-Path $out).Path
Write-Host "Готово: $full"
Write-Host 'Секреты в файле заменены на «<скрыто>», его можно пересылать целиком.'
