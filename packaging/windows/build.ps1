$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on Windows; PyInstaller is not a cross-compiler.' }

$Vendor = Join-Path $Root 'vendor/ffmpeg/bin'
$Ffmpeg = Join-Path $Vendor 'ffmpeg.exe'
$Ffprobe = Join-Path $Vendor 'ffprobe.exe'
$RequiredNotices = @(
    'vendor/ffmpeg/LICENSES',
    'vendor/ffmpeg/THIRD_PARTY_NOTICES.txt',
    'vendor/ffmpeg/SOURCE_CODE_OR_OFFER.txt',
    'vendor/ffmpeg/BUILDINFO.md',
    'vendor/ffmpeg/SHA256SUMS.txt'
)
foreach ($Path in @($Ffmpeg, $Ffprobe)) {
    if (-not (Test-Path $Path -PathType Leaf)) { throw "Missing required binary: $Path" }
}
foreach ($Relative in $RequiredNotices) {
    if (-not (Test-Path (Join-Path $Root $Relative))) { throw "Missing FFmpeg compliance file: $Relative" }
    $NoticeItem = Get-Item (Join-Path $Root $Relative)
    if (-not $NoticeItem.PSIsContainer -and $NoticeItem.Length -eq 0) {
        throw "FFmpeg compliance file is empty: $Relative"
    }
}
if (-not (Get-ChildItem (Join-Path $Root 'vendor/ffmpeg/LICENSES') -Recurse -File)) {
    throw 'FFmpeg LICENSES folder must contain the actual license texts for this build and its bundled libraries.'
}
$BuildInfo = Get-Content (Join-Path $Root 'vendor/ffmpeg/BUILDINFO.md') -Raw
foreach ($Field in @('Source URL:', 'Version:', 'Configure flags:')) {
    if ($BuildInfo -notmatch [regex]::Escape($Field)) { throw "BUILDINFO.md must document '$Field'." }
}
$HashMap = @{}
foreach ($Line in Get-Content (Join-Path $Root 'vendor/ffmpeg/SHA256SUMS.txt')) {
    if ($Line -match '^([A-Fa-f0-9]{64})\s+\*?(.+)$') { $HashMap[$Matches[2].Replace('/', '\')] = $Matches[1].ToLowerInvariant() }
    elseif ($Line.Trim()) { throw "Invalid SHA256SUMS.txt line: $Line" }
}
$VendorFiles = @(Get-ChildItem $Vendor -File | ForEach-Object { "bin\$($_.Name)" } | Sort-Object)
$ManifestFiles = @($HashMap.Keys | Sort-Object)
if (Compare-Object $VendorFiles $ManifestFiles) {
    throw 'SHA256SUMS.txt must list every file in vendor/ffmpeg/bin and no other files.'
}
foreach ($RelativeFile in $VendorFiles) {
    $Actual = (Get-FileHash (Join-Path $Root (Join-Path 'vendor/ffmpeg' $RelativeFile)) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $HashMap[$RelativeFile]) { throw "FFmpeg vendor checksum mismatch: $RelativeFile" }
}
$Encoders = (& $Ffmpeg -hide_banner -encoders 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $Encoders -notmatch '\blibx264\b') { throw 'Bundled FFmpeg must run and expose libx264.' }
& $Ffprobe -version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Bundled ffprobe did not run.' }

$Python = Get-Command python -ErrorAction Stop
$PythonInfo = & $Python.Source -c 'import struct,sys; print(f"{sys.version_info.major}.{sys.version_info.minor}|{sys.platform}|{struct.calcsize(chr(80))*8}")'
if ($LASTEXITCODE -ne 0 -or $PythonInfo -ne '3.13|win32|64') { throw 'Use 64-bit Python 3.13 from python.org, with Tcl/Tk installed.' }
$Venv = Join-Path $Root '.build-venv'
& $Python.Source -m venv --clear $Venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create a clean build venv.' }
$VenvPython = Join-Path $Venv 'Scripts/python.exe'
$Wheelhouse = Join-Path $Root 'build/wheelhouse'
New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null
& $VenvPython -m pip download --no-deps --only-binary=:all: --dest $Wheelhouse 'WannaCRI==0.3.3'
if ($LASTEXITCODE -ne 0) { throw 'Could not download the pinned WannaCRI wheel from PyPI.' }
$WannaCriWheel = Join-Path $Wheelhouse 'wannacri-0.3.3-py3-none-any.whl'
if (-not (Test-Path $WannaCriWheel -PathType Leaf)) { throw 'Expected WannaCRI 0.3.3 wheel was not downloaded.' }
$WannaCriHash = (Get-FileHash $WannaCriWheel -Algorithm SHA256).Hash.ToLowerInvariant()
$ExpectedWannaCriHash = '3d96b35c9a76632d2e773eeb2372810e854d9d77b381f81dc348d92f9aacde5c'
if ($WannaCriHash -ne $ExpectedWannaCriHash) { throw 'WannaCRI wheel SHA-256 does not match the hash published by PyPI.' }
& $VenvPython -m pip install $WannaCriWheel
if ($LASTEXITCODE -ne 0) { throw 'Could not install the verified WannaCRI wheel.' }
& $VenvPython -m pip install -r (Join-Path $Root 'requirements-windows-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $VenvPython -m unittest discover -s (Join-Path $Root 'tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Project test suite failed.' }
& $VenvPython (Join-Path $Root 'tools/collect_python_licenses.py') `
    --license-dir (Join-Path $Root 'build/python-licenses') `
    --manifest (Join-Path $Root 'build/python-third-party.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not collect Python third-party license texts.' }
& $VenvPython -m PyInstaller --clean --noconfirm (Join-Path $PSScriptRoot 'DivaUSMConverter.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
$App = Join-Path $Root 'dist/DIVA-USM-Converter'
& (Join-Path $App 'DIVA-USM-Converter.exe') --self-test
if ($LASTEXITCODE -ne 0) { throw 'Packaged application self-test failed.' }
& (Join-Path $App 'DIVA-USM-Converter.exe') --gui-smoke-test
if ($LASTEXITCODE -ne 0) { throw 'Packaged GUI smoke test failed.' }
$Zip = Join-Path $Root 'dist/DIVA-USM-Converter-Windows.zip'
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $App '*') -DestinationPath $Zip
Write-Host "Built package: $Zip"
