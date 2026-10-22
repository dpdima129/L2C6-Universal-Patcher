import tempfile
import unittest
import zipfile
from pathlib import Path

from client_scanner import classify_config, discover_clients
from backup_manager import create_backup
from config_patcher import patch_plain_ini, validate_server_address


class PatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_discover_client(self):
        system = self.base / "Game" / "system"
        system.mkdir(parents=True)
        (system / "L2.exe").write_bytes(b"test executable")
        (system / "l2.ini").write_text(
            "[URL]\nServerAddr=old.example.invalid\n",
            encoding="utf-8",
        )
        found = discover_clients(self.base)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].config_format, "plain_ini")

    def test_backup_preserves_original(self):
        source = self.base / "l2.ini"
        source.write_text("[URL]\nServerAddr=old.example.invalid\n")
        archive = create_backup([source], self.base / "backups")
        with zipfile.ZipFile(archive) as zf:
            self.assertIn("old.example.invalid", zf.read("l2.ini").decode())
        self.assertIn("old.example.invalid", source.read_text())

    def test_backup_verifies_exact_contents_of_multiple_files(self):
        exe = self.base / "L2.exe"
        ini = self.base / "l2.ini"
        exe.write_bytes(bytes([0, 255]) + b"client")
        ini.write_bytes(b"[URL]\nServerAddr=old.example.invalid\n")
        archive = create_backup([exe, ini], self.base / "backups")
        with zipfile.ZipFile(archive) as zf:
            self.assertIsNone(zf.testzip())
            self.assertEqual(set(zf.namelist()), {"L2.exe", "l2.ini"})
            self.assertEqual(zf.read("L2.exe"), exe.read_bytes())
            self.assertEqual(zf.read("l2.ini"), ini.read_bytes())

    def test_backup_rejects_duplicate_source(self):
        source = self.base / "l2.ini"
        source.write_bytes(b"original")
        with self.assertRaises(ValueError):
            create_backup([source, source], self.base / "backups")

    def test_patch_changes_only_server_address(self):
        config = self.base / "l2.ini"
        config.write_text(
            "[URL]\nServerAddr=old.example.invalid\nProtocol=746\n",
            encoding="utf-8",
        )
        patch_plain_ini(config, "ujuko1bg.pwrp.cc", self.base / "backups")
        text = config.read_text(encoding="utf-8")
        self.assertIn("ServerAddr=ujuko1bg.pwrp.cc", text)
        self.assertIn("Protocol=746", text)
        self.assertNotIn("old.example.invalid", text)


    def test_patch_only_url_section(self):
        config = self.base / "l2.ini"
        config.write_text(
            "[Other]\nServerAddr=keep.example.invalid\n"
            "[URL]\nServerAddr=old.example.invalid\n",
            encoding="utf-8",
        )
        patch_plain_ini(config, "ujuko1bg.pwrp.cc", self.base / "backups")
        text = config.read_text(encoding="utf-8")
        self.assertIn("ServerAddr=keep.example.invalid", text)
        self.assertIn("ServerAddr=ujuko1bg.pwrp.cc", text)

    def test_refuse_serveraddr_outside_url_section(self):
        config = self.base / "l2.ini"
        original = "[Other]\nServerAddr=keep.example.invalid\n"
        config.write_text(original, encoding="utf-8")
        with self.assertRaises(ValueError):
            patch_plain_ini(config, "ujuko1bg.pwrp.cc", self.base / "backups")
        self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_patch_auth_section(self):
        config = self.base / "l2.ini"
        original = (
            "[URL]\n"
            "NPLoginWebURL=lineage2.network\n"
            "[Auth]\n"
            "ServerAddr=149.202.227.142\n"
            "UseAuthUserData=true\n"
        )
        config.write_text(original, encoding="utf-8")

        patch_plain_ini(config, "ujuko1bg.pwrp.cc", self.base / "backups")

        updated = config.read_text(encoding="utf-8")
        self.assertIn("[Auth]", updated)
        self.assertIn("ServerAddr=ujuko1bg.pwrp.cc", updated)
        self.assertIn("NPLoginWebURL=lineage2.network", updated)
        self.assertIn("UseAuthUserData=true", updated)
        self.assertNotIn("149.202.227.142", updated)

    def test_unknown_config_is_not_modified(self):
        config = self.base / "l2.ini"
        original = b"\x00\xff\x81\x02encrypted"
        config.write_bytes(original)
        with self.assertRaises(ValueError):
            patch_plain_ini(config, "ujuko1bg.pwrp.cc", self.base / "backups")
        self.assertEqual(config.read_bytes(), original)

    def test_invalid_address_rejected(self):
        for address in ("", "bad host name", "example.com:99999"):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    validate_server_address(address)

    def test_utf16le_protocol_header_in_l2_ini_is_encrypted_candidate(self):
        config = self.base / "l2.ini"
        header = "Lineage2Ver413".encode("utf-16le")
        for prefix in (b"", bytes.fromhex("FF FE")):
            with self.subTest(bom=bool(prefix)):
                config.write_bytes(prefix + header + bytes.fromhex("00 01 02"))
                self.assertEqual(classify_config(config), "encrypted_candidate")

    def test_encrypted_filename_not_treated_as_plain_ini(self):
        config = self.base / "Lineage2Ver413"
        config.write_bytes(b"\x00\x01\x02\x03")
        self.assertEqual(classify_config(config), "encrypted_candidate")


if __name__ == "__main__":
    unittest.main(verbosity=2)
