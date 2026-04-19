# Product Requirements Document: GitHub PR Review AI Assistant

**Version:** 1.0
**Date:** April 19, 2026
**Status:** Draft

---

## 1. Problem Statement

Code review is one of the most valuable — and most friction-filled — parts of the software development workflow. Reviewers leave comments that range from crystal clear to cryptic. PR authors, especially junior engineers or those unfamiliar with a codebase's conventions, often struggle to:

- Understand *why* a reviewer flagged something (not just *what* was flagged)
- Know *how many legitimate ways* exist to address the feedback
- Make an informed tradeoff decision between different approaches
- Ask follow-up questions without feeling like they are bothering the reviewer

The result is slow iteration cycles, frustration on both sides, and PRs that get merged with cargo-culted fixes that the author doesn't fully understand.

**The core insight:** The problem isn't that developers need a bot to fix their code. The problem is that they need a knowledgeable collaborator to help them *understand* the feedback and *think through* their options — the way a senior engineer sitting next to them would.

---

## 2. Product Vision

A browser extension that lives inside GitHub's PR review UI and gives every PR author an always-available AI collaborator. When a reviewer leaves a comment, the author can instantly get a contextual analysis: what the reviewer likely means, multiple ways to address the concern, and the concrete pros and cons of each approach.

The goal is **understanding**, not automation. The extension explains and explores; the author decides and acts.

---

## 3. Primary Persona

**Name:** Alex
**Role:** Mid-level software engineer, 2–4 years of experience
**Context:** Works on a team of 5–10 engineers. Reviews happen async. Alex authors several PRs per week and receives review feedback that is sometimes terse or assumes familiarity with patterns Alex hasn't encountered before.

**Pain points:**
- Reviewer comments like "this should use the repository pattern" or "prefer composition here" leave Alex unsure whether to ask for clarification or just guess
- When Alex does ask follow-up questions in the PR thread, it takes hours or days to get a response, blocking the PR
- Alex sometimes makes a change just to unblock the PR, without fully understanding whether it was the right call

**What Alex needs:**
- Immediate, private context on what a comment means in the context of *this codebase*
- Multiple options laid out clearly so Alex can make an informed decision
- A safe space to ask "dumb" follow-up questions without social cost

**Secondary persona (future, not MVP):** Senior engineers who want to understand reviewer suggestions before accepting or pushing back.

---

## 4. MVP Scope

### 4.1 Core Features

#### F1 — AI Help Button Injection
The extension injects an "Get AI Help" icon button next to each inline review comment on a GitHub PR page. The button is visible only on PR pages where the logged-in user is the PR author.

#### F2 — AI Analysis Panel
Clicking the button opens a right-side slide-in panel anchored to the page. The panel is scoped to the specific review comment that was clicked.

The first message in every conversation is always AI-generated and includes:
- A plain-English interpretation of what the reviewer is asking for
- 2–4 distinct ways to address the feedback, each with clearly labeled pros and cons
- A brief note on which approach is most conventional given the visible codebase context

No user input is required to generate this first message — it is triggered automatically on button click.

#### F3 — Follow-up Conversation
After the initial analysis, the user can ask follow-up questions in a standard chat input. The conversation is contextual — the AI retains the full thread within a session and can answer clarifications, explain tradeoffs further, or dig into specific implementation details.

#### F4 — Conversation Persistence
When the user closes the panel, the conversation is serialized to `localStorage` keyed by PR URL + comment ID. When the user reopens the panel for the same comment, the previous conversation is restored and the user can continue from where they left off.

#### F5 — Repo Indexing
On first use of the extension on a given repository, the local backend automatically indexes the full repository into a local vector store. Subsequent uses retrieve relevant chunks via semantic search. The user is shown a brief "Indexing repo..." status indicator during this process.

#### F6 — Extension Settings Page
A simple settings page (accessible from the extension popup) where the user enters and saves their Anthropic API key. The key is stored in Chrome's `storage.sync` API.

### 4.2 Context Passed to AI

Every AI request includes the following assembled context:

| Context Layer | Source | Notes |
|---|---|---|
| Review comment text | GitHub page DOM / GitHub API | The specific comment being analyzed |
| Surrounding diff hunk | GitHub API (PR diff) | The lines changed, with before/after |
| Full file content | GitHub API | The file containing the comment |
| Repo chunks (RAG) | Local vector store | Top-K semantically relevant chunks from the indexed repo |
| Conversation history | localStorage | All prior messages in this comment's thread |

### 4.3 Technical Architecture

#### Browser Extension (Chrome MV3)
- **Content script:** Injects UI elements into `github.com/*/pull/*` pages. Reads the current GitHub session cookie/token from the browser to authenticate GitHub API calls made by the backend.
- **Popup:** Settings page for API key entry.
- **Background service worker:** Handles communication between content script and local backend.

#### Local Backend Server
- **Language:** Python (FastAPI)
- **Responsibilities:**
  - Receives context assembly requests from the extension
  - Fetches PR diff and file content via GitHub API (using the session token forwarded from the extension)
  - Queries the local vector store for relevant repo chunks
  - Constructs the prompt and calls the Anthropic Claude API
  - Streams the response back to the extension
  - Manages repo indexing jobs

#### Vector Store (RAG)
- **Library:** ChromaDB (local, embedded, no external server required)
- **Indexing:** Triggered on first use per repo. Clones or fetches repo content via GitHub API, chunks files by semantic boundaries (functions/classes where possible, otherwise fixed-size with overlap), generates embeddings, and stores in ChromaDB.
- **Re-indexing:** Not automatic in MVP. User can manually trigger re-index from the extension popup.
- **Storage location:** Local filesystem, in the backend's working directory.

#### AI Provider
- **Model:** Anthropic Claude (claude-sonnet-4-5 recommended for cost/quality balance; configurable)
- **Auth:** User's own API key, stored in Chrome `storage.sync`, passed to the local backend per request
- **Streaming:** Yes — responses stream token-by-token into the panel for perceived performance

#### Conversation Storage
- **Mechanism:** Browser `localStorage`
- **Key format:** `gh-ai-assist:{repo_full_name}:{pr_number}:{comment_id}`
- **Value:** JSON array of message objects `{ role, content, timestamp }`
- **Retention:** Persists until the user clears browser storage or the extension provides a "Clear conversation" button

---

## 5. UX Flow

```
User navigates to a GitHub PR page (where they are the author)
  |
  v
Extension content script detects PR author match
  |
  v
"Get AI Help" icon injected next to each review comment
  |
  v
User clicks icon on a specific comment
  |
  v
Panel slides in from the right side of the page
  |
  +-- [If prior conversation exists in localStorage]
  |     Load and display prior conversation
  |     Show a "Continue conversation" affordance
  |
  +-- [If no prior conversation]
        Show loading state ("Analyzing comment...")
        Backend assembles context (comment + diff + file + RAG chunks)
        Claude API called, response streams into panel
        Initial analysis displayed (interpretation + options + pros/cons)
  |
  v
User reads analysis, optionally types a follow-up question
  |
  v
Subsequent messages sent with full conversation history + original context
  |
  v
User closes panel → conversation saved to localStorage
```

---

## 6. Out of Scope for MVP

The following are explicitly not part of the MVP and should not be designed for or built toward:

- **Automatic code fix generation or application.** The product surfaces options and explains tradeoffs. It does not write or apply code changes.
- **Firefox or other browsers.** Chrome only for MVP.
- **Cloud backend or hosted infrastructure.** All computation runs locally. No user data leaves the user's machine except to GitHub's API and Anthropic's API.
- **OAuth or GitHub App installation.** Session-based auth only; no OAuth flow.
- **Multi-user or team features.** No shared conversations, no team dashboards.
- **Commenting back to the PR.** The AI analysis is private to the user; nothing is posted to GitHub on their behalf.
- **Support for GitHub Enterprise / self-hosted GitHub.** github.com only.
- **Automatic re-indexing on repo changes.** Indexing is one-time per repo in MVP, manually refreshable.
- **Support for comments on files not in the PR diff.** Only inline review comments on the diff are supported.
- **Mobile browsers.** Desktop only.
- **Multiple AI provider support.** Anthropic Claude only.
- **Extension sync across devices.** localStorage is per-browser, per-machine.

---

## 7. Corner Cases

Each corner case below includes the expected behavior and any required implementation note.

### 7.1 User is Not the PR Author
**Scenario:** The extension is active on a PR page, but the logged-in user did not author the PR.
**Expected behavior:** The "Get AI Help" button is not injected. The extension does nothing visible.
**Implementation note:** Compare the PR author login from the page DOM (or GitHub API) against the authenticated user's login before injecting UI.

### 7.2 Repo Has Not Been Indexed Yet
**Scenario:** User clicks "Get AI Help" on a repo for the first time.
**Expected behavior:** The panel opens immediately and shows an "Indexing this repository for the first time — this may take a minute..." message. Indexing runs in the background. Once complete, the AI analysis is generated. If the repo is large, the panel should show estimated progress.
**Implementation note:** The backend should expose a `/index/status` endpoint that the extension polls. Indexing must not block the UI thread.

### 7.3 Repo Is Very Large
**Scenario:** The repo has tens of thousands of files (e.g., a monorepo).
**Expected behavior:** Indexing may take several minutes. The extension shows a progress indicator. If indexing takes more than 5 minutes, the extension falls back to generating the analysis without RAG context (using only the diff + file) and notifies the user: "Repo still indexing — analysis based on PR context only."
**Implementation note:** The backend's indexer should prioritize files in the same directory as the changed file and files imported by the changed file. Full indexing can continue in the background.

### 7.4 GitHub Session Token Is Missing or Expired
**Scenario:** The extension cannot extract a valid GitHub session token from the browser.
**Expected behavior:** The panel shows an error: "Could not authenticate with GitHub. Please make sure you are logged in to github.com."
**Implementation note:** The content script should check for the presence of a valid session before injecting UI. On token expiry mid-session, the backend returns a 401-equivalent and the extension surfaces the error gracefully.

### 7.5 Anthropic API Key Is Not Set
**Scenario:** User clicks "Get AI Help" but has not entered an API key in settings.
**Expected behavior:** The panel opens and immediately prompts: "Please add your Anthropic API key in the extension settings to use this feature." A link opens the settings popup.
**Implementation note:** The content script should check for a stored API key before making a backend request.

### 7.6 Anthropic API Key Is Invalid or Rate-Limited
**Scenario:** The API call to Claude fails due to an invalid key or rate limit.
**Expected behavior:** The panel shows a specific error message:
  - Invalid key: "Your Anthropic API key appears to be invalid. Please check your settings."
  - Rate limited: "You've hit your Anthropic API rate limit. Please try again shortly."
**Implementation note:** The backend must parse Anthropic error response codes and return structured error types to the extension.

### 7.7 Local Backend Is Not Running
**Scenario:** The user has the extension installed but the local backend server is not running.
**Expected behavior:** The panel shows: "The AI assistant backend is not running. Please start it by running `python server.py` in your terminal."
**Implementation note:** The content script should ping the backend on page load. If no response within 2 seconds, disable the "Get AI Help" button and show a tooltip explaining the backend is offline.

### 7.8 Review Comment Is on a Binary File or Generated File
**Scenario:** The review comment is on a file that is binary (image, compiled artifact) or auto-generated (e.g., `package-lock.json`, protobuf output).
**Expected behavior:** The AI analysis is generated without full file content. The prompt notes that the file is binary or generated. The analysis focuses on the comment text and diff context only.
**Implementation note:** The backend should detect binary/generated files before attempting to fetch and index them.

### 7.9 Very Long Conversation History
**Scenario:** A user has had an extensive back-and-forth conversation (50+ messages) on a single comment.
**Expected behavior:** The extension truncates older messages from the context window passed to Claude, keeping the initial AI analysis and the most recent N exchanges. The user sees the full conversation in the UI (scrollable), but older messages are not re-sent to the API.
**Implementation note:** Implement a rolling context window — always include the first AI message (the original analysis) and the last N user/AI message pairs that fit within the token budget.

### 7.10 PR Has a Very Large Diff
**Scenario:** The PR changes hundreds of files or thousands of lines.
**Expected behavior:** The context passed to AI includes only the specific diff hunk surrounding the comment (not the entire PR diff), plus the full file containing the comment.
**Implementation note:** The GitHub API's pull request review comments endpoint returns the diff hunk directly. Use this rather than fetching the entire PR diff.

### 7.11 Comment Is Outdated (on an Older Commit)
**Scenario:** The PR has been updated since the review comment was left. The comment now shows as "outdated" in GitHub's UI.
**Expected behavior:** The extension still injects the "Get AI Help" button. The AI analysis notes that the comment may be outdated relative to the current state of the PR. The analysis uses the file content at the current HEAD, not the commit the comment was made on.
**Implementation note:** Include a note in the prompt: "This review comment was made on an earlier version of the PR. The current file is provided; the comment's diff hunk may no longer apply exactly."

### 7.12 User Navigates Away Mid-Analysis
**Scenario:** The user clicks "Get AI Help" and then navigates to a different page before the analysis completes.
**Expected behavior:** The in-progress API call is cancelled. When the user returns to the PR page, the conversation state in localStorage is either empty (if no messages were saved) or shows the partial state from before.
**Implementation note:** The background service worker should abort in-flight fetch requests when the content script signals a page unload.

### 7.13 Multiple Comments Opened Simultaneously
**Scenario:** The user quickly clicks "Get AI Help" on multiple comments before closing the first panel.
**Expected behavior:** Only one panel is open at a time. Clicking a second comment's button closes the current panel (saving its conversation to localStorage) and opens a new panel for the newly clicked comment.
**Implementation note:** The content script maintains a single panel instance. Opening a new one always closes the previous.

---

## 8. Success Metrics (MVP Validation)

Since this is an MVP targeting the builder's own use and early adopters, success is defined qualitatively:

- **Adoption signal:** User returns to use the extension on more than 3 PRs after first use
- **Understanding signal:** User reports feeling more confident about the reviewer's intent after reading the AI analysis
- **Engagement signal:** User asks at least one follow-up question per session (indicates the first message was useful enough to engage with, but not over-explaining)

Explicit non-goal for MVP: measuring whether code quality improves. That is a longer-term signal.

---

## 9. Open Questions

| # | Question | Owner | Priority |
|---|---|---|---|
| 1 | Should the extension support Firefox in a fast-follow after Chrome MVP? | Product | Low |
| 2 | Should the local backend support multiple repos being indexed concurrently? | Engineering | Medium |
| 3 | What is the maximum repo size we will support for indexing in MVP? | Engineering | High |
| 4 | Should the initial analysis be regenerated if the user re-opens a closed panel, or always served from cache? | Product | Medium |
| 5 | Do we need a mechanism to clear/reset the local vector store? | Engineering | Medium |
| 6 | Should the extension be published to the Chrome Web Store, or distributed as an unpacked extension for MVP? | Product | High |

---

## 10. Appendix: Prompt Design Principles

The AI prompt should consistently enforce these behaviors:

1. **Lead with interpretation, not code.** The first paragraph of every analysis must be a plain-English explanation of what the reviewer means and why they raised the concern.

2. **Present options, not a verdict.** Offer 2–4 approaches. Never recommend just one without explaining the tradeoff.

3. **Be concrete about tradeoffs.** Pros and cons must be specific to this codebase and this context, not generic software advice.

4. **Never apply changes.** The AI must never produce a ready-to-paste code block as its primary output. It may use brief inline snippets to illustrate a concept, but should not write the full solution.

5. **Acknowledge uncertainty.** If the reviewer's intent is ambiguous, the AI should say so and present interpretations, not pick one arbitrarily.

6. **Codebase-aware tone.** The analysis should reference patterns, conventions, or files visible in the indexed repo context when relevant (e.g., "The rest of this codebase uses X pattern in files like Y...").
