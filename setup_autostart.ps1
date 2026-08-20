# Run this script ONCE as Administrator to register the auto-start task.
# Right-click this file → "Run with PowerShell" (as Administrator)

$TaskName   = "AIStockTradingBot"
$ScriptPath = "E:\Ai Stock\start_trading_bot.bat"

# Remove old task if it exists
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Trigger 1: On system startup / login
$TriggerLogin = New-ScheduledTaskTrigger -AtLogOn

# Trigger 2: When laptop wakes from sleep
$TriggerWake = New-CimInstance -Namespace ROOT\Microsoft\Windows\TaskScheduler `
    -ClassName MSFT_TaskEventTrigger `
    -ClientOnly `
    -Property @{
        Enabled       = $true
        Subscription  = '<QueryList><Query Id="0"><Select Path="System">*[System[Provider[@Name="Microsoft-Windows-Power-Troubleshooter"] and EventID=1]]</Select></Query></QueryList>'
    }

$Action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$ScriptPath`""
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 24) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Trigger $TriggerLogin `
    -Action $Action `
    -Settings $Settings `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "✅ Task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host "   The trading bot will now auto-start whenever you log in or wake from sleep." -ForegroundColor Cyan
Write-Host ""
Write-Host "To remove it later, run:" -ForegroundColor Yellow
Write-Host "   Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Yellow
