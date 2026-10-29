# AI Overlay for Windows

This repository builds `ai_overlay.py` into a single Windows executable using GitHub Actions.

## Files

- `ai_overlay.py` — the application source.
- `requirements.txt` — Python packages used by the application and the packager.
- `.github/workflows/build-release.yml` — builds the EXE and publishes it to GitHub Releases when you push a version tag.

## Upload the project to GitHub

1. Create a new GitHub repository.
2. Upload these files while keeping the `.github/workflows/` folder path exactly as shown.
3. Commit and push the files to the repository's default branch.

## Build an EXE without publishing a Release

1. Open the repository on GitHub.
2. Select **Actions**.
3. Select **Build Windows EXE and Release**.
4. Click **Run workflow**.
5. When it finishes, open that run and download the `AI-Overlay-Windows` artifact.

Manual workflow runs create an Actions artifact only. They do not publish a Release.

## Publish an EXE in the repository's Releases tab

From a terminal in the repository folder, run:

```bash
git add .
git commit -m "Set up Windows EXE build"
git push
git tag v1.0.0
git push origin v1.0.0
```

Pushing a tag whose name starts with `v` starts the workflow. When it succeeds, open the repository's **Releases** tab and select the release for `v1.0.0`. The `AI-Overlay.exe` file will be attached to that release.

For a later version, use a new tag such as `v1.0.1`. Git tags must be unique.

## Important notes

- GitHub Actions builds this on a Windows runner; the resulting EXE is for Windows, not macOS or Linux.
- The app uses microphone/audio, global hotkeys, screen capture and optional mouse/keyboard automation. Windows may show permission, security or antivirus warnings for newly built executables.
- API keys are configured inside the app's Settings; do not commit real API keys to GitHub.
- On first launch, configure a provider in Settings. Internet-based providers may require their own API key.
- The app writes `config.json`, `memory.json` and `vault.bin` beside the EXE. Put the EXE in a folder where your Windows user has write permission (for example, a folder under your user profile), rather than a protected system folder.
- This workflow does not sign the executable. Windows SmartScreen may warn about an unsigned EXE.
