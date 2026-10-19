"""Documentation integrity tests.

Docs rot silently. This project keeps two copies of each SKILL file (repo root
for GitHub readers, .workbuddy/skills/ for WorkBuddy autoload) and links across
several markdown files — all of which break without anyone noticing.

A broken code fence is the worst case: it swallows whole sections into a code
block on GitHub. That actually happened during a README edit, so it is tested.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


MIRRORS = [
    ("SKILL.md", ".workbuddy/skills/mcd-points-rescue/SKILL.md"),
    ("SKILL-lite.md", ".workbuddy/skills/mcd-points-check/SKILL.md"),
]

DOCS = [
    "README.md",
    "docs/USAGE.md",
    "SKILL.md",
    "SKILL-lite.md",
    "MCP_INTEGRATION.md",
    "DESIGN.md",
]


class SkillMirrorTests(unittest.TestCase):
    def test_mirrors_are_byte_identical(self):
        """Two copies exist for two loaders; drift means one of them is stale."""
        for root_rel, mirror_rel in MIRRORS:
            with self.subTest(skill=root_rel):
                root = ROOT / root_rel
                mirror = ROOT / mirror_rel
                self.assertTrue(root.is_file(), f"缺少 {root_rel}")
                self.assertTrue(mirror.is_file(), f"缺少 {mirror_rel}")
                self.assertEqual(
                    root.read_bytes(), mirror.read_bytes(),
                    f"{root_rel} 与 {mirror_rel} 不一致 —— "
                    f"改完根目录那份要同步过去（mcd-points-check 对应 SKILL-lite.md）",
                )


class CodeFenceTests(unittest.TestCase):
    def test_fences_are_balanced(self):
        for rel in DOCS:
            with self.subTest(doc=rel):
                lines = _read(rel).splitlines()
                count = sum(1 for l in lines if l.lstrip().startswith("```"))
                self.assertEqual(
                    count % 2, 0,
                    f"{rel} 的代码块围栏是奇数（{count}），说明有未闭合的块 —— "
                    f"会把后面的正文整段吞进代码块",
                )

    def test_no_unclosed_block_at_eof(self):
        for rel in DOCS:
            with self.subTest(doc=rel):
                in_code = False
                for line in _read(rel).splitlines():
                    if line.lstrip().startswith("```"):
                        in_code = not in_code
                self.assertFalse(in_code, f"{rel} 末尾仍有未闭合的代码块")


class LinkTests(unittest.TestCase):
    MD_LINK = re.compile(r"\]\(([^)]+)\)")

    def test_relative_markdown_links_resolve(self):
        for rel in ("README.md", "docs/USAGE.md"):
            base = (ROOT / rel).parent
            with self.subTest(doc=rel):
                for target in self.MD_LINK.findall(_read(rel)):
                    if target.startswith(("http://", "https://", "#", "mailto:")):
                        continue
                    path = target.split("#")[0]
                    if not path:
                        continue
                    self.assertTrue(
                        (base / path).resolve().exists(),
                        f"{rel} 里的链接失效：{target}",
                    )

    def test_readme_images_exist(self):
        for src in re.findall(r'<img src="([^"]+)"', _read("README.md")):
            if src.startswith(("http://", "https://")):
                continue
            self.assertTrue((ROOT / src).is_file(), f"README 图片缺失：{src}")


class RequiredFilesTests(unittest.TestCase):
    """The contest requires four specific file names; renaming one disqualifies."""

    REQUIRED = [
        "README.md",
        "CONTEST_DECLARATION.md",
        "MCP_INTEGRATION.md",
        "mcp-config.example.json",
        "workbuddy.md",
    ]

    def test_contest_files_present(self):
        for name in self.REQUIRED:
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file(), f"参赛必需文件缺失：{name}")

    def test_declaration_unmodified(self):
        """Official template says this file must not be altered."""
        text = _read("CONTEST_DECLARATION.md")
        for marker in ("# 参赛声明", "## 原创性声明", "## 合规声明",
                       "## 信息安全声明", "## 规则遵守声明"):
            self.assertIn(marker, text, f"参赛声明被改动，缺少 {marker}")


if __name__ == "__main__":
    unittest.main()
