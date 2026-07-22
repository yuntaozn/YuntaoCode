#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            exit_app,
            find_free_port,
            kill_process_tree,
        ])
        .run(tauri::generate_context!())
        .expect("error while running YuntaoCode");
}

#[tauri::command]
fn exit_app(app: tauri::AppHandle) -> Result<(), String> {
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn find_free_port(host: String) -> Result<u16, String> {
    let listener = std::net::TcpListener::bind((host.as_str(), 0))
        .map_err(|error| format!("failed to reserve local port: {error}"))?;
    let address = listener
        .local_addr()
        .map_err(|error| format!("failed to inspect reserved local port: {error}"))?;
    Ok(address.port())
}

#[tauri::command]
fn kill_process_tree(pid: u32) -> Result<(), String> {
    kill_process_tree_impl(pid)
}

#[cfg(windows)]
fn kill_process_tree_impl(pid: u32) -> Result<(), String> {
    use std::os::windows::process::CommandExt;

    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let output = std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .output()
        .map_err(|error| format!("failed to run taskkill: {error}"))?;
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let detail = if stderr.is_empty() { stdout } else { stderr };
    Err(if detail.is_empty() {
        format!("taskkill failed with status {}", output.status)
    } else {
        detail
    })
}

#[cfg(not(windows))]
fn kill_process_tree_impl(pid: u32) -> Result<(), String> {
    let output = std::process::Command::new("kill")
        .args(["-TERM", &pid.to_string()])
        .output()
        .map_err(|error| format!("failed to run kill: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        Err(if stderr.is_empty() {
            format!("kill failed with status {}", output.status)
        } else {
            stderr
        })
    }
}
