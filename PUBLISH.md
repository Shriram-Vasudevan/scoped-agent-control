# Publishing to PyPI

Releases go out automatically when a tag matching `v*` is pushed.

## First-time setup (once per PyPI project)

1. Sign in at https://pypi.org.
2. Reserve the project name: create a dummy `scoped-agent-control` 0.0.1 release
   manually, OR wait for the first action run to create it (Trusted Publisher
   auto-creates projects as of 2024).
3. Add a Trusted Publisher entry at
   https://pypi.org/manage/account/publishing/ with:
   - PyPI Project Name: `scoped-agent-control`
   - Owner: `Shriram-Vasudevan`
   - Repository: `scoped-agent-control`
   - Workflow filename: `publish-pypi.yml`
   - Environment name: `pypi`
4. On GitHub, create a repository Environment named `pypi`
   (Settings → Environments → New environment). No secrets required —
   OIDC is used.

## Cut a release

```bash
# Bump the version in pyproject.toml.
git commit -am "Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

The `publish-pypi.yml` workflow builds the sdist + wheel and uploads them via
OIDC trusted publishing — no API token required.
