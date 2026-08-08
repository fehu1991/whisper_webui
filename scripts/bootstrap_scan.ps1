param(
    [string]$OutputPath = "",
    [switch]$JsonOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ProjectPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ReportRoot = Join-Path $ProjectRoot ".cache\environment"

if (-not $OutputPath) {
    $OutputPath = Join-Path $ReportRoot "bootstrap-report.json"
}
$MergedOutputPath = Join-Path $ReportRoot "environment-report.json"

New-Item -ItemType Directory -Force -Path $ReportRoot | Out-Null

function Get-DirectoryStats([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{
            available = $false
            files = 0
            size_mb = 0
        }
    }
    $measure = Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum
    return [ordered]@{
        available = $true
        files = $measure.Count
        size_mb = [math]::Round(($measure.Sum / 1MB), 1)
    }
}

function Get-GpuVendor([string]$Name, [string]$Compatibility) {
    $value = ($Name + " " + $Compatibility).ToLowerInvariant()
    if ($value -match "nvidia") { return "nvidia" }
    if ($value -match "amd|radeon|advanced micro devices") { return "amd" }
    if ($value -match "intel") { return "intel" }
    if ($value -match "microsoft basic") { return "microsoft-basic" }
    return "unknown"
}

function Get-NvidiaSmiRows {
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        return @()
    }
    $rows = @()
    $output = & nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader,nounits 2>$null
    if ($LASTEXITCODE -ne 0) {
        $output = & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>$null
    }
    foreach ($line in @($output)) {
        if (-not $line) { continue }
        $parts = @($line -split "," | ForEach-Object { $_.Trim() })
        $rows += [ordered]@{
            name = if ($parts.Count -gt 0) { $parts[0] } else { "" }
            driver_version = if ($parts.Count -gt 1) { $parts[1] } else { "" }
            memory_mb = if ($parts.Count -gt 2) { [double]$parts[2] } else { $null }
            compute_capability = if ($parts.Count -gt 3) { $parts[3] } else { "" }
        }
    }
    return $rows
}

$osInfo = Get-CimInstance Win32_OperatingSystem
$computerInfo = Get-CimInstance Win32_ComputerSystem
$cpuInfo = @(Get-CimInstance Win32_Processor)
$videoInfo = @(Get-CimInstance Win32_VideoController)
$nvidiaRows = @(Get-NvidiaSmiRows)
$nvidiaIndex = 0

$avx2 = $null
try {
    Add-Type @"
using System.Runtime.InteropServices;
public static class WhisperCpuFeatures {
    [DllImport("kernel32.dll")]
    public static extern bool IsProcessorFeaturePresent(uint feature);
}
"@
    $avx2 = [WhisperCpuFeatures]::IsProcessorFeaturePresent(40)
} catch {
    $avx2 = $null
}

$cpus = @()
foreach ($cpu in $cpuInfo) {
    $cpus += [ordered]@{
        name = [string]$cpu.Name
        manufacturer = [string]$cpu.Manufacturer
        cores = [int]$cpu.NumberOfCores
        logical_processors = [int]$cpu.NumberOfLogicalProcessors
        address_width = [int]$cpu.AddressWidth
        max_clock_mhz = [int]$cpu.MaxClockSpeed
        avx2 = $avx2
    }
}

$gpus = @()
foreach ($video in $videoInfo) {
    $vendor = Get-GpuVendor ([string]$video.Name) ([string]$video.AdapterCompatibility)
    $smi = $null
    if ($vendor -eq "nvidia" -and $nvidiaIndex -lt $nvidiaRows.Count) {
        $smi = $nvidiaRows[$nvidiaIndex]
        $nvidiaIndex += 1
    }
    $gpus += [ordered]@{
        name = [string]$video.Name
        vendor = $vendor
        driver_version = if ($smi) { $smi.driver_version } else { [string]$video.DriverVersion }
        memory_mb = if ($smi) {
            $smi.memory_mb
        } elseif ($video.AdapterRAM) {
            [math]::Round(([double]$video.AdapterRAM / 1MB), 0)
        } else {
            $null
        }
        compute_capability = if ($smi) { $smi.compute_capability } else { "" }
        nvidia_smi_ready = [bool]$smi
        status = [string]$video.Status
    }
}

$systemPythonCommand = Get-Command python -ErrorAction SilentlyContinue
$systemPythonVersion = ""
if ($systemPythonCommand) {
    $systemPythonVersion = (& python --version) 2>&1 | Out-String
    $systemPythonVersion = $systemPythonVersion.Trim()
}

$projectPythonVersion = ""
if (Test-Path -LiteralPath $ProjectPython) {
    $projectPythonVersion = (& $ProjectPython --version) 2>&1 | Out-String
    $projectPythonVersion = $projectPythonVersion.Trim()
}

$projectDrive = Split-Path -Qualifier $ProjectRoot
$driveName = $projectDrive.TrimEnd(":\")
$drive = Get-PSDrive -Name $driveName

$report = [ordered]@{
    schema_version = "1.0"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    system = [ordered]@{
        os = [string]$osInfo.Caption
        version = [string]$osInfo.Version
        build = [string]$osInfo.BuildNumber
        architecture = [string]$osInfo.OSArchitecture
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    cpu = $cpus
    memory = [ordered]@{
        total_gb = [math]::Round(([double]$computerInfo.TotalPhysicalMemory / 1GB), 1)
        free_gb = [math]::Round(([double]$osInfo.FreePhysicalMemory * 1KB / 1GB), 1)
    }
    disks = @(
        [ordered]@{
            name = $projectDrive
            total_gb = [math]::Round((($drive.Used + $drive.Free) / 1GB), 1)
            free_gb = [math]::Round(($drive.Free / 1GB), 1)
        }
    )
    gpus = $gpus
    python = [ordered]@{
        system_available = [bool]$systemPythonCommand
        system_version = $systemPythonVersion
        project_available = (Test-Path -LiteralPath $ProjectPython)
        project_version = $projectPythonVersion
        architecture = $osInfo.OSArchitecture
    }
    storage = [ordered]@{
        models = Get-DirectoryStats (Join-Path $ProjectRoot "models")
        cache = Get-DirectoryStats (Join-Path $ProjectRoot ".cache")
        transcriptions = Get-DirectoryStats (Join-Path $ProjectRoot "transcriptions")
        venv = Get-DirectoryStats (Join-Path $ProjectRoot ".venv")
    }
    privacy = [ordered]@{
        contains_token = $false
        contains_user_name = $false
        contains_computer_name = $false
    }
}

$json = $report | ConvertTo-Json -Depth 8
$json | Set-Content -LiteralPath $OutputPath -Encoding UTF8

if (Test-Path -LiteralPath $ProjectPython) {
    Push-Location $ProjectRoot
    try {
        & $ProjectPython -m whisper_app.environment.doctor --bootstrap-report $OutputPath --output $MergedOutputPath
        $doctorExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    exit $doctorExitCode
}

if ($JsonOnly) {
    $json
} else {
    Write-Host "Whisper bootstrap environment scan"
    Write-Host ""
    foreach ($cpu in $cpus) {
        Write-Host ("CPU: " + $cpu.name)
    }
    foreach ($gpu in $gpus) {
        Write-Host ("GPU: " + $gpu.name + " [" + $gpu.vendor + "]")
    }
    Write-Host ("Memory: " + $report.memory.total_gb + " GB")
    Write-Host ("Project drive free: " + $report.disks[0].free_gb + " GB")
    Write-Host ("Project Python: " + $(if ($report.python.project_available) { "ready" } else { "missing" }))
    Write-Host ""
    Write-Host ("Report: " + $OutputPath)
}

if (-not $report.python.system_available) { exit 1 }
if ($report.disks[0].free_gb -lt 10) { exit 1 }
exit 0
