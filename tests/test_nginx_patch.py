"""nginx 配置改写逻辑的单元测试（纯字符串，不需要 docker / nginx）。

跑法：
    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from install import (  # noqa: E402
    BEGIN,
    END,
    URL_PATH,
    find_server,
    locate_conf,
    patch_conf,
    server_blocks,
    strip_managed,
)

SAMPLE = """server {
    listen 80;
    server_name example.com;
    location / {
        proxy_pass http://127.0.0.1:9999;
    }
}

server {
    listen 8080;
    server_name panel.example.com;
    client_max_body_size 64m;

    location / {
        proxy_pass http://127.0.0.1:1234;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_buffering on;
    }
}
"""

PATCHED_EXPECTED_ORDER = ("location = /bulk-import.js", "sub_filter")


class TestServerBlocks(unittest.TestCase):
    def test_counts_two_servers(self):
        self.assertEqual(len(server_blocks(SAMPLE)), 2)

    def test_find_server_by_port(self):
        found = find_server(SAMPLE, 1234)
        self.assertIsNotNone(found)
        self.assertNotIn("9999", SAMPLE[found[0]:found[1]])

    def test_find_server_missing_port(self):
        self.assertIsNone(find_server(SAMPLE, 4321))


class TestPatch(unittest.TestCase):
    def patched(self):
        out, notes = patch_conf(SAMPLE, 1234, "/srv/conf/bulk-import/bulk-import.js")
        self.assertTrue(notes)
        return out

    def test_static_location_inserted(self):
        out = self.patched()
        self.assertIn("location = %s {" % URL_PATH, out)
        self.assertIn("alias /srv/conf/bulk-import/bulk-import.js;", out)
        self.assertIn("default_type application/javascript;", out)

    def test_script_tag_injection_present(self):
        out = self.patched()
        self.assertIn("sub_filter '</body>' '<script src=\"bulk-import.js\"></script></body>';", out)
        self.assertIn("sub_filter_once on;", out)

    def test_accept_encoding_added_once(self):
        out = self.patched()
        self.assertEqual(out.count('proxy_set_header Accept-Encoding "";'), 1)

    def test_keeps_existing_accept_encoding(self):
        src = SAMPLE.replace(
            "        proxy_set_header Host $host;",
            '        proxy_set_header Accept-Encoding "";\n        proxy_set_header Host $host;',
            1,
        )
        out, _ = patch_conf(src, 1234, "/tmp/x.js")
        self.assertEqual(out.count('proxy_set_header Accept-Encoding "";'), 1)

    def test_managed_block_lands_inside_target_server(self):
        out = self.patched()
        idx = out.index(BEGIN)
        first_server_end = out.index("}\n\nserver {")
        self.assertGreater(idx, first_server_end)

    def test_idempotent(self):
        once = self.patched()
        twice, notes = patch_conf(once, 1234, "/srv/conf/bulk-import/bulk-import.js")
        # 两个标记块：server 级静态位置 + location / 内的注入
        self.assertEqual(twice.count(BEGIN), 2)
        self.assertEqual(twice.count(BEGIN), once.count(BEGIN))
        self.assertEqual(twice.count(END), once.count(END))
        self.assertTrue(any("清理" in n for n in notes))

    def test_raises_without_location_slash(self):
        src = SAMPLE.replace("    location / {\n        proxy_pass http://127.0.0.1:1234;",
                             "    location /api {\n        proxy_pass http://127.0.0.1:1234;")
        with self.assertRaises(ValueError):
            patch_conf(src, 1234, "/tmp/x.js")

    def test_raises_without_server(self):
        with self.assertRaises(ValueError):
            patch_conf(SAMPLE, 55555, "/tmp/x.js")


class TestStrip(unittest.TestCase):
    def test_roundtrip_restores_original(self):
        out, _ = patch_conf(SAMPLE, 1234, "/srv/conf/bulk-import/bulk-import.js")
        restored, removed = strip_managed(out)
        self.assertEqual(removed, 2)
        self.assertEqual(restored, SAMPLE)

    def test_strip_without_managed_is_noop(self):
        restored, removed = strip_managed(SAMPLE)
        self.assertEqual(removed, 0)
        self.assertEqual(restored, SAMPLE)


class TestLocateConfGuards(unittest.TestCase):
    def test_locate_conf_without_port(self):
        self.assertIsNone(locate_conf(None))
        self.assertIsNone(locate_conf(0))


if __name__ == "__main__":
    unittest.main()