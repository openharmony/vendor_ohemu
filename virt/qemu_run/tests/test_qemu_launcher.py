#!/usr/bin/env python3

"""Focused regression tests for the profile-driven QEMU launcher."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qemu_launcher_lib import launcher  # noqa: E402


class LauncherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = launcher.repo_root_from_launcher()
        cls.profile = launcher.load_profile(
            cls.repo / "vendor/ohemu/virt/qemu_run/x86_64/qemu_profile.json"
        )

    def test_architecture_aliases(self):
        self.assertEqual(launcher.normalize_arch("AMD64"), "x86_64")
        self.assertEqual(launcher.normalize_arch("arm64"), "aarch64")
        self.assertEqual(launcher.normalize_arch("armv7l"), "arm")

    def test_instance_resources_are_unique(self):
        first = launcher.derive_resources(self.profile, "00")
        second = launcher.derive_resources(self.profile, "01")
        self.assertNotEqual(first["hdc_port"], second["hdc_port"])
        self.assertNotEqual(first["vnc_display"], second["vnc_display"])
        self.assertNotEqual(first["mac"], second["mac"])
        self.assertNotEqual(first["sn"], second["sn"])
        self.assertEqual(second["hdc_port"], 5556)
        self.assertEqual(second["vnc_display"], 22)
        self.assertEqual(second["gdb_port"], 1235)
        self.assertEqual(second["sn"], "0123456789")
        self.assertEqual(second["mac"], "52:54:00:58:00:01")

    def test_accelerator_policy_by_host(self):
        capabilities = {"accelerators": {"kvm", "hvf", "whpx", "tcg"}}
        cases = (("linux", "x86_64", "kvm"), ("macos", "arm64", "hvf"), ("windows", "AMD64", "whpx"))
        for system, architecture, expected in cases:
            profile = dict(self.profile, guest_arch=launcher.normalize_arch(architecture))
            with self.subTest(system=system), \
                    mock.patch.object(launcher, "host_os", return_value=system), \
                    mock.patch.object(launcher.platform, "machine", return_value=architecture), \
                    mock.patch.object(launcher, "probe_accelerator", return_value=(True, "ok")), \
                    mock.patch.object(launcher.os, "access", return_value=True):
                selected, _ = launcher.select_accelerator("auto", "qemu", profile, capabilities)
                self.assertEqual(selected, expected)

    def test_cross_architecture_falls_back_to_tcg(self):
        capabilities = {"accelerators": {"kvm", "tcg"}}
        with mock.patch.object(launcher, "host_os", return_value="linux"), \
                mock.patch.object(launcher.platform, "machine", return_value="aarch64"), \
                mock.patch.object(launcher, "probe_accelerator", return_value=(True, "ok")):
            selected, _ = launcher.select_accelerator("auto", "qemu", self.profile, capabilities)
        self.assertEqual(selected, "tcg")

    def test_archive_path_traversal_is_rejected(self):
        with self.assertRaises(launcher.LauncherError):
            launcher.validate_archive_member("../escape.img")
        with self.assertRaises(launcher.LauncherError):
            launcher.validate_archive_member("C:/escape.img")

    def test_every_public_cli_option_has_help(self):
        parser = launcher.build_parser()
        for action in parser._actions:
            if action.help == launcher.argparse.SUPPRESS:
                continue
            with self.subTest(option=action.option_strings or [action.dest]):
                self.assertIsInstance(action.help, str)
                self.assertTrue(action.help.strip())


if __name__ == "__main__":
    unittest.main()
