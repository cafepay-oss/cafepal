"""Data preservation checks, runnable without Docker or application dependencies."""
import contextlib
import gzip
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import stat
import tarfile
import tempfile
import types
import unittest
from unittest.mock import Mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[2] / 'local'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        loader = importlib.machinery.SourceFileLoader('recovery', str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.app = importlib.util.module_from_spec(spec)
        loader.exec_module(self.app)
        self.app.ROOT = self.root
        self.app.DATA = self.root / 'local-data'
        self.app.ENV = self.root / '.env.local'
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.app.initialize()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_init_preserves_credentials_and_media(self):
        before = self.app.ENV.read_bytes()
        marker = self.app.DATA / 'media' / 'photo.jpg'
        marker.write_bytes(b'original')
        self.app.initialize()
        self.assertEqual(before, self.app.ENV.read_bytes())
        self.assertEqual(stat.S_IMODE(self.app.ENV.stat().st_mode), 0o600)
        self.assertEqual(marker.read_bytes(), b'original')

    def test_media_zip_unwraps_media_and_preserves_source(self):
        source = self.root / 'photos.zip'
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('media/products/photo.jpg', b'image bytes')
        before = source.read_bytes()
        self.app.import_media(source)
        self.assertEqual((self.app.DATA / 'media/products/photo.jpg').read_bytes(), b'image bytes')
        self.assertEqual(source.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'not empty'):
            self.app.import_media(source)

    def test_media_rejects_path_traversal_without_writing(self):
        source = self.root / 'bad.zip'
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('../escape.txt', b'bad')
        with self.assertRaisesRegex(ValueError, 'Unsafe archive'):
            self.app.import_media(source)
        self.assertEqual(list((self.app.DATA / 'media').iterdir()), [])
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_media_rejects_tar_symlink(self):
        source = self.root / 'bad.tar'
        with tarfile.open(source, 'w') as archive:
            member = tarfile.TarInfo('link')
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/passwd'
            archive.addfile(member)
        with self.assertRaisesRegex(ValueError, 'regular files'):
            self.app.import_media(source)

    def test_restore_refuses_nonempty_database(self):
        source = self.root / 'dump.sql'
        source.write_text('-- PostgreSQL database dump\nSELECT 1;\n')
        self.app.compose = Mock(return_value=types.SimpleNamespace(stdout='3\n'))
        with self.assertRaisesRegex(ValueError, 'already contains objects'):
            self.app.restore_database(source)
        self.assertEqual(self.app.compose.call_count, 2)

    def test_restore_decompresses_and_uses_transaction(self):
        source = self.root / 'dump.sql.gz'
        sql = b'-- PostgreSQL database dump\nSELECT 1;\n'
        with gzip.open(source, 'wb') as stream:
            stream.write(sql)
        received = []

        def fake_compose(*args, **kwargs):
            if 'stdin' in kwargs:
                received.append((args, kwargs['stdin'].read()))
            return types.SimpleNamespace(stdout='0\n')

        self.app.compose = fake_compose
        self.app.restore_database(source)
        self.assertEqual(received[0][1], sql)
        self.assertIn('--single-transaction', received[0][0][-1])
        self.assertIn('ON_ERROR_STOP=1', received[0][0][-1])

    def test_restore_rejects_unknown_file_before_docker(self):
        source = self.root / 'random.bin'
        source.write_bytes(b'not a database')
        self.app.compose = Mock()
        with self.assertRaisesRegex(ValueError, 'Unrecognized dump'):
            self.app.restore_database(source)
        self.app.compose.assert_not_called()


if __name__ == '__main__':
    unittest.main()
