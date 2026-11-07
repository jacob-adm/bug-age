//! MCP server.
//!
//! Read-only MCP server over stdio (JSON-RPC 2.0, one message per line) answering bundle queries.
//!
//! Every value a tool returns is copied from a bundle.json; nothing is computed or inferred.
//! An unknown target, or an unknown or ambiguous SHA prefix, is a tool error, never a guess.

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::io::{BufRead, Write};

/// MCP protocol revision this server implements.
pub const PROTOCOL_VERSION: &str = "2025-06-18";

/// One loaded bundle.
pub struct Target {
    /// Name clients pass as `target`.
    pub name: String,
    /// Parsed bundle.
    pub bundle: Value,
    /// sha256 of the bundle file as read, so clients can check provenance.
    pub sha256: String,
}

impl Target {
    /// Reads and hashes a bundle file.
    ///
    /// # Errors
    /// Returns an error if the file cannot be read or is not JSON.
    pub fn load(name: &str, path: &std::path::Path) -> Result<Target, String> {
        let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let bundle = serde_json::from_slice(&bytes).map_err(|e| format!("{}: {e}", path.display()))?;
        Ok(Target { name: name.to_string(), bundle, sha256: format!("{:x}", Sha256::digest(&bytes)) })
    }
}

/// JSON schema fragment for the `target` argument shared by most tools.
fn target_arg() -> Value {
    json!({"type": "string", "description": "Target name, as listed by list_targets"})
}

/// Tool definitions returned by `tools/list`. Every tool is read-only.
pub fn tools() -> Value {
    json!([
        {"name": "list_targets", "description": "Repositories loaded, with subject (repo URL, crate path, pinned head) and bundle sha256.",
         "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": true}},
        {"name": "get_summary", "description": "Headline metrics exactly as computed by the bug-age CLI, plus subject and bundle sha256.",
         "inputSchema": {"type": "object", "properties": {"target": target_arg()}, "required": ["target"]}, "annotations": {"readOnlyHint": true}},
        {"name": "get_coverage", "description": "What each pipeline stage proves and does not prove; status COVERED, PARTIAL or NOT TESTED.",
         "inputSchema": {"type": "object", "properties": {"target": target_arg()}, "required": ["target"]}, "annotations": {"readOnlyHint": true}},
        {"name": "search_fixes", "description": "Catalogued fixes whose subject contains every query word (case-insensitive) or whose SHA starts with the query. Empty query lists all. Sorted by days, longest first.",
         "inputSchema": {"type": "object", "properties": {"target": target_arg(), "query": {"type": "string"},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}}, "required": ["target"]},
         "annotations": {"readOnlyHint": true}},
        {"name": "get_fix", "description": "One fix by full SHA or unique prefix (7+ hex chars): its Method A row, its Method B sweep if any (else null), and the subject/date of every SHA referenced.",
         "inputSchema": {"type": "object", "properties": {"target": target_arg(), "sha": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"}}, "required": ["target", "sha"]},
         "annotations": {"readOnlyHint": true}}
    ])
}

/// Resolves the `target` argument to a loaded bundle, or explains which targets exist.
fn find<'a>(targets: &'a [Target], args: &Value) -> Result<&'a Target, String> {
    let name = args["target"].as_str().ok_or("missing argument: target")?;
    targets.iter().find(|t| t.name == name)
        .ok_or_else(|| format!("unknown target '{name}'; known: {}", targets.iter().map(|t| t.name.as_str()).collect::<Vec<_>>().join(", ")))
}

/// Commit subject of `sha` from the bundle, or an empty string if absent.
fn subject(t: &Target, sha: &str) -> String {
    t.bundle["commits"][sha]["subject"].as_str().unwrap_or("").to_string()
}

/// `search_fixes`: filters Method A rows by subject words or SHA prefix; longest-lived first.
fn search(t: &Target, args: &Value) -> Result<Value, String> {
    let query = args["query"].as_str().unwrap_or("").trim().to_lowercase();
    let limit = args["limit"].as_u64().unwrap_or(20).clamp(1, 200) as usize;
    let words: Vec<&str> = query.split_whitespace().collect();
    let rows = t.bundle["method_a"].as_array().ok_or("bundle has no method_a array")?;
    let mut hits: Vec<&Value> = rows.iter().filter(|r| {
        let fix = r["fix"].as_str().unwrap_or("");
        let subj = subject(t, fix).to_lowercase();
        words.is_empty() || fix.starts_with(&query) || words.iter().all(|w| subj.contains(w))
    }).collect();
    let days = |r: &Value| r["days"].as_f64().unwrap_or(f64::NEG_INFINITY);
    hits.sort_by(|a, b| days(b).total_cmp(&days(a)).then_with(|| a["fix"].as_str().cmp(&b["fix"].as_str())));
    let total = hits.len();
    let out: Vec<Value> = hits.into_iter().take(limit).map(|r| {
        let fix = r["fix"].as_str().unwrap_or("");
        json!({"fix": fix, "fix_date": r["fix_date"], "subject": subject(t, fix), "days": r["days"],
               "commits_elapsed": r["lifetime"]["commits_elapsed"], "releases_spanned": r["lifetime"]["releases_spanned"],
               "nominees": r["nominees"].as_array().map(|n| n.iter().map(|x| x["sha"].clone()).collect::<Vec<_>>()).unwrap_or_default(),
               "flags": r["flags"]})
    }).collect();
    Ok(json!({"target": t.name, "query": query, "total": total, "returned": out.len(), "fixes": out}))
}

/// `get_fix`: one fix by unique SHA prefix, with its Method B sweep and every referenced commit.
fn get_fix(t: &Target, args: &Value) -> Result<Value, String> {
    let sha = args["sha"].as_str().ok_or("missing argument: sha")?;
    if sha.len() < 7 || sha.len() > 40 || !sha.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("sha must be 7 to 40 lowercase hex characters".into());
    }
    let rows = t.bundle["method_a"].as_array().ok_or("bundle has no method_a array")?;
    let matches: Vec<&Value> = rows.iter().filter(|r| r["fix"].as_str().is_some_and(|f| f.starts_with(sha))).collect();
    let row = match matches[..] {
        [one] => one,
        [] => return Err(format!("no catalogued fix starts with {sha} in target '{}'", t.name)),
        _ => return Err(format!("{sha} matches {} fixes; give more characters", matches.len())),
    };
    let fix = row["fix"].as_str().unwrap_or("");
    let sweep = t.bundle["method_b"].as_array().and_then(|b| b.iter().find(|m| m["fix"] == fix)).cloned().unwrap_or(Value::Null);
    let mut shas = vec![fix.to_string()];
    shas.extend(row["nominees"].as_array().into_iter().flatten().filter_map(|n| n["sha"].as_str().map(String::from)));
    for k in ["first_failing", "last_passing", "method_a_nominee"] {
        if let Some(s) = sweep[k].as_str() { shas.push(s.to_string()); }
    }
    let mut commits = Map::new();
    for s in shas {
        if let Some(c) = t.bundle["commits"].get(&s) { commits.insert(s, c.clone()); }
    }
    Ok(json!({"target": t.name, "method_a": row, "method_b": sweep, "commits": commits}))
}

/// Dispatches a `tools/call` by tool name.
///
/// # Errors
/// Returns a message for the client when the tool or its input is invalid.
pub fn call(targets: &[Target], name: &str, args: &Value) -> Result<Value, String> {
    match name {
        "list_targets" => Ok(json!({"targets": targets.iter().map(|t| json!({"name": t.name, "subject": t.bundle["subject"],
            "schema_version": t.bundle["schema_version"], "bundle_sha256": t.sha256})).collect::<Vec<_>>()})),
        "get_summary" => find(targets, args).map(|t| json!({"target": t.name, "subject": t.bundle["subject"],
            "bundle_sha256": t.sha256, "summary": t.bundle["summary"]})),
        "get_coverage" => find(targets, args).map(|t| json!({"target": t.name, "coverage": t.bundle["coverage"]})),
        "search_fixes" => search(find(targets, args)?, args),
        "get_fix" => get_fix(find(targets, args)?, args),
        other => Err(format!("unknown tool '{other}'")),
    }
}

/// Handle one JSON-RPC message; None for notifications.
pub fn handle(targets: &[Target], msg: &Value) -> Option<Value> {
    let id = msg.get("id").cloned()?;
    let ok = |result: Value| Some(json!({"jsonrpc": "2.0", "id": id, "result": result}));
    let err = |code: i64, message: String| Some(json!({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}));
    match msg["method"].as_str().unwrap_or("") {
        "initialize" => ok(json!({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
            "serverInfo": {"name": "bug-age", "version": env!("CARGO_PKG_VERSION")},
            "instructions": "Read-only facts from bug-age bundles. Every value is copied from bundle.json; cite fix SHAs when you use them."})),
        "ping" => ok(json!({})),
        "tools/list" => ok(json!({"tools": tools()})),
        "tools/call" => {
            let name = msg["params"]["name"].as_str().unwrap_or("");
            let args = msg["params"].get("arguments").cloned().unwrap_or(json!({}));
            match call(targets, name, &args) {
                Ok(v) => ok(json!({"content": [{"type": "text", "text": v.to_string()}], "structuredContent": v, "isError": false})),
                Err(e) => ok(json!({"content": [{"type": "text", "text": e}], "isError": true})),
            }
        }
        m => err(-32601, format!("method not found: {m}")),
    }
}

/// Reads one JSON-RPC message per line from `input` and writes replies to `output` until EOF.
///
/// # Errors
/// Returns an error only when reading input or writing output fails.
pub fn serve(targets: &[Target], input: impl BufRead, mut output: impl Write) -> Result<(), String> {
    for line in input.lines() {
        let line = line.map_err(|e| e.to_string())?;
        if line.trim().is_empty() { continue; }
        let reply = match serde_json::from_str::<Value>(&line) {
            Ok(msg) => handle(targets, &msg),
            Err(e) => Some(json!({"jsonrpc": "2.0", "id": null, "error": {"code": -32700, "message": format!("parse error: {e}")}})),
        };
        if let Some(r) = reply {
            writeln!(output, "{r}").and_then(|_| output.flush()).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}
