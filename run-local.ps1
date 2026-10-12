$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python --version
python .\local_collector.py
