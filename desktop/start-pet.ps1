$ErrorActionPreference = "SilentlyContinue"

$plugin = Split-Path -Parent $PSScriptRoot
$userData = Join-Path $env:APPDATA "dsh-pet-gujiguji"
New-Item -ItemType Directory -Path $userData -Force | Out-Null
$state = Join-Path $userData "state.json"
$position = Join-Path $userData "position.json"
$settings = Join-Path $userData "settings.json"
$sprite = Join-Path $plugin "assets\spritesheet.png"
$script = Join-Path $PSScriptRoot "pet-window.pyw"
$defaultSettings = Join-Path $PSScriptRoot "default-settings.json"

if (-not (Test-Path -LiteralPath $settings) -and (Test-Path -LiteralPath $defaultSettings)) {
  $legacySettings = @(
    (Join-Path $env:APPDATA "dsh-light-feather\settings.json"),
    (Join-Path $env:APPDATA "dsh-mint-budgie\settings.json")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  Copy-Item -LiteralPath $(if ($legacySettings) { $legacySettings } else { $defaultSettings }) -Destination $settings
}
$localPosition = Join-Path $PSScriptRoot "position.json"
if (-not (Test-Path -LiteralPath $position) -and (Test-Path -LiteralPath $localPosition)) {
  Copy-Item -LiteralPath $localPosition -Destination $position
}
if (-not (Test-Path -LiteralPath $position)) {
  $legacyPosition = @(
    (Join-Path $env:APPDATA "dsh-light-feather\position.json"),
    (Join-Path $env:APPDATA "dsh-mint-budgie\position.json")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if ($legacyPosition) {
    Copy-Item -LiteralPath $legacyPosition -Destination $position
  }
}
$bundledExe = $null
$versionedExe = Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*-*.exe" -File -ErrorAction SilentlyContinue |
  ForEach-Object {
    if ($_.BaseName -notmatch '^(dsh-pet-gujiguji|light-feather|mint-budgie)-(\d+\.\d+\.\d+)$') {
      return
    }
    $versionText = $Matches[2]
    try {
      [pscustomobject]@{ Path = $_.FullName; Version = [version]$versionText }
    } catch {
    }
  } |
  Sort-Object Version -Descending |
  Select-Object -First 1
if ($versionedExe) {
  $bundledExe = $versionedExe.Path
} else {
  foreach ($legacyName in @("dsh-pet-gujiguji.exe", "light-feather.exe", "mint-budgie.exe")) {
    $legacyExe = Join-Path $PSScriptRoot $legacyName
    if (Test-Path $legacyExe) {
      $bundledExe = $legacyExe
      break
    }
  }
}
$pidFile = Join-Path $PSScriptRoot "pet.pid"
$dshPidFile = Join-Path $userData "dsh.pid"
$hiddenFlag = Join-Path $userData "hidden.flag"

if (-not (Test-Path $sprite) -or (-not (Test-Path $script) -and -not $bundledExe)) {
  exit 1
}

if (Test-Path $hiddenFlag) {
  Remove-Item -LiteralPath $hiddenFlag -Force -ErrorAction SilentlyContinue
}

$knownPetExes = @(
  Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*-*.exe" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.BaseName -match '^(dsh-pet-gujiguji|light-feather|mint-budgie)-(\d+\.\d+\.\d+)$' } |
    ForEach-Object { $_.FullName }
  foreach ($legacyName in @("dsh-pet-gujiguji.exe", "light-feather.exe", "mint-budgie.exe")) {
    $legacyPath = Join-Path $PSScriptRoot $legacyName
    if (Test-Path -LiteralPath $legacyPath) { $legacyPath }
  }
)
$existingPets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {
    $isCurrentExe = $_.ExecutablePath -and ($_.ExecutablePath -eq $bundledExe)
    # Kill any legacy pet from any install location, not just this one,
    # otherwise an old startup shortcut can keep a second overlay alive.
    (
      $_.ExecutablePath -and
      $_.ExecutablePath -match '(dsh-pet-gujiguji|light-feather|mint-budgie)(-\d+\.\d+\.\d+)?\.exe$' -and
      -not $isCurrentExe
    ) -or
    ($_.CommandLine -like "*$script*")
  }
foreach ($existingPet in $existingPets) {
  Stop-Process -Id $existingPet.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 300

$dshPid = $null
if (Test-Path $dshPidFile) {
  $saved = (Get-Content $dshPidFile -Raw).Trim()
  if ($saved -match '^\d+$' -and (Get-Process -Id ([int]$saved) -ErrorAction SilentlyContinue)) {
    $dshPid = [int]$saved
  }
}
if (-not $dshPid) {
  for ($attempt = 0; $attempt -lt 20 -and -not $dshPid; $attempt++) {
    $dsh = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue |
      Where-Object { $_.MainWindowHandle -ne 0 } |
      Select-Object -First 1
    if ($dsh) { $dshPid = $dsh.Id; break }
    Start-Sleep -Milliseconds 500
  }
}
if ($dshPid) {
  Set-Content -LiteralPath $dshPidFile -Value $dshPid -Encoding ascii
}

$arguments = @(
  "--sprite", $sprite,
  "--state", $state,
  "--position", $position,
  "--settings", $settings,
  "--parent-pid", "0",
  "--anchor-pid", $(if ($dshPid) { [string]$dshPid } else { "0" })
)
if ($bundledExe) {
  $executable = $bundledExe
} else {
  $python = $null
  foreach ($candidate in @($env:DSH_PET_PYTHON, "pyw.exe", "pythonw.exe", "py.exe", "python.exe")) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($command) {
      $python = $command.Source
      break
    }
  }
  if (-not $python) { exit 2 }
  $executable = $python
  $arguments = @($script) + $arguments
}
$startedAt = Get-Date
$p = Start-Process -FilePath $executable -ArgumentList $arguments -PassThru -WindowStyle Hidden -WorkingDirectory $PSScriptRoot
if (-not $p) { exit 3 }
$deadline = (Get-Date).AddSeconds(5)
$petPid = $p.Id
while ((Get-Date) -lt $deadline) {
  $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.ProcessId -ne $p.Id -and
      $_.CreationDate -ge $startedAt.AddSeconds(-1) -and
      (
        $_.CommandLine -like "*$script*" -or
        $_.ExecutablePath -eq $bundledExe
      )
    } |
    Select-Object -First 1
  if ($running) {
    $petPid = $running.ProcessId
    break
  }
  Start-Sleep -Milliseconds 200
}
Set-Content -LiteralPath $pidFile -Value $petPid -Encoding ascii
