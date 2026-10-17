# Wpisuje klucz Sogni do .env bez pokazywania go na ekranie ani w historii.
# Uruchom: powershell -ExecutionPolicy Bypass -File set_key.ps1
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile }
$secure = Read-Host "pc6e49576-1327-480b-b3f6-d213f336403b" -AsSecureString
$key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
if (-not $key) { Write-Host "Pusty klucz, nic nie zmieniono."; exit 1 }
$lines = Get-Content $envFile | ForEach-Object {
  if ($_ -match '^SOGNI_API_KEY=') { "SOGNI_API_KEY=$key" }
  elseif ($_ -match '^PROVIDER=') { "PROVIDER=sogni" }
  else { $_ }
}
Set-Content -Path $envFile -Value $lines -Encoding utf8
Write-Host "Zapisano klucz w .env i ustawiono PROVIDER=sogni."
