use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use tauri::RunEvent;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Wrapper so we can store the sidecar child handle via `app.manage()`.
struct Backend(Mutex<Option<CommandChild>>);

fn backend_executable_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "hypomnema-server.exe"
    } else {
        "hypomnema-server"
    }
}

fn backend_executable_path<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("failed to resolve resources dir: {e}"))?;
    let bundled_paths = [
        resource_dir
            .join("hypomnema-server")
            .join(backend_executable_name()),
        resource_dir
            .join("resources")
            .join("hypomnema-server")
            .join(backend_executable_name()),
    ];

    for bundled_path in bundled_paths {
        if bundled_path.exists() {
            return Ok(bundled_path);
        }
    }

    let dev_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("resources")
        .join("hypomnema-server")
        .join(backend_executable_name());
    if dev_path.exists() {
        return Ok(dev_path);
    }

    Err(format!(
        "backend executable not found under {} or {}",
        resource_dir.display(),
        dev_path.display(),
    ))
}

/// Poll GET /api/health until the sidecar is ready.
async fn wait_for_backend(port: u16, timeout: Duration) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/api/health", port);
    let client = reqwest::Client::new();
    let start = std::time::Instant::now();

    loop {
        if start.elapsed() > timeout {
            return Err("Backend failed to start within timeout".into());
        }
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            _ => tokio::time::sleep(Duration::from_millis(250)).await,
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let port: u16 = 8073;

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(move |app| {
            let handle = app.handle().clone();
            let backend_path = backend_executable_path(&handle)?;

            // Spawn the Python sidecar
            let sidecar = handle
                .shell()
                .command(&backend_path)
                .args(["--port", &port.to_string()]);

            let (mut _rx, child) = sidecar
                .spawn()
                .map_err(|e| format!("failed to spawn backend {}: {e}", backend_path.display()))?;

            // Store child handle in Mutex for cleanup on exit
            app.manage(Backend(Mutex::new(Some(child))));

            // Wait for backend readiness in background
            let window = app.get_webview_window("main").unwrap();
            let dialog_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                match wait_for_backend(port, Duration::from_secs(30)).await {
                    Ok(()) => {
                        let url = format!("http://127.0.0.1:{}", port);
                        let _ = window.eval(&format!("window.location.replace('{}')", url));
                    }
                    Err(e) => {
                        eprintln!("Backend startup failed: {}", e);
                        tauri::async_runtime::spawn_blocking(move || {
                            use tauri_plugin_dialog::DialogExt;
                            dialog_handle
                                .dialog()
                                .message(
                                    "Backend failed to start. Please check logs and restart the application.",
                                )
                                .title("Hypomnema — Startup Error")
                                .kind(tauri_plugin_dialog::MessageDialogKind::Error)
                                .blocking_show();
                            dialog_handle.exit(1);
                        });
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = &event {
                // Kill the sidecar backend process on exit
                if let Some(backend) = app_handle.try_state::<Backend>() {
                    if let Ok(mut guard) = backend.0.lock() {
                        if let Some(child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
