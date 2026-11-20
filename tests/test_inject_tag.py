"""inject_tag 的单元测试（只用标准库）。

跑法：
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from install import TAG, inject_tag  # noqa: E402


class TestInjectTag(unittest.TestCase):
    def test_inserts_before_body_close(self):
        html = "<html><body><div>x</div></body></html>"
        out, changed = inject_tag(html)
        self.assertTrue(changed)
        self.assertEqual(out.count(TAG), 1)
        # 标签必须在 </body> 之前
        self.assertLess(out.index(TAG), out.index("</body>"))

    def test_idempotent(self):
        html = "<html><body>x</body></html>"
        once, c1 = inject_tag(html)
        twice, c2 = inject_tag(once)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(twice, once)
        self.assertEqual(twice.count(TAG), 1)

    def test_no_body_tag(self):
        html = "<html><div>x</div></html>"
        out, changed = inject_tag(html)
        self.assertTrue(changed)
        self.assertEqual(out.count(TAG), 1)
        self.assertTrue(out.startswith("<html>"))

    def test_empty_html(self):
        out, changed = inject_tag("")
        self.assertTrue(changed)
        self.assertIn(TAG, out)

    def test_does_not_touch_other_body_occurrences(self):
        # 只替换第一个 </body>
        html = "<body>a</body><body>b</body>"
        out, _ = inject_tag(html)
        self.assertEqual(out.count(TAG), 1)


if __name__ == "__main__":
    unittest.main()