param([switch]$Watch, [switch]$LaunchGame, [string]$GamePath = '', [switch]$SkipCatalogUpdate)
$ErrorActionPreference = 'Stop'
$addonRoot = $PSScriptRoot
$sourceRoot = Join-Path $addonRoot 'Sounds'
$cacheRoot = Join-Path $addonRoot 'Media\Cache'
$catalogPath = Join-Path $addonRoot 'Catalog.lua'
$script:fileCache = @{}
$script:signature = ''
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Lua-Quote([string]$Value) {
    $Value = $Value.Replace('\', '\\').Replace('"', '\"')
    $Value = $Value.Replace("`r", '\r').Replace("`n", '\n').Replace("`t", '\t')
    return '"' + $Value + '"'
}

function Hash-Text([string]$Value) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Audio-Duration([string]$Path, [string]$Extension) {
    try {
        $data = [IO.File]::ReadAllBytes($Path)
        if ($Extension -eq '.wav' -and $data.Length -ge 44) {
            if ([Text.Encoding]::ASCII.GetString($data, 0, 4) -ne 'RIFF') { return 3.0 }
            $rate = 0; $bytes = 0; $position = 12
            while ($position + 8 -le $data.Length) {
                $tag = [Text.Encoding]::ASCII.GetString($data, $position, 4)
                $length = [BitConverter]::ToUInt32($data, $position + 4)
                if ($tag -eq 'fmt ' -and $length -ge 16 -and $position + 24 -le $data.Length) {
                    $rate = [BitConverter]::ToUInt32($data, $position + 16)
                }
                if ($tag -eq 'data') { $bytes = $length; break }
                $position += 8 + $length + ($length % 2)
            }
            if ($rate -gt 0 -and $bytes -gt 0) { return [double]$bytes / [double]$rate }
        }
        if ($Extension -eq '.ogg') {
            $ascii = [Text.Encoding]::ASCII.GetString($data)
            $vorbis = $ascii.IndexOf('vorbis', [StringComparison]::Ordinal)
            $page = $ascii.LastIndexOf('OggS', [StringComparison]::Ordinal)
            if ($vorbis -ge 0 -and $vorbis + 15 -le $data.Length -and $page -ge 0 -and $page + 14 -le $data.Length) {
                $rate = [BitConverter]::ToUInt32($data, $vorbis + 11)
                $samples = [BitConverter]::ToInt64($data, $page + 6)
                if ($rate -gt 0 -and $samples -gt 0) { return [double]$samples / [double]$rate }
            }
        }
        if ($Extension -eq '.mp3') {
            $position = 0
            if ($data.Length -ge 10 -and [Text.Encoding]::ASCII.GetString($data, 0, 3) -eq 'ID3') {
                $position = 10 + (($data[6] -band 127) * 2097152) + (($data[7] -band 127) * 16384) + (($data[8] -band 127) * 128) + ($data[9] -band 127)
            }
            $bitrates1 = @(0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0)
            $bitrates2 = @(0,8,16,24,32,40,48,56,64,80,96,112,128,144,160,0)
            $rates = @(44100,48000,32000); $duration = 0.0; $frames = 0
            while ($position + 4 -le $data.Length) {
                $b0=$data[$position]; $b1=$data[$position+1]; $b2=$data[$position+2]
                $version=($b1 -shr 3) -band 3; $layer=($b1 -shr 1) -band 3
                $bitrateIndex=($b2 -shr 4) -band 15; $sampleIndex=($b2 -shr 2) -band 3
                if ($b0 -ne 255 -or ($b1 -band 224) -ne 224 -or $version -eq 1 -or $layer -ne 1 -or $sampleIndex -eq 3 -or $bitrateIndex -eq 0 -or $bitrateIndex -eq 15) {
                    $position++; continue
                }
                $rate = [double]$rates[$sampleIndex]
                if ($version -eq 2) { $rate /= 2 }
                elseif ($version -eq 0) { $rate /= 4 }
                $bitrate = $bitrates2[$bitrateIndex]; $factor = 72000; $samples = 576
                if ($version -eq 3) { $bitrate=$bitrates1[$bitrateIndex]; $factor=144000; $samples=1152 }
                $frameSize = [int][math]::Floor($factor * $bitrate / $rate) + (($b2 -shr 1) -band 1)
                if ($frameSize -lt 4 -or $position + $frameSize -gt $data.Length) { break }
                $duration += $samples / $rate; $frames++; $position += $frameSize
            }
            if ($frames -gt 0) { return $duration }
        }
    } catch { }
    return 3.0
}

function Update-Catalog {
    [IO.Directory]::CreateDirectory($sourceRoot) | Out-Null
    [IO.Directory]::CreateDirectory($cacheRoot) | Out-Null
    $names = @{ 'cat.wav' = 'Киси-киси, мяу-мяу'; 'dog.wav' = 'Песик-песик, ав-ав-ав' }
    $nameFile = Join-Path $addonRoot 'SoundNames.json'
    if (Test-Path -LiteralPath $nameFile) {
        try {
            $json = Get-Content -LiteralPath $nameFile -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($property in $json.PSObject.Properties) { $names[$property.Name.ToLowerInvariant()] = [string]$property.Value }
        } catch { Write-Warning 'SoundNames.json could not be read; file names are used.' }
    }
    $items = New-Object 'System.Collections.Generic.List[object]'
    $present = @{}; $cached = @{}; $titleSet = New-Object 'System.Collections.Generic.HashSet[string]'
    $files = @(Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | Where-Object { @('.wav','.mp3','.ogg') -contains $_.Extension.ToLowerInvariant() } | Sort-Object FullName)
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart([char[]]'\/').Replace('\','/')
        $key = $relative.ToLowerInvariant()
        $extension = $file.Extension.ToLowerInvariant()
        $id = 's_' + (Hash-Text $relative).Substring(0,16)
        $cacheFile = $id + $extension
        $stamp = [string]$file.Length + ':' + [string]$file.LastWriteTimeUtc.Ticks
        $entry = $script:fileCache[$key]
        if (-not $entry -or $entry.stamp -ne $stamp -or -not (Test-Path -LiteralPath (Join-Path $cacheRoot $cacheFile))) {
            try {
                $digest = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant().Substring(0,16)
                $duration = Audio-Duration $file.FullName $extension
                [IO.File]::Copy($file.FullName, (Join-Path $cacheRoot $cacheFile), $true)
                $entry = @{stamp=$stamp; digest=$digest; duration=$duration}
            } catch {
                if (-not $entry -or -not (Test-Path -LiteralPath (Join-Path $cacheRoot $cacheFile))) {
                    Write-Warning ('Could not read audio file: ' + $relative); continue
                }
                Write-Warning ('Audio file is busy; previous copy retained: ' + $relative)
            }
        }
        $title = $file.BaseName.Replace('_',' ')
        if ($names.ContainsKey($key)) { $title = $names[$key] }
        $title = [regex]::Replace($title, '[\x00-\x1f\x7f|]', '').Trim()
        if (-not $title) { $title = $file.BaseName }
        if (-not $titleSet.Add($title)) { $title = $title + ' [' + $relative + ']'; $titleSet.Add($title) | Out-Null }
        $items.Add(@{id=$id; title=$title; filename=$relative; file='Cache/' + $cacheFile; digest=$entry.digest; duration=$entry.duration})
        $present[$key]=$entry; $cached[$cacheFile]=$true
    }
    $script:fileCache = $present
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $lines.Add('-- Generated by SoundCatalog.ps1. Edit the Sounds folder, not this file.')
    $lines.Add('SirusChatWheelSoundCatalog = { schema = 1, items = {')
    foreach ($item in ($items | Sort-Object title,filename)) {
        $duration = ([double]$item.duration).ToString('0.00000', [Globalization.CultureInfo]::InvariantCulture)
        $lines.Add('  { id = ' + (Lua-Quote $item.id) + ', title = ' + (Lua-Quote $item.title) + ', filename = ' + (Lua-Quote $item.filename) + ', file = ' + (Lua-Quote $item.file) + ', digest = ' + (Lua-Quote $item.digest) + ', duration = ' + $duration + ' },')
    }
    $lines.Add('} }')
    $content = [string]::Join("`n", $lines) + "`n"
    $signature = Hash-Text $content
    if ($signature -ne $script:signature) {
        $temporary = $catalogPath + '.tmp'
        [IO.File]::WriteAllText($temporary, $content, $utf8)
        if (Test-Path -LiteralPath $catalogPath) { [IO.File]::Replace($temporary, $catalogPath, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $catalogPath) }
        $script:signature = $signature
        Write-Host ('Sound catalog updated: ' + $items.Count + ' files. Use /reload in game after changing sounds.')
    }
    foreach ($cache in @(Get-ChildItem -LiteralPath $cacheRoot -File)) {
        if ($cache.Name -match '^s_[0-9a-f]{16}\.(wav|mp3|ogg)$' -and -not $cached.ContainsKey($cache.Name)) {
            try { [IO.File]::Delete($cache.FullName) } catch { }
        }
    }
}

try {
    if (-not $SkipCatalogUpdate) { Update-Catalog }
    elseif (-not (Test-Path -LiteralPath $catalogPath)) { throw 'The release catalog is missing. Extract the complete addon ZIP.' }
    $gameProcess = $null
    if ($LaunchGame) {
        if (-not $GamePath) {
            $gameRoot = Split-Path (Split-Path (Split-Path $addonRoot -Parent) -Parent) -Parent
            $GamePath = Join-Path $gameRoot 'WoW.exe'
        }
        if (-not (Test-Path -LiteralPath $GamePath)) { throw 'WoW.exe was not found. Install SirusChatWheel directly in Interface\AddOns, or run Update-Sounds.cmd before starting the game.' }
        $gameProcess = Start-Process -FilePath $GamePath -WorkingDirectory (Split-Path $GamePath -Parent) -PassThru
    }
    if ($Watch) {
        Write-Host 'Watching the Sounds folder. Keep this window open; Ctrl+C stops watching.'
        while ($true) {
            Start-Sleep -Milliseconds 1000
            if ($gameProcess -and $gameProcess.HasExited) { break }
            try { Update-Catalog } catch { Write-Warning $_.Exception.Message }
        }
    }
} catch { Write-Error $_.Exception.Message; exit 1 }
