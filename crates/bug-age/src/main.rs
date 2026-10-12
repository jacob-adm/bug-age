//! bug-age CLI entry point. Subcommands land with their tickets; for now only
//! `--version` and `--help` are implemented.

use std::process::ExitCode;

const USAGE: &str = "usage: bug-age [--version | --help]";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--version") | Some("-V") => {
            println!("bug-age {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        None | Some("--help") | Some("-h") => {
            println!("{USAGE}");
            ExitCode::SUCCESS
        }
        Some(other) => {
            eprintln!("bug-age: unknown argument '{other}'\n{USAGE}");
            ExitCode::from(2)
        }
    }
}
