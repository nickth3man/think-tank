//! Local server for the Think Tank UI.
//!
//! Serves the static front-end in `ui/web`, builds deliberation reports from the
//! recorded scenarios (`/api/report`), and tells the page when a front-end file
//! changed (`/__version`) so edits show up without a manual reload. It binds to
//! loopback only and makes no outbound calls: replays run against a local stub.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::SystemTime;

use serde_json::{json, Value};
use think_tank::uireport;

const DEFAULT_PORT: u16 = 5174;

struct App {
    web_dir: PathBuf,
    /// Replays mutate process-wide env and stub state, so they run one at a time
    /// and each scenario is replayed only once.
    reports: Mutex<HashMap<String, Value>>,
}

fn content_type(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()) {
        Some("html") => "text/html; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        Some("js") | Some("mjs") => "text/javascript; charset=utf-8",
        Some("json") => "application/json; charset=utf-8",
        Some("svg") => "image/svg+xml",
        _ => "application/octet-stream",
    }
}

fn respond(stream: &mut TcpStream, status: &str, ctype: &str, body: &[u8]) {
    let head = format!(
        "HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
        status,
        ctype,
        body.len()
    );
    let _ = stream.write_all(head.as_bytes());
    let _ = stream.write_all(body);
}

fn respond_json(stream: &mut TcpStream, status: &str, value: &Value) {
    let body = serde_json::to_vec(value).unwrap_or_default();
    respond(stream, status, "application/json; charset=utf-8", &body);
}

/// Newest modification time under `dir`, as nanoseconds since the epoch.
fn newest_mtime(dir: &Path) -> u128 {
    let mut newest = 0u128;
    let mut stack = vec![dir.to_path_buf()];
    while let Some(current) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&current) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Ok(meta) = entry.metadata() else { continue };
            if meta.is_dir() {
                stack.push(path);
            } else if let Ok(modified) = meta.modified() {
                let nanos = modified
                    .duration_since(SystemTime::UNIX_EPOCH)
                    .map(|d| d.as_nanos())
                    .unwrap_or(0);
                newest = newest.max(nanos);
            }
        }
    }
    newest
}

fn percent_decode(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or("");
                match u8::from_str_radix(hex, 16) {
                    Ok(byte) => {
                        out.push(byte);
                        i += 2;
                    }
                    Err(_) => out.push(b'%'),
                }
            }
            other => out.push(other),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn query_param(query: &str, key: &str) -> Option<String> {
    query.split('&').find_map(|pair| {
        let (k, v) = pair.split_once('=')?;
        (k == key).then(|| percent_decode(v))
    })
}

fn serve_static(app: &App, stream: &mut TcpStream, url_path: &str) {
    let relative = match url_path.trim_start_matches('/') {
        "" => "index.html",
        other => other,
    };
    if relative
        .split('/')
        .any(|part| part == ".." || part.is_empty())
    {
        return respond(stream, "400 Bad Request", "text/plain", b"bad path");
    }
    let path = app.web_dir.join(relative);
    match std::fs::read(&path) {
        Ok(bytes) => respond(stream, "200 OK", content_type(&path), &bytes),
        Err(_) => respond(stream, "404 Not Found", "text/plain", b"not found"),
    }
}

fn handle(app: &App, mut stream: TcpStream) {
    let mut reader = BufReader::new(match stream.try_clone() {
        Ok(clone) => clone,
        Err(_) => return,
    });
    let mut request_line = String::new();
    if reader.read_line(&mut request_line).is_err() {
        return;
    }
    // Drain headers; no endpoint reads a body.
    loop {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) if line == "\r\n" || line == "\n" => break,
            Ok(_) => {}
            Err(_) => return,
        }
    }
    let mut parts = request_line.split_whitespace();
    let (Some(method), Some(target)) = (parts.next(), parts.next()) else {
        return;
    };
    if method != "GET" {
        return respond(
            &mut stream,
            "405 Method Not Allowed",
            "text/plain",
            b"GET only",
        );
    }
    let (path, query) = target.split_once('?').unwrap_or((target, ""));

    match path {
        "/__version" => {
            let version = newest_mtime(&app.web_dir).to_string();
            respond(&mut stream, "200 OK", "text/plain", version.as_bytes());
        }
        "/api/scenarios" => {
            respond_json(
                &mut stream,
                "200 OK",
                &json!({"scenarios": uireport::scenario_names()}),
            );
        }
        "/api/report" => {
            let Some(name) = query_param(query, "scenario") else {
                return respond_json(
                    &mut stream,
                    "400 Bad Request",
                    &json!({"error": "missing ?scenario=", "scenarios": uireport::scenario_names()}),
                );
            };
            let mut cache = app.reports.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(report) = cache.get(&name) {
                return respond_json(&mut stream, "200 OK", report);
            }
            match uireport::replay_named(&name) {
                Ok(report) => {
                    respond_json(&mut stream, "200 OK", &report);
                    cache.insert(name, report);
                }
                Err(error) => respond_json(
                    &mut stream,
                    "500 Internal Server Error",
                    &json!({"error": error}),
                ),
            }
        }
        other => serve_static(app, &mut stream, other),
    }
}

fn main() {
    let web_dir = std::env::var("THINK_TANK_UI_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| Path::new(env!("CARGO_MANIFEST_DIR")).join("../ui/web"));
    let port = std::env::var("THINK_TANK_UI_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(DEFAULT_PORT);
    let listener = match TcpListener::bind(("127.0.0.1", port)) {
        Ok(listener) => listener,
        Err(error) => {
            eprintln!("cannot bind 127.0.0.1:{}: {}", port, error);
            std::process::exit(1);
        }
    };
    let app = Arc::new(App {
        web_dir,
        reports: Mutex::new(HashMap::new()),
    });
    println!("Think Tank UI: http://127.0.0.1:{}/", port);
    println!("serving {}", app.web_dir.display());
    for stream in listener.incoming().flatten() {
        let app = Arc::clone(&app);
        std::thread::spawn(move || handle(&app, stream));
    }
}
