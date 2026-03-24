# Building Hypomnema Desktop

> **macOS Sequoia+ (15.0+):** Apple has tightened Gatekeeper enforcement.
> Unsigned apps are blocked entirely — the old `xattr -cr` workaround no
> longer works reliably. The build script now applies **ad-hoc code signing**
> automatically when no `APPLE_SIGNING_IDENTITY` env var is set. This allows
> the app to launch via right-click > Open, but users will still see a
> "developer cannot be verified" prompt. For distribution without warnings,
> set up proper Apple Developer signing (see Code Signing section below).

Each platform must be built natively — no cross-compilation.

## Prerequisites (all platforms)

- Rust (via [rustup](https://rustup.rs))
- Node.js 20+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Tauri CLI: `cargo install tauri-cli`

## macOS

Additional prerequisites:
- Xcode CLI tools: `xcode-select --install`

```bash
cd backend && uv sync --group desktop
cd frontend && npm install
python desktop/packaging/build.py
```

Output: `desktop/src-tauri/target/release/bundle/dmg/Hypomnema_0.1.0_aarch64.dmg`

## Windows

Additional prerequisites:
- Visual Studio Build Tools (C++ workload)

```bash
cd backend && uv sync --group desktop
cd frontend && npm install
python desktop/packaging/build.py
```

Output: `desktop/src-tauri/target/release/bundle/msi/Hypomnema_0.1.0_x64_en-US.msi`

## Linux

Additional prerequisites:
```bash
sudo apt install libwebkit2gtk-4.1-dev libappindicator3-dev
```

```bash
cd backend && uv sync --group desktop
cd frontend && npm install
python desktop/packaging/build.py
```

Output: `desktop/src-tauri/target/release/bundle/appimage/Hypomnema_0.1.0_amd64.AppImage`

## Code signing

The app is distributed unsigned. Each platform shows a warning on first launch.

### macOS

The build script automatically applies **ad-hoc code signing** (`codesign --force --deep -s -`) when no `APPLE_SIGNING_IDENTITY` env var is set. This is sufficient for local development and lets the app launch via right-click > Open on Sequoia+.

If you encounter Gatekeeper issues on older macOS versions, run:

```bash
xattr -cr /Applications/Hypomnema.app
```

To sign properly for distribution: enroll in Apple Developer Program ($99/yr), then set `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, and `APPLE_TEAM_ID` env vars before running `cargo tauri build`. Tauri handles notarization automatically with these set.

### Windows

SmartScreen warns on first launch. Click "More info" then "Run anyway".

To sign: purchase a code signing certificate from a CA ($200-400/yr), then use `signtool.exe` on the MSI output.

### Linux

AppImage works unsigned. No action needed.

## Build flags

- `--skip-frontend` — skip Next.js static export
- `--skip-backend` — skip PyInstaller sidecar
- `--skip-tauri` — skip Tauri application build

## Uploading releases

Use the release script to upload to GitHub:

```bash
GITHUB_TOKEN=your-token python desktop/packaging/release.py \
  --version v0.1.0 \
  --artifact <path-to-artifact> \
  --repo your-org/hypomnema
```
