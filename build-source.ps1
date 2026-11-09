param(
    [string]$PythonExe = 'python',
    [ValidateSet('Portable', 'SingleFile', 'Both')]
    [string]$Format = 'Portable',
    [switch]$RebuildAnimation,
    [string]$AnimationSdk = ''
)
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$previousMode = $env:VERTEXVIEWER_ONEFILE
Push-Location -LiteralPath $sourceRoot
try {
    if ($RebuildAnimation) {
        if (-not $AnimationSdk) {
            $AnimationSdk = Join-Path $sourceRoot 'tools\animation_bridge\sdk'
            if (-not (Test-Path -LiteralPath $AnimationSdk)) {
                $AnimationSdk = Join-Path $sourceRoot 'work\animation-hands-sdk'
            }
        }
        $AnimationSdk = (Resolve-Path -LiteralPath $AnimationSdk).Path
        $sdkManifest = Get-Content -LiteralPath 'tools\animation_bridge\sdk-manifest.json' -Raw | ConvertFrom-Json
        foreach ($entry in $sdkManifest.source.PSObject.Properties) {
            $actual = (Get-FileHash -LiteralPath (Join-Path $AnimationSdk $entry.Name) -Algorithm SHA256).Hash
            if ($actual -ne $entry.Value) { throw "Animation SDK differs: $($entry.Name)" }
        }
        $publishDir = Join-Path $sourceRoot 'build\animation-publish'
        & dotnet publish tools\animation_bridge\VertexViewer.AnimationBridge.csproj -c Release -r win-x64 --self-contained true "-p:SdkDirectory=$AnimationSdk" -o $publishDir
        if ($LASTEXITCODE -ne 0) { throw 'Animation bridge build failed.' }
        Get-ChildItem -LiteralPath $publishDir -Force | Copy-Item -Destination (Join-Path $sourceRoot 'assets\animation') -Recurse -Force
    }
    foreach ($asset in @('assets\animation\VertexViewer.AnimationBridge.exe', 'assets\animation\CUE4Parse-Natives.dll', 'assets\audio\OPEN_0.wav', 'core\part_offsets.json', 'work\mesh_catalog.json', 'work\names.json', 'work\icons.db')) {
        if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) { throw "Missing source asset: $asset" }
    }
    & $PythonExe -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed.' }
    $env:VERTEXVIEWER_ONEFILE = switch ($Format) {
        'SingleFile' { '1' }
        'Both' { 'both' }
        default { '' }
    }
    & $PythonExe -m PyInstaller --noconfirm VertexViewer.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    Write-Host (Join-Path $sourceRoot 'dist')
} finally {
    $env:VERTEXVIEWER_ONEFILE = $previousMode
    Pop-Location
}
