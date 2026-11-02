import json
import os
import sqlite3

import pytest

from app.core.data_profile import apply_data_profile, PROFILE_FIELDS
from scripts.create_data_profile import create_profile
from app.planning.analysis_models import AnalysisPlan, MetricSpec
from app.planning.option_catalog import build_plan_option_catalog


def test_new_domain_profile_uses_declared_keys_and_isolates_old_metadata(tmp_path,monkeypatch):
    db=tmp_path/'library.sqlite'
    with sqlite3.connect(db) as c:
        c.executescript('CREATE TABLE authors(author_key INTEGER PRIMARY KEY,name TEXT);'
          'CREATE TABLE books(book_key INTEGER PRIMARY KEY,author_key INTEGER REFERENCES authors(author_key),genre TEXT,price REAL);')
    profile=create_profile(db,tmp_path/'profile')
    for env in PROFILE_FIELDS.values():monkeypatch.setenv(env,'old-dataset')
    apply_data_profile(profile)
    config=json.loads((profile.parent/'analysis_semantics.json').read_text())
    assert {'table':'books','field':'author_key','entity':'authors'} in config['column_roles']
    assert os.environ['ORDER_UI_DB_PATH']==str(db)
    assert 'old-dataset' not in [os.environ[env] for env in PROFILE_FIELDS.values()]
    catalog=build_plan_option_catalog('authors(author_key INTEGER, name TEXT)\nbooks(book_key INTEGER,author_key INTEGER,genre TEXT,price REAL)',
        AnalysisPlan(original_question='장르별 책 수',metric=MetricSpec(kind='count',field='book_key')))
    assert 'book_key' in {o.value for o in catalog.count_fields}
    assert 'genre' in {o.value for o in catalog.group_by}
    assert 'price' in {o.value for o in catalog.numeric_fields}
    with pytest.raises(ValueError,match='never overwritten'):create_profile(db,profile.parent)


def test_invalid_profile_does_not_partially_replace_environment(tmp_path,monkeypatch):
    path=tmp_path/'profile.json';path.write_text(json.dumps({'version':1,'database':'missing'}))
    monkeypatch.setenv('ORDER_UI_DB_PATH','original')
    with pytest.raises(ValueError):apply_data_profile(path)
    assert os.environ['ORDER_UI_DB_PATH']=='original'


def test_metadata_edits_are_not_hidden_by_path_only_cache(tmp_path,monkeypatch):
    from app.execution.analysis_semantics import load_analysis_semantics
    path=tmp_path/'semantics.json';monkeypatch.setenv('ANALYSIS_SEMANTICS_PATH',str(path))
    path.write_text('{"entity_roles":{}}')
    assert load_analysis_semantics()['entity_roles']=={}
    path.write_text('{"entity_roles":{"books":{"identifier_fields":["book_key"]}}}')
    assert 'books' in load_analysis_semantics()['entity_roles']
