#!/usr/bin/env python3
"""Prepare a trusted pg_dump SQL backup for an empty local database.

Remove supported cleanup statements before the first CREATE statement.
Remove object ownership statements outside COPY data.
Preserve the source file and every COPY data byte.
This helper does not restore data or validate arbitrary SQL for safe execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


IDENT = rb'(?:[A-Za-z_][A-Za-z_0-9$]*|"(?:[^"]|"")+")'
NAME = IDENT + rb'\.' + IDENT
CLEANUP = re.compile(
    rb'(?:ALTER TABLE (?:ONLY )?' + NAME + rb' DROP CONSTRAINT ' + IDENT
    + rb'|ALTER TABLE (?:ONLY )?' + NAME + rb' ALTER COLUMN ' + IDENT
    + rb' DROP DEFAULT|DROP (?:INDEX|TABLE|SEQUENCE) ' + NAME + rb');'
)
OWNERSHIP = re.compile(
    rb'ALTER (?:TABLE|SEQUENCE|VIEW|MATERIALIZED VIEW|TYPE|SCHEMA) '
    + rb'(?:' + NAME + rb'|' + IDENT + rb') OWNER TO ' + IDENT + rb';'
)
COPY = re.compile(rb'COPY ' + NAME + rb' \(' + IDENT + rb'(?:, ' + IDENT + rb')*\) FROM stdin;')
SET = re.compile(
    rb'SET (?:statement_timeout|lock_timeout|idle_in_transaction_session_timeout|'
    rb'client_encoding|standard_conforming_strings|check_function_bodies|xmloption|'
    rb'client_min_messages|row_security|default_tablespace|default_table_access_method) = '
    rb"(?:[A-Za-z_0-9]+|'(?:[^']|'')*');"
)
SEARCH_PATH = b"SELECT pg_catalog.set_config('search_path', '', false);"


class StatementReader:
    """Split SQL statements without interpreting quoted strings or comments."""

    def __init__(self):
        self.raw = bytearray()
        self.code = bytearray()
        self.state = 'normal'
        self.tag = None
        self.depth = 0
        self.escaped_string = False

    def feed(self, line):
        index = 0
        while index < len(line):
            size = 1
            char = line[index:index + 1]
            pair = line[index:index + 2]
            include = True
            complete = False
            if self.state == 'line_comment':
                include = False
                if char == b'\n':
                    self.state = 'normal'
            elif self.state == 'block_comment':
                include = False
                if pair == b'/*':
                    self.depth += 1
                    size = 2
                elif pair == b'*/':
                    self.depth -= 1
                    size = 2
                    if not self.depth:
                        self.state = 'normal'
            elif self.state in ('single', 'double'):
                quote = b"'" if self.state == 'single' else b'"'
                if self.state == 'single' and self.escaped_string and char == b'\\':
                    size = 2
                elif pair == quote * 2:
                    size = 2
                elif char == quote:
                    self.state = 'normal'
            elif self.state == 'dollar':
                if line.startswith(self.tag, index):
                    size = len(self.tag)
                    self.state = 'normal'
            elif pair in (b'--', b'/*'):
                self.state = 'line_comment' if pair == b'--' else 'block_comment'
                self.depth = 1
                self.code.extend(b' ')
                size = 2
                include = False
            elif char in (b"'", b'"'):
                self.state = 'single' if char == b"'" else 'double'
                self.escaped_string = bool(re.search(rb'(?:^|\W)[eE]$', self.code))
            elif char == b'$':
                match = re.match(rb'\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$', line[index:])
                if match:
                    self.tag = match.group()
                    size = len(self.tag)
                    self.state = 'dollar'
            elif char == b';':
                complete = True
            chunk = line[index:index + size]
            self.raw.extend(chunk)
            if include:
                self.code.extend(chunk)
            index += size
            if len(self.raw) > 8 * 1024 * 1024:
                raise ValueError('SQL statement exceeds 8 MiB; inspect this dump manually.')
            if complete:
                raw, code = bytes(self.raw), bytes(self.code).strip()
                self.raw.clear()
                self.code.clear()
                yield raw, code, line[index:]


def convert(source, output):
    """Copy SQL to output and return hashes and conversion counts."""
    source_hash, output_hash, copy_hash = (hashlib.sha256() for _ in range(3))
    counts = dict(cleanup_statements=0, ownership_statements=0,
                  copy_sections=0, copy_rows=0, source_bytes=0, output_bytes=0)
    reader = StatementReader()
    created = False
    in_copy = False

    def write(data):
        output.write(data)
        output_hash.update(data)
        counts['output_bytes'] += len(data)

    for line_number, line in enumerate(source, 1):
        source_hash.update(line)
        counts['source_bytes'] += len(line)
        if in_copy:
            write(line)
            if line.rstrip(b'\r\n') == b'\\.':
                in_copy = False
            else:
                counts['copy_rows'] += 1
                copy_hash.update(line)
            continue
        if not reader.code.strip() and reader.state == 'normal':
            if not line.strip() or line.lstrip().startswith(b'--'):
                write(bytes(reader.raw) + line)
                reader.raw.clear()
                reader.code.clear()
                continue
        for raw, code, tail in reader.feed(line):
            # Collapse whitespace only for comparison. Preserve original output bytes.
            compact = re.sub(rb'\s+', b' ', code)
            if OWNERSHIP.fullmatch(compact):
                counts['ownership_statements'] += 1
                continue
            if re.match(rb'ALTER\s+\w+\b', compact) and b' OWNER TO ' in compact:
                raise ValueError('Unsupported ownership statement at line {}.'.format(line_number))
            if not created:
                if CLEANUP.fullmatch(compact):
                    counts['cleanup_statements'] += 1
                    continue
                if compact.startswith(b'CREATE '):
                    created = True
                elif not SET.fullmatch(compact) and compact != SEARCH_PATH:
                    raise ValueError('Unsupported pre-CREATE statement at line {}.'.format(line_number))
            elif compact.startswith((b'DROP ', b'TRUNCATE ', b'DELETE ', b'UPDATE ')) or CLEANUP.fullmatch(compact):
                raise ValueError('Unexpected cleanup after CREATE at line {}.'.format(line_number))
            if compact.startswith(b'COPY '):
                if not COPY.fullmatch(compact) or tail.strip():
                    raise ValueError('Unsupported COPY statement at line {}.'.format(line_number))
                in_copy = True
                counts['copy_sections'] += 1
            write(raw)
        # Whitespace after a statement belongs to SQL, including COPY headers.
        if not reader.code.strip() and reader.state == 'normal':
            write(bytes(reader.raw))
            reader.raw.clear()
            reader.code.clear()
    if in_copy:
        raise ValueError('COPY data has no final terminator.')
    if reader.code.strip() or reader.state != 'normal':
        raise ValueError('The dump ends inside a SQL statement.')
    if not created:
        raise ValueError('The dump has no CREATE statement.')
    write(bytes(reader.raw))
    counts.update(source_sha256=source_hash.hexdigest(), output_sha256=output_hash.hexdigest(),
                  copy_data_sha256=copy_hash.hexdigest())
    return counts


def prepare_backup(source_path, output_path):
    """Create a new SQL file and manifest. Refuse existing destinations."""
    source_path, output_path = Path(source_path).resolve(), Path(output_path).absolute()
    manifest_path = output_path.with_name(output_path.name + '.manifest.json')
    if source_path == output_path.resolve():
        raise ValueError('The source and output paths must differ.')
    if output_path.exists() or manifest_path.exists():
        raise ValueError('The output or manifest already exists. Choose a new output name.')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_paths = []
    installed = False
    try:
        with source_path.open('rb') as source:
            if b'-- PostgreSQL database dump' not in source.read(4096):
                raise ValueError('The source must be a plain PostgreSQL SQL dump.')
            source.seek(0)
            with tempfile.NamedTemporaryFile(dir=str(output_path.parent), delete=False) as output:
                temporary_paths.append(Path(output.name))
                manifest = convert(source, output)
        manifest.update(format_version=1, source_path=str(source_path), output_path=str(output_path))
        with tempfile.NamedTemporaryFile(dir=str(output_path.parent), delete=False) as report:
            temporary_paths.append(Path(report.name))
            report.write((json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode('utf-8'))
        os.link(str(temporary_paths[0]), str(output_path))
        installed = True
        os.link(str(temporary_paths[1]), str(manifest_path))
        return manifest
    except Exception:
        if installed:
            output_path.unlink()
        raise
    finally:
        for path in temporary_paths:
            path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or (Path(__file__).resolve().parents[2] / 'local-data' / 'backups'
                             / (args.source.name + '.prepared.sql'))
    try:
        report = prepare_backup(args.source, output)
    except (OSError, ValueError) as error:
        parser.exit(1, '{}\n'.format(error))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
