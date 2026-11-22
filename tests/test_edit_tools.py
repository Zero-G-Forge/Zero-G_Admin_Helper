## Tests for validation, diff and backup-first local saves. No real server or user files are touched.

import os
import sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from features.shared.edit_tools import validate_ecf, validate_yaml, make_diff, has_errors
from features.server_files import edit_store


def test_ecf_line_numbers():
    problems = validate_ecf('{ +Item Id: 1\n Mass: 2\n')
    assert problems[0]['line'] == 1 and has_errors(problems)
    assert validate_ecf('{ +Item Id: 1\n Mass: 2\n}\n') == []
    assert validate_ecf('}\n')[0]['line'] == 1
    assert has_errors(validate_ecf('{ Item\n Name: "bad\n}\n'))


def test_diff_and_final_newline():
    assert make_diff('a\n', 'a\n') == []
    diff = make_diff('a\n', 'b\n', 'test.ecf')
    assert '-a\n' in diff and '+b\n' in diff
    assert make_diff('a\n', 'a')


def test_yaml_errors():
    assert has_errors(validate_yaml('a: [\n'))
    assert has_errors(validate_yaml('\tbad: 2\n'))


def test_save_backup_and_download_unchanged(tmp_path):
    source = tmp_path / 'scenario' / 'Content' / 'Config.ecf'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'{ Item\r\n}\r\n')
    entry = {'root': 'scenario', 'path': 'Content/Config.ecf', 'full': str(source)}
    first = edit_store.save_edit(str(tmp_path), entry, '{ Item\n Mass: 2\n}\n')
    assert source.read_bytes() == b'{ Item\r\n}\r\n'
    assert open(first['backup'], 'rb').read() == source.read_bytes()
    assert b'\r\n' in open(first['saved'], 'rb').read()
    second = edit_store.save_edit(str(tmp_path), entry, '{ Item\n Mass: 3\n}\n')
    assert first['backup'] != second['backup']
    assert b'Mass: 2' in open(second['backup'], 'rb').read()
    assert edit_store.base_sha256(str(tmp_path), entry) == edit_store.file_sha256(str(source))
