#!/usr/bin/env python3
"""The reaper (0.6.0 cut, quantum-concepts 1974): dreams are compaction continuity for the session
that made them, so a folder or watermark left by ANOTHER session and older than reap_days is
removed - and nothing else is ever touched.

The legs that matter are the refusals: the current session's things survive at any age, a young
thing survives, and a name the plugin did not write survives even when it sits in dreams/.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from dreaming import config, sleep as sl  # noqa: E402

DAY = 86400.0
NOW = 1_800_000_000.0


class ReapTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.dreams = os.path.join(self.root, sl.DREAMS_DIRNAME)
        os.makedirs(self.dreams)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _folder(self, name, age_days):
        path = os.path.join(self.dreams, name)
        os.makedirs(path)
        with open(os.path.join(path, "sleep.log"), "w") as fh:
            fh.write("x")
        os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
        return path

    def _file(self, name, age_days):
        path = os.path.join(self.dreams, name)
        with open(path, "w") as fh:
            fh.write("uuid")
        os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
        return path

    def test_old_things_of_other_sessions_go_and_everything_else_stays(self):
        old_other = self._folder("20260901-101010-aaaaaaaa", 30)
        old_other_2 = self._folder("20260901-101010-aaaaaaaa-2", 30)
        old_mine = self._folder("20260901-101010-bbbbbbbb", 30)
        young_other = self._folder("20260930-101010-cccccccc", 1)
        not_ours = self._folder("my-notes", 30)
        wm_old_other = self._file(".watermark-aaaaaaaa-1111.txt", 30)
        wm_old_mine = self._file(".watermark-bbbbbbbb-2222.txt", 30)
        wm_young = self._file(".watermark-cccccccc-3333.txt", 1)
        stray = self._file("README.txt", 30)

        gone = sl.reap(self.root, keep_session="bbbbbbbb-2222", max_age_days=14, now=NOW)

        for p in (old_other, old_other_2, wm_old_other):
            self.assertFalse(os.path.exists(p), p)
        for p in (old_mine, young_other, not_ours, wm_old_mine, wm_young, stray):
            self.assertTrue(os.path.exists(p), p)
        self.assertEqual(sorted(os.path.basename(g) for g in gone),
                         sorted(["20260901-101010-aaaaaaaa", "20260901-101010-aaaaaaaa-2",
                                 ".watermark-aaaaaaaa-1111.txt"]))

    def test_zero_days_means_off(self):
        old = self._folder("20260901-101010-aaaaaaaa", 300)
        self.assertEqual(sl.reap(self.root, keep_session="zzz", max_age_days=0, now=NOW), [])
        self.assertTrue(os.path.exists(old))

    def test_a_store_with_no_dreams_dir_is_fine(self):
        empty = tempfile.mkdtemp()
        try:
            self.assertEqual(sl.reap(empty, keep_session="x", max_age_days=14, now=NOW), [])
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_the_default_is_on(self):
        self.assertEqual(config.DEFAULTS["reap_days"], 14)


if __name__ == "__main__":
    unittest.main()
