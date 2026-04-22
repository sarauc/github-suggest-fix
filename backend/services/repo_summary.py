"""
AI-generated codebase summary.

Generated once at index time by calling Claude over the repo tree and README.
Stored per repo under ~/.gh-ai-assistant/summaries/.
Injected into every /analyze prompt as a short orientation block.
"""

import logging
from pathlib import Path
from typing import List

import anthropic

import config

logger = logging.getLogger(__name__)

SUMMARIES_DIR = config.BASE_DIR / "summaries"


def _summary_path(repo: str) -> Path:
    safe = repo.replace("/", "__")
    return SUMMARIES_DIR / f"{safe}.txt"


def load_summary(repo: str) -> str:
    """Return the stored summary for a repo, or empty string if not yet generated."""
    path = _summary_path(repo)
    if not path.exists():
        return ""
    return path.read_text()


def save_summary(repo: str, text: str) -> None:
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    _summary_path(repo).write_text(text)


async def generate_summary(
    repo: str,
    tree_paths: List[str],
    readme: str,
    anthropic_key: str,
) -> str:
    """Call Claude to produce a 150-200 word orientation summary of the repo."""
    # Cap tree to 500 paths to stay within token budget
    tree_text = "\n".join(tree_paths[:500])
    readme_section = readme[:6000] if readme else "(no README found)"

    prompt = f"""You are analyzing a code repository to produce a brief orientation summary for a code-review assistant.

Repository: {repo}

File tree (up to 500 paths):
{tree_text}

README:
{readme_section}

Write a concise summary (150–200 words) covering:
1. What this project does
2. Primary language(s) and framework(s)
3. Key directories and their roles
4. Any notable conventions or patterns visible from the structure

Be factual and specific. Do not speculate beyond what the files show. Do not repeat the repository name."""

    client = anthropic.AsyncAnthropic(api_key=anthropic_key)
    message = await client.messages.create(
        model=config.DEFAULT_MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    summary = message.content[0].text
    logger.info(f'"action": "summary_generated", "repo": "{repo}", "chars": {len(summary)}')
    return summary
