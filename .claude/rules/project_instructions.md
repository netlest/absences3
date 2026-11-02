# Project instructions for Claude Code

Python project managed with **uv**. You work on a remote VPS; the owner reviews and tests every change locally before it is accepted. Never merge your own work.

## Workflow (always follow)

1. **Start from fresh `main`.**
   ```bash
   git switch main && git pull --ff-only
   ```
2. **Create one branch per feature or fix.** Name it `feature/<short-name>`, `fix/<short-name>` or `chore/<short-name>`.
   ```bash
   git switch -c feature/<short-name>
   ```
3. **Never commit or push directly to `main`.** Never force-push, rewrite published history, or merge PRs. If asked to, refuse and explain this rule.
4. **Make small, focused commits** with clear imperative messages (e.g. `Add CSV parser`). One logical change per commit.
5. **Before every push, run the checks and make sure they pass:**
   ```bash
   uv sync --frozen --all-packages
   uv run ruff check .
   uv run ruff format --check .
   uv run --directory frontend pytest
   ```
   If a check fails, fix it (`uv run ruff check --fix .` and `uv run ruff format .` fix most ruff findings). Do not push failing code. If you cannot fix it, say so in the PR description.
6. **Push and open a PR (only if none exists yet):**
   ```bash
   git push -u origin HEAD
   gh pr view >/dev/null 2>&1 || gh pr create --fill --base main
   ```
   If a PR for this branch already exists, just push new commits to it. Never create a second PR for the same branch.

7. **Stop after opening the PR.** Report the PR URL and wait for review. Do not start the next feature on the same branch.

## PR description must include

- **What changed** and why (2-5 lines).
- **How to test locally** — exact commands the owner can run after `gh pr checkout <number>` (e.g. `uv sync --frozen --all-packages && uv run ruff check . && uv run --directory frontend pytest`).
- **Risks / follow-ups**, including anything not done or not verified.

## Handling review feedback

- Address comments by adding commits to the **same branch**; do not open a new PR.
- Read PR comments with `gh pr view <number> --comments` and `gh api repos/{owner}/{repo}/pulls/<number>/comments`.
- Summarize what you changed in response to each comment.

## Dependencies and environment

- Use `uv add <pkg>` / `uv add --dev <pkg>` / `uv remove <pkg>`. Never use `pip install` or edit `pyproject.toml` dependency lists by hand.
- Always commit `uv.lock` together with `pyproject.toml` changes.
- Run code with `uv run ...`. Do not activate or commit `.venv/`.
- Do not change the supported Python version (`requires-python`, ruff's `target-version`) without asking.

## Code standards

- Add or update tests for every behavior change; bug fixes get a regression test.
- Keep type hints on public functions. Keep functions small and readable.
- Write optional types as `X | None`, never `Optional[X]` (enforced by ruff rule UP045).
- Code must pass `ruff check` and `ruff format --check` (config: `[tool.ruff]` in the root `pyproject.toml`). Don't add `# noqa` without a short reason after it.
- Don't add unrelated refactors or formatting churn to a feature PR.
- Update `README.md` when usage or setup changes.

## Safety rules

- **Never commit secrets** (`.env`, tokens, keys, credentials). Use `.env` (git-ignored) and keep `.env.example` up to date with variable names only.
- Don't run destructive commands (`rm -rf`, `git reset --hard`, `git clean -fd`, dropping databases) outside the project's temp/build directories without asking.
- Don't modify `.github/workflows/`, branch protection, or repository settings unless the task says so.
- If the task is ambiguous or touches something risky, ask before proceeding.

## Project commands

Run from the repo root (see `CLAUDE.md` for details).

| Task         | Command                                                            |
|--------------|--------------------------------------------------------------------|
| Install      | `uv sync --frozen --all-packages`                                  |
| Run UI       | `uv run --directory frontend uvicorn app:app --reload --port 8000` |
| Run API      | `uv run --directory backend uvicorn app:app --reload --port 8001`  |
| Test         | `uv run --directory frontend pytest`                               |
| Lint         | `uv run ruff check .` (autofix: `--fix`)                           |
| Format       | `uv run ruff format .` (check only: `--check`)                     |

