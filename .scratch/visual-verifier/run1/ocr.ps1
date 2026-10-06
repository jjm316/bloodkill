param([string]$imgPath, [string]$outPath)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Foundation,ContentType=WindowsRuntime]
function Await($WinRtTask, $ResultType) {
  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}
$path = $imgPath
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$conv = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bmp, [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('zh-Hans-CN'))
if (-not $engine) { Write-Output 'NO_ENGINE_zh'; exit 1 }
$ocr = Await ($engine.RecognizeAsync($conv)) ([Windows.Media.Ocr.OcrResult])
$out = New-Object System.Collections.Generic.List[string]
foreach ($l in @($ocr.Lines)) {
  $ws = @($l.Words)
  $text = ($ws | ForEach-Object { [string]$_.Text }) -join ''
  $r = $ws[0].BoundingRect
  $x = [math]::Round([double]$r.X); $y = [math]::Round([double]$r.Y)
  $w = [math]::Round([double]$r.Width); $h = [math]::Round([double]$r.Height)
  $out.Add(("{0}|{1}|{2}|{3}|{4}" -f $x,$y,$w,$h,$text))
}
$out | Out-File -FilePath $outPath -Encoding utf8
Write-Output ("LINES=" + $out.Count + " LANG=" + $engine.RecognizerLanguage.LanguageTag)
