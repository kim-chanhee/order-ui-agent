import json

import pytest

from app.execution.sql_contract import SqlContractViolation, validate_sql_contract


@pytest.fixture
def roles(tmp_path, monkeypatch):
    config = {'entity_roles':{'event':{'identifier_fields':['event_id']},
                              'item':{'identifier_fields':['item_id']}},
        'column_roles':[
            {'table':'links','field':'source','discriminator':'kind','entities':{'contains':'order'}},
            {'table':'links','field':'target','discriminator':'kind','entities':{'contains':'item'}},
            {'table':'events','field':'object_key','entity':'item'},
            {'table':'events','field':'event_key','entity':'event'}]}
    path=tmp_path/'semantics.json';path.write_text(json.dumps(config))
    monkeypatch.setenv('ANALYSIS_SEMANTICS_PATH',str(path))


@pytest.mark.parametrize('join', ['l.source=x.item_id', 'e.event_key=x.item_id'])
def test_reject_incompatible_keys_through_cte_projection(roles, join):
    sql=f"""WITH x AS (SELECT object_key AS item_id FROM events)
    SELECT x.item_id FROM x JOIN links l ON l.target=x.item_id
    JOIN events e ON {join} WHERE l.kind='contains'"""
    with pytest.raises(SqlContractViolation,match='incompatible_join_keys'):
        validate_sql_contract(None,sql)


def test_allow_correct_direction_and_unknown_roles(roles):
    sql="""WITH x AS (SELECT object_key AS item_id FROM events)
    SELECT x.item_id FROM x JOIN links l ON l.target=x.item_id WHERE l.kind='contains'"""
    assert validate_sql_contract(None,sql)==sql
    unknown='SELECT * FROM a JOIN b ON a.untyped=b.unknown'
    assert validate_sql_contract(None,unknown)==unknown


def test_role_discriminator_does_not_leak_from_another_alias(roles):
    sql="""WITH x AS (SELECT object_key AS item_id FROM events)
    SELECT x.item_id FROM x JOIN links l ON l.source=x.item_id
    JOIN links other ON other.target=x.item_id WHERE other.kind='contains'"""
    # l has no known qualifier; do not borrow other.kind to type l.source.
    assert validate_sql_contract(None,sql)==sql
