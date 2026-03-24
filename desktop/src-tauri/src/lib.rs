use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use tauri::RunEvent;
use tauri_plugin_shell::process::CommandChild;

/// Wrapper so we can store the sidecar child handle via `app.manage()`.
struct Backend(Mutex<Option<CommandChild>>);

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
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(move |app| {
            let handle = app.handle().clone();

            // Spawn the Python sidecar
            let sidecar = handle
                .shell()
                .sidecar("hypomnema-server")
                .expect("failed to create sidecar command")
                .args(["--port", &port.to_string()]);

            let (mut _rx, child) = sidecar.spawn().expect("failed to spawn sidecar");

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
