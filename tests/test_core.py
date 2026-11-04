import os
import tarfile
import tempfile
import threading
import unittest
import zipfile

from camera_installer import catalog as cat
from camera_installer import device as dev
from camera_installer import installer, matching

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "internet_list.sh")


def load():
    with open(FIXTURE, encoding="utf-8") as f:
        return cat.parse(f.read())


def device(board, jp, family):
    model = board.upper().replace("_", "-") if board else None
    return dev.Device(None, model, board, jp, {"orin": "0x23", "thor": "0x26"}.get(family), family)


def compatible(catalog, d):
    return {m.package.key: m for m in matching.classify(catalog, d) if m.compatible}


class CatalogTest(unittest.TestCase):
    def test_parse_fixture(self):
        c = load()
        self.assertEqual(len(c.packages), 42)
        self.assertEqual(c.probe, "https://github.com/advantech-edge-ai/MIC-AI-camera-driver")
        p = next(p for p in c.packages if p.key == "otobrite/imx728/agx_orin/mic_733ao/jp6.2")
        self.assertTrue(p.url.startswith("https://github.com/advantech-edge-ai/MIC-AI-camera-driver/releases/download/"))
        self.assertEqual(p.asset_name, "MIC-733AO_Orin_6.2_V1.0.0_Otobrite_IMX728_V2.tbz2")
        self.assertEqual(c.board_label("mic_733ao"), "MIC-733AO")
        self.assertEqual(c.board_label("mic_999"), "MIC-999")
        self.assertEqual(c.platform_label("thor"), "AGX Thor")

    def test_rejects_garbage(self):
        with self.assertRaises(cat.CatalogError):
            cat.parse("<html>rate limited</html>")

    def test_jetpack_label(self):
        self.assertEqual(cat.jetpack_label("jp6.2"), "6.2")
        self.assertEqual(cat.jetpack_label("igx2.0"), "IGX 2.0")
        self.assertEqual(cat.jetpack_label(None), "Unknown")


class DeviceTest(unittest.TestCase):
    def test_version_line(self):
        self.assertEqual(dev.parse_version_line("MIC-743_Thor_7.2_V1.0.0, 1:2f23252, Build Date: x\r\n"),
                         ("MIC-743", "mic_743", "jp7.2"))
        self.assertEqual(dev.parse_version_line("MIC-733AO_32G_Orin_6.2_v1.0.0"),
                         ("MIC-733AO", "mic_733ao", "jp6.2"))
        self.assertEqual(dev.parse_version_line("MIC-711_Orin")[2], None)

    def test_chipid(self):
        self.assertEqual(dev.parse_chipid("TNSPEC x\nTEGRA_CHIPID 0x26\n"), "0x26")
        self.assertIsNone(dev.parse_chipid("nothing"))

    def test_detect_missing_files(self):
        d = dev.detect("/nonexistent/version", "/nonexistent/conf")
        self.assertIsNone(d.board)
        self.assertIsNone(d.family)


class MatchingTest(unittest.TestCase):
    def setUp(self):
        self.c = load()

    def test_exact_board_only(self):
        ok = compatible(self.c, device("mic_733ao", "jp6.2", "orin"))
        self.assertIn("otobrite/imx728/agx_orin/mic_733ao/jp6.2", ok)
        self.assertTrue(all(k.split("/")[3] == "mic_733ao" for k in ok))
        self.assertTrue(all(k.endswith("/jp6.2") for k in ok))

    def test_soc_family_never_offered(self):
        keys = {m.package.key for m in matching.classify(self.c, device("mic_733ao", "jp6.2", "orin"))}
        self.assertFalse(any("/thor/" in k for k in keys))

    def test_742_uses_own(self):
        ok = compatible(self.c, device("mic_742", "jp7.2", "thor"))
        self.assertIn("leopard/imx728/thor/mic_742/jp7.2", ok)
        self.assertIsNone(ok["leopard/imx728/thor/mic_742/jp7.2"].via_board)

    def test_741_falls_back_to_742(self):
        ok = compatible(self.c, device("mic_741", "jp7.2", "thor"))
        m = ok["leopard/imx728/thor/mic_742/jp7.2"]
        self.assertEqual(m.via_board, "mic_742")

    def test_743_prefers_own_package(self):
        # econ STURDeCAM25 has its own mic_743 package on jp7.1
        ok = compatible(self.c, device("mic_743", "jp7.1", "thor"))
        self.assertIn("econ/STURDeCAM25/thor/mic_743/jp7.1", ok)

    def test_743_falls_back_when_no_own_for_jetpack(self):
        ok = compatible(self.c, device("mic_743", "jp7.2", "thor"))
        self.assertEqual(ok["econ/STURDeCAM25/thor/mic_742/jp7.2"].via_board, "mic_742")
        self.assertNotIn("econ/STURDeCAM25/thor/mic_743/jp7.1", ok)

    def test_743_own_hides_742_for_same_jetpack(self):
        url = "https://example.com/x.tbz2"
        c = self.c._replace(packages=[cat.Package("v", "s", "thor", "mic_743", "jp7.2", url),
                                      cat.Package("v", "s", "thor", "mic_742", "jp7.2", url)])
        ok = compatible(c, device("mic_743", "jp7.2", "thor"))
        self.assertEqual(list(ok), ["v/s/thor/mic_743/jp7.2"])

    def test_mismatch_reasons(self):
        ms = {m.package.key: m for m in matching.classify(self.c, device("mic_733ao", "jp6.2", "orin"))}
        m = ms["otobrite/imx728/agx_orin/mic_732/jp6.2"]
        self.assertFalse(m.compatible)
        self.assertIn("MIC-732", m.problems[0])

    def test_unknown_device_offers_all_with_warning(self):
        ms = matching.classify(self.c, dev.Device(None, None, None, None, None, None))
        self.assertEqual(len(ms), 42)
        self.assertFalse(any(m.compatible for m in ms))


class InstallerTest(unittest.TestCase):
    def test_dest_dir(self):
        c = load()
        get = {p.key: p for p in c.packages}.get
        self.assertEqual(installer.dest_dir(get("otobrite/imx728/agx_orin/mic_733ao/jp6.2")),
                         "/opt/advantech/camera_framework/vendors/otobrite/imx728/agx_orin/mic_733ao/jp6.2")
        self.assertEqual(installer.dest_dir(get("realsense/D457/thor/mic_742/jp7.2")),
                         "/opt/advantech/camera_framework/vendors/realsense/agx_thor/mic_742/jp7.2")

    def test_find_entry_prefers_shallowest(self):
        with tempfile.TemporaryDirectory() as d:
            deep = os.path.join(d, "pkg", "headers", "scripts")
            os.makedirs(deep)
            open(os.path.join(deep, "install.sh"), "w").close()
            open(os.path.join(d, "pkg", "install.sh"), "w").close()
            self.assertEqual(installer.find_entry(d), os.path.join(d, "pkg"))

    def test_find_entry_deb_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "a"))
            open(os.path.join(d, "a", "zed.deb"), "w").close()
            self.assertEqual(installer.find_entry(d), os.path.join(d, "a"))

    def test_extract_tar_and_zip(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src")
            os.makedirs(os.path.join(src, "pkg"))
            script = os.path.join(src, "pkg", "install.sh")
            with open(script, "w") as f:
                f.write("echo hi\n")
            os.chmod(script, 0o755)
            os.symlink("/usr/src/linux-headers", os.path.join(src, "pkg", "headers"))

            tbz = os.path.join(d, "x.tbz2")
            with tarfile.open(tbz, "w:bz2") as tf:
                tf.add(os.path.join(src, "pkg"), arcname="pkg")
            stage = os.path.join(d, "stage1")
            os.makedirs(stage)
            installer.extract(tbz, stage, lambda i, n: None, threading.Event())
            self.assertTrue(os.access(os.path.join(stage, "pkg", "install.sh"), os.X_OK))
            self.assertTrue(os.path.islink(os.path.join(stage, "pkg", "headers")))

            zp = os.path.join(d, "x.zip")
            with zipfile.ZipFile(zp, "w") as zf:
                zf.write(script, "pkg/install.sh")
            stage = os.path.join(d, "stage2")
            os.makedirs(stage)
            installer.extract(zp, stage, lambda i, n: None, threading.Event())
            self.assertTrue(os.access(os.path.join(stage, "pkg", "install.sh"), os.X_OK))

    def test_zip_slip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            zp = os.path.join(d, "bad.zip")
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("../evil.sh", "x")
            stage = os.path.join(d, "stage")
            os.makedirs(stage)
            with self.assertRaises(installer.InstallError):
                installer.extract(zp, stage, lambda i, n: None, threading.Event())


if __name__ == "__main__":
    unittest.main()
