param(
  [int]$Port = 8000
)

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$bundledPython = "C:\Users\Lenovo Ideapad\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path $bundledPython) {
  $python = $bundledPython
} else {
  $python = "python"
}

Set-Location $workspaceRoot
& $python -m backend.serve_local --host 127.0.0.1 --port $Port
