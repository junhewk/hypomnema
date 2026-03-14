use std::time::Duration;
use tauri::Manager;

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
        .setup(move |app| {
            let handle = app.handle().clone();

            // Spawn the Python sidecar
            let sidecar = handle
                .shell()
                .sidecar("hypomnema-server")
                .expect("failed to create sidecar command")
                .args(["--port", &port.to_string()]);

            let (mut _rx, _child) = sidecar.spawn().expect("failed to spawn sidecar");

            // Store child handle for cleanup
            app.manage(_child);

            // Wait for backend readiness in background
            let window = app.get_webview_window("main").unwrap();
            tauri::async_runtime::spawn(async move {
                match wait_for_backend(port, Duration::from_secs(30)).await {
                    Ok(()) => {
                        let url = format!("http://127.0.0.1:{}", port);
                        let _ = window.eval(&format!("window.location.replace('{}')", url));
                    }
                    Err(e) => {
                        eprintln!("Backend startup failed: {}", e);
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
