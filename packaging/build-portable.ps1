param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$dist = Join-Path $root "dist"
$work = Join-Path $root "build\pyinstaller"

if (-not (Test-Path $python)) {
    throw "Project virtual environment not found: $python"
}

& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Install the build dependency first: & '$python' -m pip install -r packaging\requirements-build.txt"
}

if ($Clean) {
    foreach ($path in @((Join-Path $dist "Gesturelink"), $work)) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

$data = @(
    "$root\index.html;.",
    "$root\app.js;.",
    "$root\sign_utils.js;.",
    "$root\styles.css;.",
    "$root\collector.html;.",
    "$root\backend\gesture_model.joblib;backend",
    "$root\backend\gesture_model_metadata.json;backend",
    "$root\dataset\hand_landmarker.task;dataset",
    "$root\dataset\manifest.json;dataset",
    "$root\dataset\videos;dataset\videos",
    "$PSScriptRoot\PORTABLE_README.txt;."
)

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--console",
    "--name", "Gesturelink",
    "--distpath", $dist,
    "--workpath", $work,
    "--specpath", $work,
    "--paths", $root,
    "--hidden-import", "backend.main"
)

foreach ($item in $data) {
    $arguments += @("--add-data", $item)
}

foreach ($package in @("mediapipe", "cv2", "numpy", "sklearn", "uvicorn", "joblib")) {
    $arguments += @("--collect-all", $package)
}

$arguments += "desktop_launcher.py"

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

$output = Join-Path $dist "Gesturelink"
if (-not (Test-Path (Join-Path $output "Gesturelink.exe"))) {
    throw "Portable app was not created in $output."
}

Write-Output "Portable app created: $output"
Write-Output "Copy or zip the complete folder to share it."
