# AI Overlay — automatic Windows build and GitHub Releases

Every push to the `main` branch automatically builds `AI-Overlay.exe` on a Windows GitHub Actions runner and creates a GitHub Release with the executable attached. You can also start the workflow manually from the **Actions** tab.

## What the workflow does

- Builds a single-file Windows executable with PyInstaller.
- Uploads the EXE as an Actions artifact (retained for 30 days).
- Creates a release with a version like `v1.0.12` and title `AI-Overlay v1.0.12`.
- Uses GitHub-generated release notes for the release description.
- Attaches `AI-Overlay.exe` to the release so people can download it from **Releases**.

The patch number comes from the GitHub Actions run number, so each new workflow run gets a new version tag. The workflow creates the release itself; you do not need to push a version tag manually.

## Repository setup

1. Put `ai_overlay.py`, `requirements.txt`, `.gitignore`, `README.md`, and `.github/workflows/build-release.yml` in the root of your GitHub repository. Keep the `.github` folder and workflow filename exactly as shown.
2. Make sure the default branch is named `main`. If your branch is named `master` or something else, update the branch under `on.push.branches` in the workflow.
3. In GitHub, open **Settings → Actions → General → Workflow permissions** and enable **Read and write permissions** if organization/repository policy allows it. The workflow declares `contents: write` to let `GITHUB_TOKEN` create releases.
4. Commit and push the workflow to `main`.
5. Every subsequent push to `main` starts a build and publishes a release automatically. To start one manually, use **Actions → Build Windows EXE and Publish Release → Run workflow**.

## Versioning note

The version is `v1.0.<GitHub Actions run number>`. Since run numbers count workflow runs, versions may skip numbers if a run fails before publishing; a failed run can be rerun, but a release that was already created under that tag should not be recreated. If you want strict semantic versioning (major/minor/patch based on a version file), this workflow can be adapted for that.

## Important notes

- This builds a Windows executable using `windows-latest`; it does not build a macOS or Linux executable.
- Do not commit API keys, passwords, or private configuration.
- The app may store its configuration, memory, or vault files beside the executable; place it in a folder where you have write permission.
- The executable is not code-signed, so Windows SmartScreen may show a warning.
