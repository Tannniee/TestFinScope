# Git Tagging & Release Rule

- **Tagging on Push**: Every time work is completed and pushed to remote (`origin/main`), create a git tag and push it (`git tag vX.Y.Z` and `git push origin vX.Y.Z`).
- **Version Sequence**:
  - The next push starts at: `v1.0.0`
  - Subsequent pushes increment by 0.0.1: `v1.0.1`, `v1.0.2`, `v1.0.3`, ...
