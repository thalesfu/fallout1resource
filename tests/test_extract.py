from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fallout1resource.extract import ExtractionError, build_extraction_plan, execute_extraction
from test_dat1 import build_dat1


class ExtractionTests(unittest.TestCase):
    def _game(self, root: Path) -> Path:
        game_dir = root / "Fallout"
        game_dir.mkdir()
        build_dat1(game_dir / "MASTER.DAT")
        build_dat1(game_dir / "CRITTER.DAT")
        return game_dir

    def test_requires_explicit_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(ExtractionError):
                build_extraction_plan(self._game(root), root / "workspace")

    def test_dry_plan_creates_no_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            plan = build_extraction_plan(
                self._game(root),
                workspace,
                paths=["TEXT/ENGLISH/DIALOG/HAROLD.MSG"],
                archives=["MASTER.DAT"],
            )
            self.assertEqual(len(plan), 1)
            self.assertFalse(workspace.exists())

    def test_extracts_uncompressed_and_lzss_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            plan = build_extraction_plan(
                self._game(root),
                workspace,
                extensions=[".msg", ".txt"],
                archives=["MASTER.DAT"],
            )
            results = execute_extraction(plan, workspace)
            contents = {result.internal_path: result.target_path.read_bytes() for result in results}
            self.assertEqual(contents["text/english/dialog/HAROLD.MSG"], b"hello")
            self.assertEqual(contents["text/english/dialog/README.TXT"], b"xyz")

    def test_refuses_overwrite_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            game_dir = self._game(root)
            plan = build_extraction_plan(
                game_dir,
                workspace,
                paths=["text/english/dialog/HAROLD.MSG"],
                archives=["MASTER.DAT"],
            )
            execute_extraction(plan, workspace)
            target = plan[0].target_path
            target.write_bytes(b"user content")
            with self.assertRaises(ExtractionError):
                execute_extraction(plan, workspace)
            self.assertEqual(target.read_bytes(), b"user content")

    def test_explicit_overwrite_replaces_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            game_dir = self._game(root)
            plan = build_extraction_plan(
                game_dir,
                workspace,
                paths=["text/english/dialog/HAROLD.MSG"],
                archives=["MASTER.DAT"],
            )
            plan[0].target_path.parent.mkdir(parents=True)
            plan[0].target_path.write_bytes(b"old")
            execute_extraction(plan, workspace, overwrite=True)
            self.assertEqual(plan[0].target_path.read_bytes(), b"hello")

    def test_rejects_source_changed_after_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            game_dir = self._game(root)
            plan = build_extraction_plan(
                game_dir,
                workspace,
                paths=["text/english/dialog/HAROLD.MSG"],
                archives=["MASTER.DAT"],
            )
            with (game_dir / "MASTER.DAT").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaises(ExtractionError):
                execute_extraction(plan, workspace)
            self.assertFalse(plan[0].target_path.exists())

    def test_rejects_parent_traversal_from_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_dir = root / "Fallout"
            game_dir.mkdir()
            build_dat1(game_dir / "MASTER.DAT", directory="..\\outside")
            build_dat1(game_dir / "CRITTER.DAT")
            with self.assertRaises(ExtractionError):
                build_extraction_plan(
                    game_dir,
                    root / "workspace",
                    paths=["../outside/HAROLD.MSG"],
                    archives=["MASTER.DAT"],
                )

    def test_rejects_symlink_escape_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            outside = root / "outside"
            outside.mkdir()
            raw = workspace / "raw"
            raw.mkdir(parents=True)
            try:
                (raw / "master").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            with self.assertRaises(ValueError):
                build_extraction_plan(
                    self._game(root),
                    workspace,
                    paths=["text/english/dialog/HAROLD.MSG"],
                    archives=["MASTER.DAT"],
                )


if __name__ == "__main__":
    unittest.main()
