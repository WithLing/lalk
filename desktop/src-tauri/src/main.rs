#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    io::{BufRead, BufReader},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};
use tauri::{
    menu::MenuBuilder,
    path::BaseDirectory,
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, Manager, RunEvent, Runtime,
};

const SIDECAR_DIR: &str = "sidecar/lalk-server";
const SIDECAR_EXECUTABLE: &str = "lalk-server";

struct SidecarProcess(Mutex<Option<Child>>);

impl SidecarProcess {
    fn stop(&self) {
        if let Some(child) = self.0.lock().expect("sidecar lock").take().as_mut() {
            terminate(child);
        }
    }
}

fn resolve_sidecar<R: Runtime>(app: &tauri::App<R>) -> Result<PathBuf, Box<dyn std::error::Error>> {
    #[cfg(debug_assertions)]
    {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join(SIDECAR_DIR)
            .join(SIDECAR_EXECUTABLE);
        if path.is_file() {
            return Ok(path);
        }
    }

    Ok(app.path().resolve(
        format!("{SIDECAR_DIR}/{SIDECAR_EXECUTABLE}"),
        BaseDirectory::Resource,
    )?)
}

fn spawn_sidecar<R: Runtime>(app: &tauri::App<R>) -> Result<Child, Box<dyn std::error::Error>> {
    let executable = resolve_sidecar(app)?;
    let mut child = Command::new(executable)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    if let Some(stdout) = child.stdout.take() {
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                println!("[lalk-server] {line}");
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("[lalk-server] {line}");
            }
        });
    }

    Ok(child)
}

fn terminate(child: &mut Child) {
    unsafe {
        libc::kill(child.id() as i32, libc::SIGTERM);
    }
    for _ in 0..20 {
        if child.try_wait().ok().flatten().is_some() {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let child = spawn_sidecar(app)?;
            app.manage(SidecarProcess(Mutex::new(Some(child))));
            let product_name = app.package_info().name.clone();
            let menu = MenuBuilder::new(app)
                .text("open", format!("打开 {product_name}"))
                .separator()
                .text("quit", "退出")
                .build()?;
            let mut tray = TrayIconBuilder::with_id("lalk")
                .menu(&menu)
                .tooltip(&product_name)
                .show_menu_on_left_click(false)
                .on_menu_event(|handle, event| match event.id().as_ref() {
                    "open" => show_main_window(handle),
                    "quit" => handle.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if matches!(
                        event,
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        }
                    ) {
                        show_main_window(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone()).icon_as_template(true);
            }
            tray.build(app)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Lalk desktop");

    app.run(|handle, event| match event {
        RunEvent::WindowEvent {
            label,
            event: tauri::WindowEvent::CloseRequested { api, .. },
            ..
        } if label == "main" => {
            api.prevent_close();
            let _ = handle.emit("lalk-window-hidden", ());
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.hide();
            }
        }
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows: false,
            ..
        } => show_main_window(handle),
        RunEvent::Exit => stop_sidecar(handle),
        _ => {}
    });
}

fn show_main_window<R: Runtime>(handle: &AppHandle<R>) {
    if let Some(window) = handle.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn stop_sidecar<R: Runtime>(handle: &tauri::AppHandle<R>) {
    if let Some(sidecar) = handle.try_state::<SidecarProcess>() {
        sidecar.stop();
    }
}
