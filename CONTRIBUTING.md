# Contributing

## Branching strategy
- `main` is always working and is protected. Never commit directly to it.
- Create a short-lived branch for each task:
  - `feat/<short-name>`: new feature
  - `fix/<short-name>`: bug fix
  - `docs/<short-name>`: documentation
  - `chore/<short-name>`: tooling and setup
- Open a pull request (PR) into `main`. At least one approval and a passing
  automated check are required before merging.

## Commit messages (Conventional Commits)
Format: `type(scope): short description`

Examples:
- `feat(ingest): add PDF loader`
- `fix(api): handle empty query`
- `docs(readme): add setup steps`
- `chore(ci): add GitHub Actions workflow`
- `test(fees): add fee calculation tests`

Types: feat, fix, docs, test, chore, refactor.

## Code review etiquette
- Be specific and kind. Comment on the code, not the person.
- Explain *why* when requesting a change.
- Author: respond to every comment, and keep PRs small.