"""Check backup conversion without Docker or database access."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from prepare_legacy_backup import prepare_backup


HEADER = b"-- PostgreSQL database dump\nSET client_encoding = 'UTF8';\n"
CREATE = b'CREATE TABLE public.example (id integer, text text);\n'


class PrepareBackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / 'original.bkp'
        self.output = self.root / 'prepared.sql'

    def tearDown(self):
        self.directory.cleanup()

    def prepare(self, sql):
        self.source.write_bytes(sql)
        return prepare_backup(self.source, self.output)

    def test_cleanup_ownership_and_copy_preservation(self):
        cleanup = (
            b'ALTER TABLE ONLY public.example DROP CONSTRAINT example_pkey;\n'
            b'ALTER TABLE public.example ALTER COLUMN id DROP DEFAULT;\n'
            b'ALTER TABLE ONLY public.example ALTER COLUMN id DROP DEFAULT;\n'
            b'DROP INDEX public.example_idx;\nDROP TABLE public.example;\n'
            b'DROP SEQUENCE public.example_id_seq;\n'
        )
        rows = (b'ALTER TABLE public.example OWNER TO old_role;\n'
                b'DROP TABLE public.example;\n'
                b'COPY public.example (id, text) FROM stdin;\n'
                b'1\t\\.\r\n2\ttext with ; and -- and \' and "\n')
        owner = b'ALTER TABLE public.example OWNER TO old_role;\n'
        sql = HEADER + cleanup + CREATE + owner + b'COPY public.example (id, text) FROM stdin;\n' + rows + b'\\.\n'
        report = self.prepare(sql)
        result = self.output.read_bytes()
        self.assertEqual(self.source.read_bytes(), sql)
        self.assertIn(rows + b'\\.\n', result)
        self.assertEqual(result.count(owner), 1)
        self.assertEqual(report['cleanup_statements'], 6)
        self.assertEqual(report['ownership_statements'], 1)
        self.assertEqual(report['copy_sections'], 1)
        self.assertEqual(report['copy_rows'], 5)
        self.assertEqual(report['copy_data_sha256'], hashlib.sha256(rows).hexdigest())
        self.assertEqual(report['source_sha256'], hashlib.sha256(sql).hexdigest())
        self.assertEqual(report['output_sha256'], hashlib.sha256(result).hexdigest())
        self.assertEqual(report['source_bytes'], len(sql))
        self.assertEqual(report['output_bytes'], len(result))
        self.assertEqual(json.loads(self.output.with_name('prepared.sql.manifest.json').read_text()), report)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_unknown_cleanup_fails_without_output(self):
        for statement in (b'DROP DATABASE cafepay;', b'DROP TABLE public.example CASCADE;',
                          b'ALTER TABLE public.example DROP COLUMN id;', b'TRUNCATE public.example;',
                          b'DROP TABLE public.example; DELETE FROM public.other;'):
            with self.subTest(statement=statement):
                sql = HEADER + statement + b'\n' + CREATE
                with self.assertRaisesRegex(ValueError, 'Unsupported pre-CREATE'):
                    self.prepare(sql)
                self.assertEqual(self.source.read_bytes(), sql)
                self.assertFalse(self.output.exists())
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['original.bkp'])

    def test_quoted_sql_and_comments_remain_unchanged(self):
        sql = (HEADER + CREATE + b"COMMENT ON TABLE public.example IS 'first line\n"
               b'ALTER TABLE public.example OWNER TO old_role;\n'
               b"last line';\n-- ALTER TABLE public.example OWNER TO old_role;\n"
               b"COMMENT ON TABLE public.example IS $$DROP TABLE public.example;$$;\n")
        report = self.prepare(sql)
        self.assertEqual(self.output.read_bytes(), sql)
        self.assertEqual(report['ownership_statements'], 0)

    def test_cleanup_after_create_fails(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected cleanup'):
            self.prepare(HEADER + CREATE + b'DROP TABLE public.example;\n')
        self.assertFalse(self.output.exists())

    def test_incomplete_copy_fails(self):
        with self.assertRaisesRegex(ValueError, 'terminator'):
            self.prepare(HEADER + CREATE + b'COPY public.example (id) FROM stdin;\n1\n')
        self.assertFalse(self.output.exists())

    def test_existing_output_and_manifest_remain_unchanged(self):
        self.source.write_bytes(HEADER + CREATE)
        for destination in (self.output, self.output.with_name('prepared.sql.manifest.json')):
            destination.write_bytes(b'existing file')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                prepare_backup(self.source, self.output)
            self.assertEqual(destination.read_bytes(), b'existing file')
            destination.unlink()

    def test_source_cannot_be_output(self):
        self.source.write_bytes(HEADER + CREATE)
        with self.assertRaisesRegex(ValueError, 'must differ'):
            prepare_backup(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), HEADER + CREATE)


if __name__ == '__main__':
    unittest.main()
