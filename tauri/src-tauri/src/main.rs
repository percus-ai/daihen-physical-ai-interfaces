//! Tauri application with backend sidecar.

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // Start backend server as sidecar
            // The backend binary should be bundled with the app
            let sidecar = app.shell().sidecar("percus-server")?;
            let (mut rx, _child) = sidecar.args(["--port", "8000"]).spawn()?;

            // Log sidecar output
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let tauri::api::process::CommandEvent::Stdout(line) = event {
                        println!("[backend] {}", line);
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
