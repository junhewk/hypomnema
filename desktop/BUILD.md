# Building Hypomnema Desktop

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

## Build flags

- `--skip-frontend` — skip Next.js static export
- `--skip-backend` — skip PyInstaller sidecar
- `--skip-tauri` — skip Tauri application build

## Uploading releases

Use the release script to upload to Gitea:

```bash
python desktop/packaging/release.py \
  --version v0.1.0 \
  --artifact <path-to-artifact> \
  --gitea-url http://100.122.128.11:3000 \
  --repo jk/hypomnema
```
