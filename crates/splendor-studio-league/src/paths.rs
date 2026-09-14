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

use crate::{
    STUDIO_LEAGUE_DB_NAME, STUDIO_LEAGUE_DIR, STUDIO_LEAGUE_IDENTITY_NAME,
    STUDIO_LEAGUE_REPLAY_DIR_NAME,
};

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
        assert_eq!(
            paths.replay_root(),
            Path::new(STUDIO_LEAGUE_DIR).join(STUDIO_LEAGUE_REPLAY_DIR_NAME)
        );
        assert!(paths.db().is_relative());
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
