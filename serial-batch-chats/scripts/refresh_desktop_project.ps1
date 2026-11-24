[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectName,
    [Parameter(Mandatory=$true)][string]$ChatTitle
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$element = [System.Windows.Automation.AutomationElement]
$scope = [System.Windows.Automation.TreeScope]::Descendants
$projectFilter = [System.Windows.Automation.PropertyCondition]::new($element::NameProperty, $ProjectName)
$titleFilter = [System.Windows.Automation.PropertyCondition]::new($element::NameProperty, $ChatTitle)
$windows = @(Get-Process -Name Codex,ChatGPT -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
    ForEach-Object { $element::FromHandle($_.MainWindowHandle) })

function Get-ProjectGroup {
    $groups = @($windows | ForEach-Object { $_.FindAll($scope, $projectFilter) } |
        Where-Object { $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Group -and
            $_.Current.ClassName -like 'group/cwd *' })
    if ($groups.Count -ne 1) { throw 'Target Codex sidebar project is not unique or not available.' }
    return $groups[0]
}

function Get-ProjectToggle {
    $group = Get-ProjectGroup
    $buttons = @($group.FindAll($scope, $projectFilter) |
        Where-Object { $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button })
    if ($buttons.Count -ne 1) { throw 'Target project toggle is not unique or not available.' }
    return $buttons[0].GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
}

function Test-ChatTitle {
    $group = Get-ProjectGroup
    return ($group.FindAll($scope, $titleFilter).Count -gt 0)
}

if (-not (Test-ChatTitle)) {
    $toggle = Get-ProjectToggle
    if ($toggle.Current.ExpandCollapseState -eq [System.Windows.Automation.ExpandCollapseState]::Expanded) {
        $toggle.Collapse()
        Start-Sleep -Milliseconds 500
        $toggle = Get-ProjectToggle
    }
    if ($toggle.Current.ExpandCollapseState -eq [System.Windows.Automation.ExpandCollapseState]::Collapsed) {
        $toggle.Expand()
    }
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-ChatTitle) { break }
    }
}

if (-not (Test-ChatTitle)) { throw 'The chat title was not found under the target Codex sidebar project.' }
'SIDEBAR_TITLE_VISIBLE'
