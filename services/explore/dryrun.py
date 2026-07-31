#!/usr/bin/env python3
"""
Dry run — ask rsync what it would actually do, and say it in plain words.

The plan is worked out from a comparison of the two file listings. That is a
good answer, but it is our answer. A dry run puts the same file list, the same
flags and the same destination in front of the real rsync with `--dry-run`, and
reports what it says back. If the two disagree, the plan is wrong and you find
out before anything moves.

rsync is asked for `--out-format=%i|%l|%n`, which gives one line per item:

    >f+++++++++|4823891234|Season 01/Show - S01E01 - Pilot.mkv
    >f..t......|2311885320|Season 01/Show - S01E02 - Second.mkv
    .f         |1998221114|Season 01/Show - S01E03 - Third.mkv
    cd+++++++++|0         |Season 02/

The first field is the itemised change string, and it is the whole point:

    position 0   update kind — `>` received, `<` sent, `c` created locally,
                 `.` no update at all, `*` a message such as `*deleting`
    position 1   file kind — `f` file, `d` directory, `L` symlink
    positions 2+ which attributes differ: c s t p o g u a x, or `+` for every
                 one of them, which is rsync's way of saying "brand new"

So `>f+++++++++` is a new file arriving, `>f..t......` is an existing file being
replaced, and a leading `.` with no `+` is a file rsync would leave alone.

Only `%n` may contain the separator, so every line is split from the left with
at most two splits and the name keeps whatever is in it.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# What we tell the operator, rather than what rsync calls it.
NEW = 'new'            # not there now, would arrive
REPLACED = 'replaced'  # there now, would be overwritten
UNCHANGED = 'unchanged'
DELETED = 'deleted'    # rsync would remove it (never used by Explore's flags)
DIRECTORY = 'directory'

MEDIA_SUFFIXES = ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.ts', '.wmv', '.mpg', '.mpeg')


@dataclass
class DryRunFile:
    change: str
    rel: str
    size: int
    itemize: str = ''

    @property
    def is_media(self) -> bool:
        return self.rel.lower().endswith(MEDIA_SUFFIXES)

    def to_dict(self) -> Dict:
        return {
            'change': self.change,
            'rel': self.rel,
            'size': self.size,
            'itemize': self.itemize,
            'is_media': self.is_media,
        }


@dataclass
class DryRunReport:
    ok: bool = True
    ran: bool = True
    exit_code: int = 0
    error: Optional[str] = None
    duration_ms: int = 0
    files: List[DryRunFile] = field(default_factory=list)
    # Actions the plan performs itself, which rsync never sees: local files
    # moved to backup before the transfer starts.
    backups: List[Dict] = field(default_factory=list)
    removals: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_tail: str = ''

    def _of(self, change: str) -> List[DryRunFile]:
        return [f for f in self.files if f.change == change]

    @property
    def incoming_bytes(self) -> int:
        return sum(f.size for f in self.files if f.change in (NEW, REPLACED))

    def summary(self) -> Dict:
        new, replaced = self._of(NEW), self._of(REPLACED)
        return {
            'new': len(new),
            'replaced': len(replaced),
            'unchanged': len(self._of(UNCHANGED)),
            'directories': len(self._of(DIRECTORY)),
            'deleted': len(self._of(DELETED)),
            'backed_up': len(self.backups),
            'removed': len(self.removals),
            'incoming_bytes': self.incoming_bytes,
            'backup_bytes': sum(int(b.get('local_size') or 0) for b in self.backups),
            'removed_bytes': sum(int(r.get('local_size') or 0) for r in self.removals),
            'media_new': len([f for f in new if f.is_media]),
            'media_replaced': len([f for f in replaced if f.is_media]),
        }

    def verdict(self) -> str:
        """
        One sentence about what would happen to the files on this machine.

        A replacement already implies its backup, so the two are never counted
        separately — "2 replaced, 2 backed up" reads as four files.
        """
        if not self.ok:
            return self.error or 'The dry run could not be completed.'

        counts = self.summary()
        parts = []
        if counts['new']:
            parts.append(f"{counts['new']} file(s) would be downloaded")
        if counts['replaced']:
            parts.append(f"{counts['replaced']} would be replaced, "
                         'with the current copy backed up first')
        if counts['removed']:
            parts.append(f"{counts['removed']} would be moved to backup and removed")

        if not parts:
            return 'Nothing would change — the local copy already matches the remote.'

        sentence = ', '.join(parts) + '.'
        if not self.ran:
            # rsync was never asked, because there is nothing to transfer.
            return f"Nothing would be downloaded. {sentence[0].upper()}{sentence[1:]}"
        return f"rsync agrees: {sentence}"

    def to_dict(self) -> Dict:
        return {
            'ok': self.ok,
            'ran': self.ran,
            'exit_code': self.exit_code,
            'error': self.error,
            'duration_ms': self.duration_ms,
            'verdict': self.verdict(),
            'summary': self.summary(),
            'files': [f.to_dict() for f in self.files],
            'backups': self.backups,
            'removals': self.removals,
            'warnings': self.warnings,
            'raw_tail': self.raw_tail,
        }


def classify(itemize: str) -> Optional[str]:
    """
    Turn one itemised change string into the word we show.

    Returns None for lines that are not an item at all (rsync's banner, the
    --stats block, "sending incremental file list", blank lines).
    """
    code = itemize.strip()
    if not code:
        return None

    if code.startswith('*'):
        # `*deleting` is the only message Explore could ever see; anything else
        # in this family is still a removal from the destination's point of view.
        return DELETED if 'deleting' in code else None

    if len(code) < 2 or code[0] not in '<>ch.':
        return None

    kind = code[1]
    attrs = code[2:]

    if kind == 'd':
        return DIRECTORY
    if kind not in 'fLDS':
        return None

    if '+' in attrs:
        return NEW
    if code[0] == '.' and not attrs.strip('. '):
        return UNCHANGED
    if attrs.strip('. '):
        return REPLACED
    return UNCHANGED


def parse(output: str) -> List[DryRunFile]:
    """Read the `%i|%l|%n` lines out of rsync's output, ignoring the rest."""
    files: List[DryRunFile] = []
    for line in output.splitlines():
        if '|' not in line:
            continue
        itemize, _, rest = line.partition('|')
        size_text, _, rel = rest.partition('|')
        if not rel:
            continue
        change = classify(itemize)
        if change is None:
            continue
        try:
            size = int(size_text.strip().replace(',', ''))
        except ValueError:
            size = 0
        files.append(DryRunFile(change=change, rel=rel.rstrip('\r'),
                                size=size, itemize=itemize.strip()))
    return files


def reconcile(report: 'DryRunReport', planned: Dict[str, int],
              superseded: Dict[str, int]) -> None:
    """
    Hold rsync's answer against the plan's, and report where they differ.

    The two are asked at different moments, and one gap is expected: the real
    run moves every superseded local file into backup BEFORE rsync starts, so
    rsync — asked now, with those files still in place — says there is nothing
    to do for them. Those are folded back in as replacements rather than left
    invisible, which would read as "this file is safe" about a file that is
    about to be overwritten.

    Any other disagreement is a real one and becomes a warning:

      * a planned file rsync would skip, and the plan does not back up —
        the plan believes it is missing and rsync can see it is not
      * a file rsync would move that the plan never listed — impossible with
        --files-from, and worth shouting about if it ever happens

    `planned` and `superseded` map a remote-relative path to its size.
    """
    seen = {f.rel for f in report.files}

    for rel, size in planned.items():
        if rel in seen:
            continue
        if rel in superseded:
            report.files.append(DryRunFile(
                change=REPLACED, rel=rel, size=size,
                itemize='after-backup',
            ))
        else:
            report.warnings.append(
                f"rsync would skip “{rel}” — an identical file is already there."
            )

    for file in report.files:
        if file.change in (NEW, REPLACED) and file.rel not in planned:
            report.warnings.append(
                f"rsync would move “{file.rel}”, which is not in the approved plan."
            )


def tail(output: str, lines: int = 12) -> str:
    """The last few lines, which is where rsync puts --stats and any error."""
    kept = [line for line in output.splitlines() if line.strip() and '|' not in line]
    return '\n'.join(kept[-lines:])
