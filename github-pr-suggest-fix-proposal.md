# GitHub PR Auto Suggest Fix — Project Proposal

## Overview

Build an AI-powered GitHub App that listens to pull request review comments and automatically generates code fix suggestions, posted back as GitHub native suggestion blocks. This bridges the gap between a reviewer identifying an issue and a developer knowing how to fix it.

---

## Goals

- Automatically detect when a PR review comment describes a code problem
- Fetch the relevant code context around the comment
- Use an LLM (Claude) to generate a concrete code fix
- Post the fix back as a GitHub native suggestion (` ```suggestion ``` ` block) that the author can apply with one click
- Be reviewer-agnostic: works regardless of who leaves the comment

---

## Architecture

### High-Level Flow

```
PR review comment created / edited
            ↓
GitHub Webhook → GitHub App Server (Express / FastAPI)
            ↓
Verify webhook signature (HMAC-SHA256)
            ↓
Fetch PR diff + file content via GitHub API
            ↓
Build LLM prompt (comment + code context)
            ↓
Call Claude API → parse suggested code block
            ↓
Post suggestion comment back to PR via GitHub API
```

### Components

| Component | Responsibility |
|---|---|
| **GitHub App** | Webhook receiver, authentication (JWT + installation tokens) |
| **Webhook Handler** | Route events, filter relevant comment types |
| **Context Fetcher** | Pull file content and diff from GitHub API |
| **LLM Service** | Format prompt, call Claude API, parse response |
| **Comment Poster** | Format as GitHub suggestion block and post reply |
| **Config Layer** | Per-repo opt-in/out, trigger keyword config |

---

## Phase 1: GitHub Action MVP (Validation)

Start with a GitHub Action to validate the concept before building full infrastructure.

### Trigger

```yaml
on:
  pull_request_review_comment:
    types: [created]
```

### Action Steps

1. Check if comment contains a trigger keyword (e.g., `/suggest-fix`, or bot is @mentioned)
2. Extract the file path and line number from the comment context
3. Fetch the file content at that line range
4. Call Claude API with the comment + code context
5. Post a reply with a `suggestion` code block

### File: `.github/workflows/suggest-fix.yml`

```yaml
name: AI Suggest Fix

on:
  pull_request_review_comment:
    types: [created]

permissions:
  pull-requests: write

jobs:
  suggest-fix:
    runs-on: ubuntu-latest
    if: contains(github.event.comment.body, '/suggest-fix')
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}

      - name: Run suggest-fix script
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          COMMENT_BODY: ${{ github.event.comment.body }}
          FILE_PATH: ${{ github.event.comment.path }}
          LINE: ${{ github.event.comment.line }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          REPO: ${{ github.repository }}
        run: |
          pip install anthropic requests
          python scripts/suggest_fix.py
```

### File: `scripts/suggest_fix.py`

```python
import os
import anthropic
import requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
COMMENT_BODY = os.environ["COMMENT_BODY"]
FILE_PATH = os.environ["FILE_PATH"]
LINE = int(os.environ["LINE"])
PR_NUMBER = os.environ["PR_NUMBER"]
REPO = os.environ["REPO"]

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

def fetch_file_context(file_path: str, target_line: int, window: int = 15) -> str:
    url = f"https://api.github.com/repos/{REPO}/contents/{file_path}"
    resp = requests.get(url, headers=GITHUB_HEADERS)
    resp.raise_for_status()
    import base64
    content = base64.b64decode(resp.json()["content"]).decode("utf-8")
    lines = content.splitlines()
    start = max(0, target_line - window - 1)
    end = min(len(lines), target_line + window)
    numbered = [f"{i+1}: {line}" for i, line in enumerate(lines[start:end], start=start)]
    return "\n".join(numbered), target_line - start

def generate_suggestion(comment: str, code_context: str, file_path: str, target_line_offset: int) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""You are a code reviewer assistant. A reviewer left the following comment on a pull request:

REVIEWER COMMENT:
{comment}

FILE: {file_path}
CODE CONTEXT (line numbers shown):
{code_context}

The reviewer's comment refers to approximately line {target_line_offset + 1} in the shown context.

Your task:
1. Understand what the reviewer is asking to fix
2. Generate ONLY the corrected line(s) of code as a GitHub suggestion block
3. The suggestion should be minimal — only change what's needed
4. Do not include explanation in the suggestion block itself

Respond in this exact format:
```suggestion
<corrected code here>
```

Then on a new line, add a brief one-sentence explanation of what was changed."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def post_reply(comment_id: str, body: str):
    # Get original comment to find PR review ID
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/comments"
    resp = requests.post(url, headers=GITHUB_HEADERS, json={
        "body": body,
        "in_reply_to": int(comment_id),
    })
    resp.raise_for_status()

if __name__ == "__main__":
    comment_id = os.environ.get("COMMENT_ID")
    code_context, offset = fetch_file_context(FILE_PATH, LINE)
    suggestion = generate_suggestion(COMMENT_BODY, code_context, FILE_PATH, offset)
    post_reply(comment_id, f"🤖 **AI Suggested Fix:**\n\n{suggestion}")
```

---

## Phase 2: GitHub App (Production)

### Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Runtime | Node.js (TypeScript) | Best GitHub App ecosystem (Octokit, Probot) |
| Framework | Fastify or Express | Lightweight webhook server |
| GitHub SDK | `@octokit/app` | Handles JWT + installation token auth |
| LLM | Anthropic Claude API | Best at code understanding and generation |
| Hosting | Railway / Fly.io / AWS Lambda | Low ops overhead |
| Queue | BullMQ (Redis) | Async processing, retry logic |

### Project Structure

```
github-suggest-fix/
├── src/
│   ├── app.ts                  # Express/Fastify app, webhook routes
│   ├── github/
│   │   ├── auth.ts             # JWT + installation token management
│   │   ├── context.ts          # Fetch file content, diff, PR metadata
│   │   └── poster.ts           # Post suggestion comments
│   ├── llm/
│   │   ├── prompt.ts           # Prompt construction
│   │   ├── client.ts           # Anthropic API wrapper
│   │   └── parser.ts           # Extract suggestion blocks from response
│   ├── handlers/
│   │   └── reviewComment.ts    # Main event handler
│   ├── queue/
│   │   └── worker.ts           # BullMQ worker for async processing
│   └── config.ts               # Env vars, feature flags
├── tests/
├── .github/
│   └── workflows/
├── Dockerfile
└── README.md
```

### Webhook Events to Handle

| Event | Action | Description |
|---|---|---|
| `pull_request_review_comment` | `created` | New inline review comment |
| `issue_comment` | `created` | Comment on PR (non-inline) |
| `pull_request_review_comment` | `edited` | Reviewer updated their comment |

### GitHub App Registration

1. Go to `GitHub Settings → Developer Settings → GitHub Apps → New GitHub App`
2. Set webhook URL to your server endpoint
3. Required **Repository Permissions**:
   - `Pull requests`: Read & Write (to post comments)
   - `Contents`: Read (to fetch file content)
4. Subscribe to events: `Pull request review comment`, `Issue comment`
5. Store: `App ID`, `Private Key`, `Webhook Secret`

### Authentication Flow

```typescript
import { App } from "@octokit/app";

const app = new App({
  appId: process.env.GITHUB_APP_ID,
  privateKey: process.env.GITHUB_PRIVATE_KEY,
  webhooks: { secret: process.env.GITHUB_WEBHOOK_SECRET },
});

// Get installation-scoped Octokit for API calls
const octokit = await app.getInstallationOctokit(installationId);
```

### Context Fetching Strategy

```typescript
async function fetchCodeContext(
  octokit: Octokit,
  owner: string,
  repo: string,
  filePath: string,
  targetLine: number,
  ref: string,
  windowLines: number = 20
): Promise<CodeContext> {
  // Fetch file content at PR head commit
  const { data } = await octokit.rest.repos.getContent({
    owner, repo, path: filePath, ref,
  });

  const content = Buffer.from(data.content, "base64").toString("utf-8");
  const lines = content.split("\n");

  const startLine = Math.max(0, targetLine - windowLines - 1);
  const endLine = Math.min(lines.length, targetLine + windowLines);

  return {
    lines: lines.slice(startLine, endLine),
    startLine: startLine + 1,
    targetLineOffset: targetLine - startLine - 1,
    filePath,
    language: detectLanguage(filePath),
  };
}
```

### LLM Prompt Design

```typescript
function buildPrompt(context: CodeContext, reviewComment: string): string {
  const numberedLines = context.lines
    .map((line, i) => `${context.startLine + i}: ${line}`)
    .join("\n");

  return `You are an expert code reviewer assistant helping developers fix issues identified in pull request reviews.

A reviewer left this comment on a pull request:
---
${reviewComment}
---

File: ${context.filePath} (${context.language})
Code context around the commented line:
\`\`\`${context.language}
${numberedLines}
\`\`\`

The comment refers to line ${context.startLine + context.targetLineOffset}.

Instructions:
- Analyze what the reviewer is asking to fix
- Generate a minimal, correct fix — only change what's necessary
- Output ONLY a \`\`\`suggestion block with the replacement code
- After the block, add one sentence explaining what changed
- If the comment is unclear or you cannot determine a safe fix, say so explicitly

Format your response as:
\`\`\`suggestion
[corrected line(s) here]
\`\`\`
[one-sentence explanation]`;
}
```

### Suggestion Posting

GitHub suggestion blocks must exactly replace the commented line(s). The API call:

```typescript
async function postSuggestion(
  octokit: Octokit,
  owner: string,
  repo: string,
  pullNumber: number,
  inReplyTo: number,
  suggestionBody: string
): Promise<void> {
  await octokit.rest.pulls.createReplyForReviewComment({
    owner,
    repo,
    pull_number: pullNumber,
    comment_id: inReplyTo,
    body: `🤖 **AI Suggested Fix** *(generated — please review before applying)*\n\n${suggestionBody}`,
  });
}
```

---

## Key Engineering Challenges

### 1. Context Window Management

**Problem:** Sending too little context produces bad suggestions; too much is expensive and slow.

**Strategy:**
- Default window: ±20 lines around the commented line
- For complex comments (mentioning function names, types): expand to full function/class using AST parsing (`tree-sitter`)
- Cap at 150 lines; summarize or truncate beyond that

### 2. Suggestion Line Alignment

**Problem:** GitHub suggestions must exactly match the line(s) being replaced. LLM output often includes extra lines or reformatting.

**Strategy:**
- Instruct the LLM to output only the replacement for the specific target line(s)
- Post-process: strip markdown fences, trim whitespace
- Validate that the suggestion block line count matches expectation before posting

### 3. Noise Filtering

**Problem:** Not every review comment needs a code fix (e.g., "Great work!", "Can you explain why you chose this approach?").

**Strategy:**
- Intent classification: quick LLM call or heuristic (does comment contain words like "should", "fix", "change", "wrong", "use X instead"?)
- Only trigger on explicit `/suggest-fix` keyword initially, then broaden

### 4. Auth Token Lifecycle

**Problem:** GitHub installation tokens expire after 1 hour.

**Strategy:**
- Cache tokens with TTL
- Refresh proactively before expiry
- Use `@octokit/auth-app` which handles this automatically

### 5. Rate Limiting

**Problem:** GitHub API has rate limits; Anthropic API has token limits.

**Strategy:**
- Queue all webhook events via BullMQ
- Implement exponential backoff on 429s
- Track per-installation API usage

---

## Configuration (Per Repo)

Support a `.github/suggest-fix.yml` config file in each repo:

```yaml
suggest-fix:
  enabled: true
  trigger: auto          # auto | keyword | mention
  keyword: "/suggest-fix"
  languages:             # Limit to specific languages (optional)
    - typescript
    - python
  exclude_paths:         # Never suggest fixes in these paths
    - "*.test.ts"
    - "migrations/"
  max_context_lines: 30
  post_as_reply: true    # Reply to original comment vs new top-level comment
```

---

## Testing Strategy

### Unit Tests
- Prompt builder: verify correct line numbers, language detection, context window
- Parser: extract suggestion blocks from various LLM response formats
- Context fetcher: mock GitHub API, verify line slicing logic

### Integration Tests
- End-to-end with a test GitHub repo using `@octokit/webhooks` to replay events
- Golden-set tests: known comment + code pairs with expected suggestion quality

### Eval Framework (Important for LLM Quality)
- Maintain a dataset of (comment, code, expected_fix) triples
- Score suggestions on: correctness (does it compile?), minimality (lines changed), relevance (does it address the comment?)
- Run evals on prompt changes before deploying

---

## Deployment

### Dockerfile

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY dist/ ./dist/
EXPOSE 3000
CMD ["node", "dist/app.js"]
```

### Environment Variables

```env
GITHUB_APP_ID=
GITHUB_PRIVATE_KEY=           # Multi-line PEM, base64 encode for env vars
GITHUB_WEBHOOK_SECRET=
ANTHROPIC_API_KEY=
REDIS_URL=                    # For BullMQ queue
PORT=3000
LOG_LEVEL=info
```

### Hosting Options

| Option | Best For | Notes |
|---|---|---|
| Railway | Quick start, hobby | Free tier available |
| Fly.io | Production, low latency | Good global distribution |
| AWS Lambda + API Gateway | Serverless, cost-efficient | Cold start latency for webhooks |
| Render | Simple deploys | Good DX |

---

## Development Milestones

### Milestone 1 — GitHub Action MVP (Week 1)
- [ ] `/suggest-fix` keyword trigger via GitHub Action
- [ ] Fetch file content + call Claude API
- [ ] Post suggestion block as reply
- [ ] Test on a real PR in a private repo

### Milestone 2 — GitHub App Skeleton (Week 2)
- [ ] Register GitHub App
- [ ] Webhook handler with signature verification
- [ ] Installation token auth flow
- [ ] Basic event routing

### Milestone 3 — Core Feature (Week 3)
- [ ] Context fetcher (file content + line windowing)
- [ ] Prompt builder + Claude integration
- [ ] Suggestion parser + poster
- [ ] Intent filter (skip non-fix comments)

### Milestone 4 — Reliability (Week 4)
- [ ] BullMQ async queue + worker
- [ ] Retry logic + error handling
- [ ] Config file support (`.github/suggest-fix.yml`)
- [ ] Rate limit handling

### Milestone 5 — Quality & Evals (Week 5)
- [ ] Eval dataset + scoring pipeline
- [ ] Unit + integration tests
- [ ] Language detection + AST-based context expansion
- [ ] Metrics: suggestion acceptance rate, latency, error rate

### Milestone 6 — Polish & Launch (Week 6)
- [ ] README + setup docs
- [ ] Marketplace listing prep
- [ ] Landing page (optional)
- [ ] Open source or private launch

---

## Open Questions / Future Ideas

- **Suggestion acceptance tracking:** React to comment edits to know if the suggestion was accepted, and use that as a feedback signal
- **Multi-line suggestions:** Handle cases where a fix spans multiple lines
- **Explanation mode:** Let reviewer ask `/explain-fix` to get reasoning without auto-posting
- **IDE integration:** VS Code extension that surfaces the same suggestions locally
- **Fine-tuning:** Collect accepted suggestions to fine-tune a smaller, faster model specific to your codebase
- **Security scanning integration:** Trigger automatically when a security-related comment is detected

---

## Resources

- [GitHub Apps Documentation](https://docs.github.com/en/apps/creating-github-apps)
- [Octokit.js](https://github.com/octokit/octokit.js)
- [GitHub Pull Request Review Comment API](https://docs.github.com/en/rest/pulls/comments)
- [GitHub Suggestion Syntax](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/incorporating-feedback-in-your-pull-request)
- [Anthropic Claude API Docs](https://docs.anthropic.com)
- [Probot Framework](https://probot.github.io/)
