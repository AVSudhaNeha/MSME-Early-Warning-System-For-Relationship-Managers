"""
Evaluation framework config.

JUDGE_PROVIDER switches between Azure OpenAI (reuses the SAME credentials
already in app.config — AZURE_ENDPOINT/AZURE_API_KEY/AZURE_API_VERSION/
AZURE_CHAT_DEPLOYMENT, the ones app/agents/explanation_agent.py already
uses) and Anthropic (needs ANTHROPIC_API_KEY separately, since nothing
else in this project uses Anthropic's API directly). Azure is the
default specifically because it needs zero new configuration — if your
Explanation Agent already works, the judge already works.
"""

import os

JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "anthropic")  # "azure" | "anthropic"

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_JUDGE_MODEL", "claude-sonnet-4-6")

MAX_JUDGE_TOKENS = 700
TEMPERATURE = 0

# Below this overall_score (out of 5), a case is marked FAIL regardless
# of individual dimension scores — placeholder, tune once you've seen
# real judge output distributions.
PASS_THRESHOLD = 3.5

GOLDEN_DATASET_PATH = os.path.join(os.path.dirname(__file__), "golden_dataset.json")
REPORT_JSON_PATH = os.path.join(os.path.dirname(__file__), "evaluation_report.json")
REPORT_MD_PATH = os.path.join(os.path.dirname(__file__), "evaluation_report.md")

# Plain .txt mirror of the report — no JSON/Markdown extension, no
# viewer/extension involved, just readable text. Exists specifically
# so results are always reachable even if a JSON/Markdown preview
# tab in an editor is being unreliable about reloading from disk.
REPORT_TXT_PATH = os.path.join(os.path.dirname(__file__), "evaluation_report.txt")