#!/usr/bin/env python3
"""
One version, in one place.

The number used to live in three hand-maintained copies — `config.py`,
`frontend/package.json` and a constant in the navbar — and nothing read the
Python one. Keeping three in step by hand is not a discipline anybody sustains,
so it drifted and then stopped being updated at all.

`VERSION` at the repository root is now the only place it is written. These
tests fail the build if a second copy reappears or falls behind, which is the
only thing that makes a single source actually single.
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import config

VERSION_FILE = REPO_ROOT / 'VERSION'
SEMVER = re.compile(r'^\d+\.\d+\.\d+$')


class VersionIsSingleSourced(unittest.TestCase):
    def setUp(self):
        self.version = VERSION_FILE.read_text(encoding='utf-8').strip()

    def test_the_version_file_holds_one_plain_semver(self):
        self.assertTrue(
            SEMVER.match(self.version),
            f"VERSION should read like 2.2.0, got {self.version!r}",
        )

    def test_the_backend_reports_what_the_version_file_says(self):
        self.assertEqual(config.APP_VERSION, self.version)

    def test_the_frontend_package_matches(self):
        package = json.loads((REPO_ROOT / 'frontend/package.json').read_text(encoding='utf-8'))
        self.assertEqual(
            package['version'], self.version,
            'frontend/package.json has fallen behind VERSION — bump both, or the '
            'installed package claims a release it is not',
        )

    def test_the_lockfile_matches(self):
        lock = json.loads((REPO_ROOT / 'frontend/package-lock.json').read_text(encoding='utf-8'))
        self.assertEqual(lock['version'], self.version)
        self.assertEqual(lock['packages']['']['version'], self.version)

    def test_no_source_file_hard_codes_a_version_again(self):
        """
        The failure this whole arrangement exists to prevent.

        A literal `2.1.4`-shaped string in the application source means someone
        has made a fourth copy, and it will be the one on screen while every
        other copy moves on without it.
        """
        literal = re.compile(r'["\']v?\d+\.\d+\.\d+["\']')
        searched = [
            *(REPO_ROOT / 'frontend/src').rglob('*.ts'),
            *(REPO_ROOT / 'frontend/src').rglob('*.tsx'),
            REPO_ROOT / 'config.py',
            # The build reads VERSION; a literal here would be baked into every
            # bundle and outrank the file it is supposed to be reading.
            REPO_ROOT / 'frontend/vite.config.ts',
        ]
        offenders = []
        for path in searched:
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                # A version-shaped string is only suspicious next to the word
                # version; `"1.0.0"` in an unrelated context is not this bug.
                if literal.search(line) and 'version' in line.lower():
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")

        self.assertEqual(
            offenders, [],
            'the version is written in VERSION and read from there — '
            'these lines hard-code it instead:\n' + '\n'.join(offenders),
        )


class VersionSurvivesABadFile(unittest.TestCase):
    """Reading it must never be the reason the application will not start."""

    def test_a_missing_version_file_reads_as_unknown(self):
        with patch.object(config, '_VERSION_FILE', REPO_ROOT / 'VERSION-does-not-exist'):
            self.assertEqual(config._read_version(), 'unknown')

    def test_an_empty_version_file_reads_as_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / 'VERSION'
            empty.write_text('   \n', encoding='utf-8')
            with patch.object(config, '_VERSION_FILE', empty):
                self.assertEqual(config._read_version(), 'unknown')

if __name__ == '__main__':
    unittest.main()
