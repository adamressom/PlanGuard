param(
    [string]$IssueFile = ".\planguard-issues.json",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. Install GitHub CLI, then run: gh auth login"
    }
}

Require-Command "gh"

if (-not (Test-Path $IssueFile)) {
    throw "Issue file not found: $IssueFile"
}

gh auth status | Out-Null
$repo = gh repo view --json nameWithOwner --jq ".nameWithOwner"
if (-not $repo) {
    throw "Could not determine the GitHub repository. Run this script from inside the cloned repository."
}

Write-Host "Repository: $repo"
$data = Get-Content -Raw -Encoding UTF8 $IssueFile | ConvertFrom-Json

Write-Host "`nCreating labels..."
foreach ($label in $data.labels) {
    $args = @(
        "label", "create", $label.name,
        "--description", $label.description,
        "--force",
        "--repo", $repo
    )

    if ($DryRun) {
        Write-Host "DRY RUN: gh $($args -join ' ')"
    }
    else {
        & gh @args | Out-Null
        Write-Host "  Ready: $($label.name)"
    }
}

Write-Host "`nLoading existing milestones..."
$existingMilestones = @{}
$milestoneJson = gh api "repos/$repo/milestones?state=all&per_page=100"
if ($milestoneJson) {
    foreach ($item in ($milestoneJson | ConvertFrom-Json)) {
        $existingMilestones[$item.title] = $item.number
    }
}

Write-Host "`nCreating milestones..."
foreach ($milestone in $data.milestones) {
    if ($existingMilestones.ContainsKey($milestone.title)) {
        Write-Host "  Exists: $($milestone.title)"
        continue
    }

    if ($DryRun) {
        Write-Host "DRY RUN: create milestone '$($milestone.title)'"
        continue
    }

    $createdJson = gh api `
        --method POST `
        "repos/$repo/milestones" `
        -f "title=$($milestone.title)"

    $created = $createdJson | ConvertFrom-Json
    $existingMilestones[$created.title] = $created.number
    Write-Host "  Created: $($created.title)"
}

Write-Host "`nLoading existing issue titles..."
$existingIssueTitles = @{}
$issueLines = gh issue list --repo $repo --state all --limit 1000 --json title --jq ".[].title"
foreach ($title in $issueLines) {
    $existingIssueTitles[$title] = $true
}

Write-Host "`nCreating issues..."
$createdCount = 0
$skippedCount = 0

foreach ($issue in $data.issues) {
    if ($existingIssueTitles.ContainsKey($issue.title)) {
        Write-Host "  Skipped existing: $($issue.title)"
        $skippedCount++
        continue
    }

    $tempBody = New-TemporaryFile
    try {
        Set-Content -Path $tempBody.FullName -Value $issue.body -Encoding UTF8

        $args = @(
            "issue", "create",
            "--repo", $repo,
            "--title", $issue.title,
            "--body-file", $tempBody.FullName
        )

        foreach ($labelName in $issue.labels) {
            $args += @("--label", $labelName)
        }

        if ($issue.milestone) {
            $args += @("--milestone", $issue.milestone)
        }

        if ($DryRun) {
            Write-Host "DRY RUN: create issue '$($issue.title)'"
        }
        else {
            $url = & gh @args
            Write-Host "  Created: $($issue.title)"
            Write-Host "           $url"
            $createdCount++
        }
    }
    finally {
        Remove-Item $tempBody.FullName -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "`nFinished."
Write-Host "Created: $createdCount"
Write-Host "Skipped: $skippedCount"
if ($DryRun) {
    Write-Host "No GitHub changes were made because -DryRun was used."
}
