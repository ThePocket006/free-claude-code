#requires -Version 5.1

<#
    fcc-service.ps1 - Free Claude Code LOCAL service manager

    Manages the local (dev) fcc-server on a dedicated port using the
    workspace override env file (.fcc-local.env). It never touches the
    global config (~/.fcc/.env).

    Commands:
      start                 Start the local server in background
      stop                  Stop the local server
      restart               Restart the local server
      status, ps            Show server status (PID, port, health)
      health, check         Quick health check
      logs                  Tail the server logs
      server [args]         Run fcc-server in foreground (passes args)
      claude [args]         Launch Claude Code against the local server
      codex [args]          Launch Codex against the local server
      pi [args]             Launch Pi against the local server
      version               Show project + server version
      port                  Show the local port
      help                  Show this help
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------
# Constants (scripts live in <project>/bin, project is one level up)
# ---------------------------------------------------------------
$ScriptDir    = $PSScriptRoot
$ProjectDir   = Split-Path $ScriptDir -Parent
$VenvDir      = Join-Path $ProjectDir '.venv'
$ServerExe    = Join-Path $VenvDir 'Scripts\fcc-server.exe'
$ClaudeExe    = Join-Path $VenvDir 'Scripts\fcc-claude.exe'
$CodexExe     = Join-Path $VenvDir 'Scripts\fcc-codex.exe'
$PiExe        = Join-Path $VenvDir 'Scripts\fcc-pi.exe'
$LocalEnv     = Join-Path $ProjectDir '.fcc-local.env'
$OutLog       = Join-Path $ProjectDir '_fcc-local.out.log'
$ErrLog       = Join-Path $ProjectDir '_fcc-local.err.log'
$Name         = 'fcc-local'
$ScriptName   = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name) + '.ps1'
$DefaultPort  = 8091
$HealthPath   = '/health'
$HealthTries  = 40
$HealthDelay  = 0.5

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

function Assert-Project {
    if (-not (Test-Path (Join-Path $ProjectDir 'pyproject.toml'))) {
        Write-Error "Could not find free-claude-code project at: $ProjectDir"
        exit 1
    }
    if (-not (Test-Path $ServerExe)) {
        Write-Error "Local server executable not found: $ServerExe (run 'uv sync' first)"
        exit 1
    }
    if (-not (Test-Path $ClaudeExe)) {
        Write-Error "Local claude launcher not found: $ClaudeExe (run 'uv sync' first)"
        exit 1
    }
}

function Read-LocalEnv {
    param([string]$Key)
    if (-not (Test-Path $LocalEnv)) { return $null }
    $line = Select-String -Path $LocalEnv -Pattern "^$Key=" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $line) { return $null }
    $value = $line.Line.Substring($Key.Length + 1).Trim()
    $value = $value.Trim('"', "'")
    return $value
}

function Get-LocalPort {
    $port = Read-LocalEnv 'PORT'
    if ($port -and $port -match '^\d+$') { return [int]$port }
    return $DefaultPort
}

function Get-ServerConnection {
    $port = Get-LocalPort
    return Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-ServerProcess {
    $conn = Get-ServerConnection
    if (-not $conn) { return $null }
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmdLine) { $proc | Add-Member -NotePropertyName CommandLine -NotePropertyValue $cmdLine -Force }
    return $proc
}

function Test-Health {
    $port = Get-LocalPort
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port$HealthPath" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return $resp.StatusCode
    }
    catch {
        return $null
    }
}

function Set-LocalEnv {
    $env:FCC_ENV_FILE = $LocalEnv
}

# ---------------------------------------------------------------
# Service operations
# ---------------------------------------------------------------

function Start-FccService {
    Assert-Project
    if (Get-ServerProcess) {
        Write-Host "[$Name] already running (port $(Get-LocalPort))." -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path $LocalEnv)) {
        Write-Error "Override env file not found: $LocalEnv"
        exit 1
    }
    Set-LocalEnv
    Write-Host "[$Name] starting on port $(Get-LocalPort)..." -ForegroundColor Cyan
    Start-Process -FilePath $ServerExe `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog

    for ($i = 0; $i -lt $HealthTries; $i++) {
        Start-Sleep -Milliseconds ($HealthDelay * 1000)
        $status = Test-Health
        if ($status -eq 200) {
            $proc = Get-ServerProcess
            $procId = if ($proc) { $proc.Id } else { 'unknown' }
            Write-Host "[$Name] up (PID $procId, port $(Get-LocalPort), health 200)." -ForegroundColor Green
            return
        }
    }
    Write-Error "[$Name] failed to become healthy within $($HealthTries * $HealthDelay)s. Check $ErrLog"
    exit 1
}

function Stop-FccService {
    $conn = Get-ServerConnection
    if (-not $conn) {
        Write-Host "[$Name] not running (port $(Get-LocalPort))." -ForegroundColor Yellow
        return
    }
    $procId = $conn.OwningProcess
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Write-Host "[$Name] stopped (PID $procId)." -ForegroundColor Green
}

function Get-FccStatus {
    $port = Get-LocalPort
    $proc = Get-ServerProcess
    if (-not $proc) {
        Write-Host "[$Name] status: stopped (port $port)." -ForegroundColor Yellow
        return
    }
    $isLocal = $false
    if ($proc.CommandLine) {
        $isLocal = $proc.CommandLine.IndexOf($VenvDir, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    }
    $health = Test-Health
    Write-Host "[$Name] status:" -ForegroundColor Cyan
    Write-Host "  PID     : $($proc.Id)"
    Write-Host "  Port    : $port"
    Write-Host "  Health  : $(if ($health) { $health } else { 'unreachable' })"
    Write-Host "  Local   : $isLocal"
    Write-Host "  Started : $($proc.StartTime)"
    Write-Host "  Exe     : $($proc.Path)"
}

function Restart-FccService {
    Stop-FccService
    Start-FccService
}

function Get-FccLogs {
    param([switch]$Follow)
    $target = @($OutLog, $ErrLog) | Where-Object { Test-Path $_ }
    if (-not $target) {
        Write-Host "[$Name] no log files yet." -ForegroundColor Yellow
        return
    }
    if ($Follow) {
        Get-Content -Path $target -Wait -Tail 40
    }
    else {
        foreach ($log in $target) {
            Write-Host "===== $log =====" -ForegroundColor Cyan
            Get-Content -Path $log -Tail 40
        }
    }
}

# ---------------------------------------------------------------
# Foreground / client invocations
# ---------------------------------------------------------------

function Invoke-FccServer {
    param([string[]]$Rest)
    Assert-Project
    Set-LocalEnv
    & $ServerExe @Rest
    exit $LASTEXITCODE
}

function Invoke-FccClient {
    param([string]$Client, [string[]]$Rest)
    Assert-Project
    Set-LocalEnv
    $health = Test-Health
    if ($health -ne 200) {
        Write-Host "[$Name] server not healthy (port $(Get-LocalPort)); start it with: $ScriptName start" -ForegroundColor Yellow
    }
    $exe = switch ($Client) {
        'claude' { $ClaudeExe }
        'codex'  { $CodexExe }
        'pi'     { $PiExe }
        default  { $null }
    }
    if (-not $exe) {
        Write-Error "Unknown client: $Client"
        exit 1
    }
    & $exe @Rest
    exit $LASTEXITCODE
}

function Show-FccVersion {
    Assert-Project
    $port = Get-LocalPort
    Write-Host "[$Name] project: $ProjectDir"
    Write-Host "[$Name] port   : $port"
    Set-LocalEnv
    & $ServerExe --version
    exit $LASTEXITCODE
}

function Show-FccHelp {
    Write-Host ""
    Write-Host "  $Name - Free Claude Code LOCAL service manager" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Usage: $ScriptName [command] [args...]" -ForegroundColor White
    Write-Host ""
    Write-Host "  Commands:" -ForegroundColor White
    Write-Host "    start                 Start the local server in background"
    Write-Host "    stop                  Stop the local server"
    Write-Host "    restart               Restart the local server"
    Write-Host "    status, ps            Show server status (PID, port, health)"
    Write-Host "    health, check         Quick health check"
    Write-Host "    logs                  Tail the server logs"
    Write-Host "    logs -f               Follow the server logs (live)"
    Write-Host "    server [args]         Run fcc-server in foreground"
    Write-Host "    claude [args]         Launch Claude Code against the local server"
    Write-Host "    codex [args]          Launch Codex against the local server"
    Write-Host "    pi [args]             Launch Pi against the local server"
    Write-Host "    version               Show project + server version"
    Write-Host "    port                  Show the local port"
    Write-Host "    help                  Show this help"
    Write-Host ""
    Write-Host "  Examples:" -ForegroundColor White
    Write-Host "    $ScriptName start"
    Write-Host "    $ScriptName status"
    Write-Host "    $ScriptName claude --version"
    Write-Host ""
}

# ---------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------

$cmd = if ($args.Count -gt 0) { $args[0] } else { $null }
$rest = @()
if ($args.Count -gt 1) { $rest = @($args[1..($args.Count - 1)]) }

switch -Regex ($cmd) {
    '^start$'        { Start-FccService }
    '^stop$'         { Stop-FccService }
    '^restart$'      { Restart-FccService }
    '^(status|ps)$'  { Get-FccStatus }
    '^(health|check)$' {
        $status = Test-Health
        if ($status -eq 200) {
            Write-Host "[$Name] healthy (port $(Get-LocalPort), HTTP $status)." -ForegroundColor Green
        }
        else {
            Write-Host "[$Name] not healthy (port $(Get-LocalPort))." -ForegroundColor Red
            exit 1
        }
    }
    '^(logs|log)$'   {
        if ($rest -contains '-f' -or $rest -contains '--follow') {
            Get-FccLogs -Follow
        }
        else {
            Get-FccLogs
        }
    }
    '^server$'       { Invoke-FccServer -Rest $rest }
    '^claude$'       { Invoke-FccClient -Client 'claude' -Rest $rest }
    '^codex$'        { Invoke-FccClient -Client 'codex' -Rest $rest }
    '^pi$'           { Invoke-FccClient -Client 'pi' -Rest $rest }
    '^(version|-v|--version)$' { Show-FccVersion }
    '^port$'         { Write-Host (Get-LocalPort) }
    '^(help|-h|--help)$' { Show-FccHelp }
    default {
        if (-not $cmd) {
            Show-FccHelp
        }
        else {
            Write-Host "[$Name] unknown command: $cmd" -ForegroundColor Red
            Write-Host "Run: $ScriptName help"
            exit 1
        }
    }
}
