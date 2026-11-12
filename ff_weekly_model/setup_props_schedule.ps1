# Creates the two Windows scheduled tasks that snapshot player props (fetch_props.py).
#   FF props - early pull     Thursday 10:00 AM: every game this week (skips itself if free-key credits are short)
#   FF props - pregame pulls  every 30 min, 8 AM - 11 PM daily: games kicking off within 75 min that haven't
#                             had a pregame pull yet (listing games is free, so idle runs cost nothing)
# Run once:  powershell -ExecutionPolicy Bypass -File setup_props_schedule.ps1
# Remove:    Unregister-ScheduledTask -TaskName "FF props*" -Confirm:$false
# Every run appends a line to data\props\pull_log.txt. The PC must be on (a missed run starts when it wakes).
$py = "C:\Users\jbond\AppData\Local\Programs\Python\Python313\pythonw.exe"
$wd = $PSScriptRoot
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$a1 = New-ScheduledTaskAction -Execute $py -Argument "fetch_props.py --mode early" -WorkingDirectory $wd
$t1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At 10:00AM
Register-ScheduledTask -TaskName "FF props - early pull" -Action $a1 -Trigger $t1 -Settings $set -Force `
    -Description "Thursday-morning player-prop snapshot for ff_weekly_model" | Out-Null

$a2 = New-ScheduledTaskAction -Execute $py -Argument "fetch_props.py --mode pregame --within 75" -WorkingDirectory $wd
$t2 = New-ScheduledTaskTrigger -Daily -At 8:00AM
$t2.Repetition = (New-ScheduledTaskTrigger -Once -At 8:00AM -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 15)).Repetition
Register-ScheduledTask -TaskName "FF props - pregame pulls" -Action $a2 -Trigger $t2 -Settings $set -Force `
    -Description "Pulls props for games kicking off within 75 min" | Out-Null

Get-ScheduledTask -TaskName "FF props*" | ForEach-Object {
    "{0}  next run {1}" -f $_.TaskName, ($_ | Get-ScheduledTaskInfo).NextRunTime }
