Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Foundation,ContentType=WindowsRuntime]
$lang = [Windows.Globalization.Language]::new('zh-Hans-CN')
Write-Output ("lang resolved: " + $lang.DisplayName)
$e1 = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($e1) { Write-Output ("engine1 lang: " + $e1.RecognizerLanguage.LanguageTag) } else { Write-Output 'engine1 NULL' }
