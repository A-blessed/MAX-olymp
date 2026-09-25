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
    [string]$Domain
)

$ErrorActionPreference = 'Continue'

# Репозиторий лежит на уровень выше каталога deploy\.
Set-Location (Join-Path $PSScriptRoot '..')

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

Add-Section 'Машина' {
    $os = Get-CimInstance Win32_OperatingSystem
    "$($os.Caption) ($($os.Version))"
    "Имя: $env:COMPUTERNAME"
    "Пользователь: $env:USERNAME"
    "Запущена с: $($os.LastBootUpTime)"
    "PowerShell: $($PSVersionTable.PSVersion)"
}

Add-Section 'Версия кода' {
    git rev-parse --short HEAD
    git log -1 --format='%s (%ci)'
    ''
    'Незакоммиченные изменения:'
    git status --porcelain
}

# .env печатаем построчно: секретные значения нельзя показывать даже
# замаскированными — по длине строки токен угадывается.
Add-Section 'Переменные окружения (.env)' {
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
}

Add-Section 'Python и зависимости' {
    "python: " + ((cmd /c 'python --version 2>&1') -join ' ')
    "где: " + ((cmd /c 'where python 2>&1') -join '; ')
    ''
    'Запущенные процессы python/uvicorn:'
    $procs = Get-Process python, pythonw, uvicorn -ErrorAction SilentlyContinue
    if ($procs) { $procs | Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize }
    else { '  ни одного — бэкенд не запущен' }
}

Add-Section 'Сертификаты Минцифры (certs\)' {
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
Add-Section 'Кто слушает порты 80, 443, 8000, 5432, 5433' {
    $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in 80, 443, 8000, 5432, 5433 }
    if ($conns) {
        $conns | Select-Object LocalAddress, LocalPort, OwningProcess,
            @{ n = 'Процесс'; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } } |
            Sort-Object LocalPort | Format-Table -AutoSize
    }
    else { 'никто не слушает ни один из них' }
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

Write-Host "Готово: $out"
Write-Host 'Секреты в файле заменены на «<скрыто>», его можно пересылать целиком.'
