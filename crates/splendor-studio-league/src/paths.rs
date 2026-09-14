//! Where a Studio League installation lives on disk.
//!
//! Every protocol path — the derived index database, the durable identity
//! manifest, and the content-addressed replay archive — is derived from **one**
//! resolved root by [`StudioLeaguePathsV1::from_root`]. Nothing else in the
//! crate composes a league path, so the three locations cannot drift apart and
//! there is exactly one place where "relative to what?" is answered.
//!
//! # Why this type exists
//!
//! The three locations used to be three parallel string literals that merely
//! repeated a shared prefix:
//!
//! ```text
//! local-artifacts/studio-league/league.sqlite3
//! local-artifacts/studio-league/identity.json
//! local-artifacts/studio-league/replays
//! ```
//!
//! Nothing enforced the prefix, and the replay root in particular could only
//! ever mean "that literal, resolved against whatever the process working
//! directory happens to be". A launcher, a future replay reader and the CLI all
//! need the same answer, so the relation is now a type instead of a convention.
//!
//! # Scope
//!
//! This module moves *where paths come from*; it does not change the layout, the
//! ledger, or any authority. An existing database and archive stay valid in
//! place because [`from_root`](StudioLeaguePathsV1::from_root) composes exactly
//! the same layout inside the root.

use std::path::{Path, PathBuf};

use crate::error::StudioLeagueError;

/// The single root-relative directory every league path derives from.
///
/// Private on purpose. These four names are the layout; exposing them would give
/// an external crate a second, equally official way to answer "relative to
/// what?" — one that composes a league path without ever mentioning
/// [`StudioLeaguePathsV1`]. The supported way to locate a league is
/// `StudioLeaguePathsV1::resolve(..)` followed by `db()` / `identity()` /
/// `replay_root()`.
const STUDIO_LEAGUE_DIR: &str = "local-artifacts/studio-league";
/// File name of the derived index database inside [`STUDIO_LEAGUE_DIR`].
const STUDIO_LEAGUE_DB_NAME: &str = "league.sqlite3";
/// File name of the durable identity manifest inside [`STUDIO_LEAGUE_DIR`].
const STUDIO_LEAGUE_IDENTITY_NAME: &str = "identity.json";
/// Directory name of the content-addressed replay archive inside
/// [`STUDIO_LEAGUE_DIR`] (`<document sha256>.json`).
const STUDIO_LEAGUE_REPLAY_DIR_NAME: &str = "replays";

/// Directory name of the per-occurrence evidence slots inside
/// [`STUDIO_LEAGUE_DIR`] (`occurrences/<occurrence id>/`).
const STUDIO_LEAGUE_OCCURRENCE_DIR_NAME: &str = "occurrences";

/// The longest occurrence id the composer will turn into a path component.
///
/// Bounded because the id arrives from outside the process (a CLI argument or an
/// HTTP body) and because every filesystem has a component limit; 128 bytes is
/// far above any real id and far below any platform's.
const MAX_OCCURRENCE_ID_BYTES: usize = 128;

/// The resolved on-disk locations of one Studio League installation.
///
/// Constructed only by [`from_root`](Self::from_root) /
/// [`resolve`](Self::resolve); read through the accessors. There is deliberately
/// no way to set one path without the others, because a league whose database
/// and archive root were chosen independently is exactly the state this type
/// exists to prevent.
#[derive(Debug, Clone)]
pub struct StudioLeaguePathsV1 {
    root: PathBuf,
    dir: PathBuf,
    db: PathBuf,
    identity: PathBuf,
    replay_root: PathBuf,
}

impl StudioLeaguePathsV1 {
    /// Derive every league path from one explicit root.
    ///
    /// `root` may be absolute or relative. When it is empty the paths are the
    /// bare protocol-relative ones, which is how the process resolved them
    /// before this type existed; that is what [`resolve`](Self::resolve) uses
    /// for its default so the change is behaviour-preserving.
    pub fn from_root(root: impl AsRef<Path>) -> Self {
        let root = root.as_ref().to_path_buf();
        let dir = root.join(STUDIO_LEAGUE_DIR);
        let db = dir.join(STUDIO_LEAGUE_DB_NAME);
        let identity = dir.join(STUDIO_LEAGUE_IDENTITY_NAME);
        let replay_root = dir.join(STUDIO_LEAGUE_REPLAY_DIR_NAME);
        Self {
            root,
            dir,
            db,
            identity,
            replay_root,
        }
    }

    /// Resolve the league locations once, at the boundary.
    ///
    /// `Some(root)` derives everything from that root. `None` keeps the
    /// historical behaviour of resolving the protocol-relative paths against the
    /// process working directory, byte for byte, so callers that do not care
    /// about the root see no change.
    ///
    /// Automatic discovery (walking up to a project marker) is deliberately not
    /// implemented here: choosing the root is the launcher's decision, and this
    /// method only makes it expressible.
    pub fn resolve(explicit: Option<&Path>) -> Self {
        match explicit {
            Some(root) => Self::from_root(root),
            None => Self::from_root(Path::new("")),
        }
    }

    /// The root everything was derived from; empty means "the process working
    /// directory" (see [`resolve`](Self::resolve)).
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// The Studio League directory itself: `root/<protocol dir>`.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    /// The derived index database. Rebuildable state.
    pub fn db(&self) -> &Path {
        &self.db
    }

    /// The durable identity manifest. Must exist before a completion session can
    /// be opened; it is never regenerated silently.
    pub fn identity(&self) -> &Path {
        &self.identity
    }

    /// The content-addressed replay archive root. The ledger stores only
    /// content-relative paths, so this is the only thing needed to locate a
    /// recorded replay document.
    pub fn replay_root(&self) -> &Path {
        &self.replay_root
    }

    /// The evidence slot of one occurrence: `dir()/occurrences/<occurrence_id>`.
    ///
    /// The id is validated **here**, by the one composer, before it can become a
    /// path component. A client-supplied string that reaches `Path::join`
    /// unchecked is a directory-traversal primitive, and the check must not live
    /// in whichever caller happens to sit nearest the network. The rule is
    /// deliberately narrow and cross-platform:
    ///
    /// * non-empty, and at most [`MAX_OCCURRENCE_ID_BYTES`] bytes;
    /// * not `.` and not `..`;
    /// * no leading or trailing `.` — Win32 silently strips a trailing dot, so
    ///   `x.` and `x` would address the same slot;
    /// * every byte in `[A-Za-z0-9._-]`.
    ///
    /// The charset is what carries the weight: it excludes both path separators,
    /// the Windows `:` volume separator, NUL and every control character, and it
    /// keeps the rule identical on every platform rather than compiling a
    /// different one per target.
    ///
    /// Two residual hazards are accepted rather than papered over. A
    /// case-insensitive filesystem folds ids that differ only in case onto one
    /// slot, and a Windows reserved device name (`CON`, `LPT1`) is refused by the
    /// filesystem rather than by this rule. A name the filesystem rejects surfaces
    /// as an I/O error, and a folded id is refused as a conflict: the slot's
    /// evidence names its own occurrence id, and a caller that locates a slot by id
    /// gets a mismatch error rather than another occurrence's recorded fact (see
    /// the Studio League Host documentation). An occurrence id is an occurrence's
    /// *identity*, not a per-request token.
    pub fn occurrence_dir(&self, occurrence_id: &str) -> Result<PathBuf, StudioLeagueError> {
        validate_occurrence_id(occurrence_id)?;
        Ok(self
            .dir
            .join(STUDIO_LEAGUE_OCCURRENCE_DIR_NAME)
            .join(occurrence_id))
    }
}

/// The occurrence-id rule documented on
/// [`StudioLeaguePathsV1::occurrence_dir`].
fn validate_occurrence_id(occurrence_id: &str) -> Result<(), StudioLeagueError> {
    let reject = |why: &str| {
        Err(StudioLeagueError::Invalid(format!(
            "unsafe occurrence id `{occurrence_id}`: {why}"
        )))
    };
    if occurrence_id.is_empty() {
        return reject("it is empty");
    }
    if occurrence_id.len() > MAX_OCCURRENCE_ID_BYTES {
        return reject("it is longer than the protocol allows");
    }
    if occurrence_id == "." || occurrence_id == ".." {
        return reject("it is a relative path component");
    }
    if occurrence_id.starts_with('.') || occurrence_id.ends_with('.') {
        return reject("it starts or ends with a dot");
    }
    if let Some(byte) = occurrence_id
        .bytes()
        .find(|byte| !matches!(byte, b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'.' | b'_' | b'-'))
    {
        return reject(&format!(
            "it contains `{}`, which is outside `[A-Za-z0-9._-]`",
            char::from(byte).escape_default()
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_protocol_paths_derive_from_one_root() {
        let paths = StudioLeaguePathsV1::from_root("/srv/league");
        assert_eq!(
            paths.dir(),
            Path::new("/srv/league").join(STUDIO_LEAGUE_DIR).as_path()
        );
        assert_eq!(paths.db(), paths.dir().join(STUDIO_LEAGUE_DB_NAME));
        assert_eq!(
            paths.identity(),
            paths.dir().join(STUDIO_LEAGUE_IDENTITY_NAME)
        );
        assert_eq!(
            paths.replay_root(),
            paths.dir().join(STUDIO_LEAGUE_REPLAY_DIR_NAME)
        );
        assert_eq!(paths.root(), Path::new("/srv/league"));
    }

    #[test]
    fn the_default_resolution_is_the_bare_protocol_relative_layout() {
        // This is the behaviour every existing artifact and test depends on:
        // `None` must reproduce the historical relative paths exactly, with no
        // `.` or cwd prefix leaking into them.
        let paths = StudioLeaguePathsV1::resolve(None);
        assert_eq!(paths.dir(), Path::new(STUDIO_LEAGUE_DIR));
        assert_eq!(
            paths.db(),
            Path::new(STUDIO_LEAGUE_DIR).join(STUDIO_LEAGUE_DB_NAME)
        );
        // The identity manifest is pinned here too. It is the leaf that used to
        // have a second, independently public definition (the deleted
        // `DEFAULT_IDENTITY_MANIFEST_PATH`), so the default layout is asserted
        // for all three locations rather than only for the database and archive.
        assert_eq!(
            paths.identity(),
            Path::new(STUDIO_LEAGUE_DIR).join(STUDIO_LEAGUE_IDENTITY_NAME)
        );
        assert_eq!(
            paths.replay_root(),
            Path::new(STUDIO_LEAGUE_DIR).join(STUDIO_LEAGUE_REPLAY_DIR_NAME)
        );
        assert!(paths.db().is_relative());
        assert!(paths.identity().is_relative());
        assert!(paths.replay_root().is_relative());
    }

    #[test]
    fn one_occurrence_slot_lives_under_the_league_dir() {
        let paths = StudioLeaguePathsV1::from_root("/srv/league");
        let dir = paths
            .occurrence_dir("run-001")
            .expect("a safe id is accepted");
        assert_eq!(
            dir,
            paths
                .dir()
                .join(STUDIO_LEAGUE_OCCURRENCE_DIR_NAME)
                .join("run-001")
        );
        // A sibling of the archive root, never inside it: occurrence evidence and
        // archived replay documents are different authorities.
        assert!(dir.starts_with(paths.dir()));
        assert!(!dir.starts_with(paths.replay_root()));
    }

    #[test]
    fn an_occurrence_id_can_never_address_anything_but_its_own_slot() {
        // Every one of these is a real way to escape, alias or break a path
        // component, so each must be refused by the composer before any caller can
        // join it.
        let too_long = "x".repeat(MAX_OCCURRENCE_ID_BYTES + 1);
        let unsafe_ids = [
            "",
            ".",
            "..",
            "...",
            ".hidden",
            "trailing.",
            "a/b",
            r"a\b",
            "a:b",
            "C:",
            r"C:\league",
            "/etc/passwd",
            r"..\escape",
            "a\u{0}b",
            "a\nb",
            "a\u{7f}b",
            "a b",
            "h\u{e9}llo",
            too_long.as_str(),
        ];
        for unsafe_id in unsafe_ids {
            let error = paths()
                .occurrence_dir(unsafe_id)
                .expect_err("an unsafe occurrence id must be refused");
            assert!(
                matches!(error, StudioLeagueError::Invalid(_)),
                "`{unsafe_id}` should be an Invalid error, got {error:?}"
            );
        }
    }

    #[test]
    fn the_charset_admits_every_id_the_protocol_actually_uses() {
        // The rule must not be so tight that a legitimate id becomes unusable.
        for good in [
            "a",
            "run-001",
            "s15.selfplay_0001",
            "20260915T101500Z-4f9a",
            "a.b.c",
            "A.B_c-9",
        ] {
            assert!(paths().occurrence_dir(good).is_ok(), "`{good}` was refused");
        }
    }

    /// The default (cwd-relative) resolution: the id rule is independent of the
    /// root, so these unit tests need no real filesystem.
    fn paths() -> StudioLeaguePathsV1 {
        StudioLeaguePathsV1::resolve(None)
    }

    #[test]
    fn an_explicit_root_wins_over_the_default() {
        let explicit = Path::new("/tmp/scratch-root");
        let paths = StudioLeaguePathsV1::resolve(Some(explicit));
        assert_eq!(paths.root(), explicit);
        assert!(paths.db().starts_with(explicit));
        assert!(paths.replay_root().starts_with(explicit));
    }
}
