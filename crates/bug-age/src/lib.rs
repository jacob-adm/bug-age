//! # bug-age
//!
//! Measures how long bugs lived in a git repository, using only repository data.
//!
//! bug-age does not discover new bugs. It starts from bugs the project already fixed:
//!
//! 1. [`catalog`] lists the commits whose subject says they fix something (rule-based, auditable).
//! 2. [`szz`] (Method A) blames the lines each fix changed to nominate the commit that introduced
//!    the bug, then measures the time, commits, releases and churn in between.
//! 3. [`sweep`] (Method B) replays a regression test for one bug across history, using a
//!    [`runner`], to find the first commit where the bug's behaviour appears.
//! 4. [`bundle`] assembles everything into one blameless, schema-validated JSON file.
//! 5. [`explorer`] packages bundles into a static page; [`mcp`] serves bundle facts to agents.
//!
//! Every number is computed by this crate or its scripts. No model produces or alters a metric.

/// Fix-commit catalog: which commits count as bug fixes, and why the others were excluded.
pub mod catalog;
/// The single entry point for running `git`; isolates bug-age from the caller's git environment.
pub mod git;
/// Method A: blame-based introducer nomination and bug lifetime measurement.
pub mod szz;
/// Executes a build/test step at one commit, locally or in an isolated Docker container.
pub mod runner;
/// Method B: searches history for the first commit where a regression test fails.
pub mod sweep;
/// Builds the canonical bundle, its summary statistics, coverage report and blameless gate.
pub mod bundle;
/// Assembles the static explorer page and its per-target data files, with a size gate.
pub mod explorer;
/// Read-only MCP server (JSON-RPC over stdio) answering questions from bundles.
pub mod mcp;
