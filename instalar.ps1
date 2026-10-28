# Instalador de Pleno para Windows. En PowerShell:
#   irm https://raw.githubusercontent.com/pescamill/pleno/main/instalar.ps1 | iex
# Instala uv (que trae su propio Python), descarga Pleno en tu carpeta de usuario, crea un acceso directo y lo abre.
$ErrorActionPreference = "Stop"
$Dest = if ($env:PLENO_DIR) { $env:PLENO_DIR } else { Join-Path $HOME "Pleno" }
$ZipUrl = "https://github.com/pescamill/pleno/archive/refs/heads/main.zip"

Write-Host ""
Write-Host "  Instalando Pleno en $Dest"
Write-Host ""

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "  1/3  Instalando uv (administra Python por ti)..."
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
}
$env:Path = "$HOME\.local\bin;$env:Path"

Write-Host "  2/3  Descargando Pleno..."
$Tmp = Join-Path $env:TEMP ("pleno-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Tmp | Out-Null
Invoke-WebRequest $ZipUrl -OutFile "$Tmp\pleno.zip" -UseBasicParsing
Expand-Archive "$Tmp\pleno.zip" -DestinationPath $Tmp
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
# Keep the person's data (data\) when updating an existing install.
Get-ChildItem "$Tmp\pleno-main" | Where-Object { $_.Name -ne "data" } | Copy-Item -Destination $Dest -Recurse -Force
Remove-Item $Tmp -Recurse -Force

Write-Host "  3/3  Preparando Python y dependencias (la primera vez tarda un poco)..."
Push-Location $Dest; uv sync --quiet; Pop-Location

$Launcher = Join-Path $Dest "Abrir Pleno.bat"
@"
@echo off
set PATH=%USERPROFILE%\.local\bin;%PATH%
cd /d "$Dest"
uv run --quiet python -m pleno abrir
"@ | Set-Content -Path $Launcher -Encoding ASCII

$Shell = New-Object -ComObject WScript.Shell
$Link = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Pleno.lnk"))
$Link.TargetPath = $Launcher
$Link.WorkingDirectory = $Dest
$Link.Description = "Pleno: lo que se dice en el poder publico de Mexico"
$Link.Save()

Write-Host ""
Write-Host "  Listo. En tu Escritorio quedo 'Pleno': dale doble clic para abrirlo cuando quieras."
Write-Host "  Abriendo Pleno en tu navegador..."
Write-Host ""
& $Launcher
