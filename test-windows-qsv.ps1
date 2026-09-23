$ErrorActionPreference = "Continue"
Write-Host "Testing native Windows Intel Quick Sync..." -ForegroundColor Cyan
ffmpeg -hide_banner -y -init_hw_device qsv=hw,child_device_type=d3d11va -f lavfi -i "testsrc2=size=1280x720:rate=30" -t 5 -c:v h264_qsv -global_quality 23 qsv-native-test.mp4
if ($LASTEXITCODE -eq 0) {
    Write-Host "QSV encode succeeded: qsv-native-test.mp4" -ForegroundColor Green
} else {
    Write-Host "QSV encode failed. Update the Intel graphics driver and confirm the Intel UHD GPU is enabled." -ForegroundColor Red
}
