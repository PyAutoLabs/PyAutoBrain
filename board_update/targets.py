"""Refresh-only allowlist, matching the owner contract in board-orchestration.md."""

WORKFLOWS = {
    "PyAutoBrain": "brain_board.yml",
    "PyAutoMind": "dashboard_refresh.yml",
    "PyAutoCortex": "dashboard_refresh.yml",
    "PyAutoEars": "pages.yml",
    "PyAutoHeart": "heart-health.yml",
    "PyAutoHands": "release_board.yml",
    "PyAutoMemory": "knowledge_board.yml",
    "PyAutoPulse": "dashboard_refresh.yml",
    "PyAutoInsight": "dashboard_refresh.yml",
    "PyAutoNerves": "nerves_board.yml",
    "PyAutoGut": "gut_board.yml",
    "PyAutoEyes": "dashboard_refresh.yml",
    "PyAutoScientist": "organism_board.yml",
}


def workflow_url(repo):
    return f"https://github.com/PyAutoLabs/{repo}/actions/workflows/{WORKFLOWS[repo]}"


def target_for_url(url):
    return next((repo for repo in WORKFLOWS if workflow_url(repo) == url), None)
