Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$lang = [Windows.Globalization.Language]::new('zh-Hans-CN')
Write-Output ("lang resolved: " + $lang.DisplayName)
$e1 = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
Write-Output ("TryCreateFromLanguage zh-Hans-CN -> " + ($e1 -ne $null))
$e2 = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($e2) { Write-Output ("profile engine lang: " + $e2.RecognizerLanguage.LanguageTag) }
if ($e1) { Write-Output ("engine1 lang: " + $e1.RecognizerLanguage.LanguageTag) }
