"""发布清单回归测试:index.html 引用到的每个本地资源,都必须被 publish_viewer.sh 覆盖。

背景:线上曾出现过"index.html 已引用 markdown.js / vendor/katex,但发布清单没包含它们"
的隐患——一旦先发布 HTML 再补文件,站点就会在两步之间 404 白屏。这个测试把它变成硬约束。

运行:python3 -m unittest tests.test_publish_manifest
"""
import re
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VIEWER = BASE / "viewer"
PUBLISH_SCRIPT = BASE / "scripts" / "publish_viewer.sh"


class TestPublishManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = PUBLISH_SCRIPT.read_text(encoding="utf-8")
        self.html = (VIEWER / "index.html").read_text(encoding="utf-8")

    def _local_refs(self):
        refs = set(re.findall(r'(?:src|href)="([^"]+)"', self.html))
        return {
            r for r in refs
            if not r.startswith(("http://", "https://", "//", "data:", "#"))
        }

    def test_every_referenced_asset_is_in_publish_list(self):
        missing = []
        for ref in sorted(self._local_refs()):
            candidates = {ref, f"viewer/{ref}", f"viewer/{ref.split('/')[0]}"}
            if not any(c in self.manifest for c in candidates):
                missing.append(ref)
        self.assertEqual(
            missing, [],
            "这些 index.html 引用到的资源没有被 publish_viewer.sh 纳入发布清单:"
            f" {missing}",
        )

    def test_referenced_files_exist_on_disk(self):
        missing = [r for r in sorted(self._local_refs()) if not (VIEWER / r).exists()]
        self.assertEqual(missing, [], f"index.html 引用了本地不存在的文件: {missing}")

    def test_publish_list_still_guards_pending_state(self):
        # 发布前的 pending_llm_ids.txt 守卫不能被误删
        self.assertIn("pending_llm_ids.txt", self.manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
