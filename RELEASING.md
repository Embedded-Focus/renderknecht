# Releasing Renderknecht

## TestPyPI setup

The release workflow uses OpenID Connect trusted publishing. It does not use a stored API token.

1. In the GitHub repository, create an environment named `testpypi` and configure its desired
   reviewers and tag protection rules.
2. In TestPyPI, create a pending trusted publisher with these exact values:
   - PyPI project name: `renderknecht`
   - Owner: `Embedded-Focus`
   - Repository: `renderknecht`
   - Workflow: `publish-testpypi.yml`
   - Environment: `testpypi`
3. Confirm that the release commit passes the normal CI workflow.

## Publish to TestPyPI

The version has one source of truth in `pyproject.toml`. TestPyPI distributions cannot be
overwritten, so increment it before retrying a version that was already uploaded.

```sh
uv version 0.1.0
git tag v0.1.0
git push public v0.1.0
```

Publish a GitHub release for the tag. The `Publish to TestPyPI` workflow then:

1. verifies the stable tag and package version;
2. runs formatting, lint, type, test, and dependency-audit checks;
3. builds and validates the wheel and source distribution once;
4. installs both artifacts in isolated environments;
5. builds and smoke-tests the image from the wheel;
6. publishes those validated files to TestPyPI;
7. installs from TestPyPI and performs another complete PDF render.

Verify the resulting files and metadata at
<https://test.pypi.org/project/renderknecht/>.

Production PyPI publishing will be added after this TestPyPI path has completed successfully.
