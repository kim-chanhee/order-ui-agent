"""Create editable metadata from a SQLite schema without copying its data."""
import argparse
import json
import os
from pathlib import Path
import sqlite3


def create_profile(database, output):
    database, output = Path(database).resolve(), Path(output).resolve()
    if not database.is_file():
        raise ValueError('Database does not exist')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be new or empty; existing profiles are never overwritten')
    # Inspect first, then write the complete profile. No sample rows or API keys
    # are copied; PK/FK declarations, columns, and types are the only evidence.
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        schemas, foreign_keys = {}, {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            schemas[table] = conn.execute(f'PRAGMA table_info({quoted})').fetchall()
            foreign_keys[table] = conn.execute(f'PRAGMA foreign_key_list({quoted})').fetchall()
    entities, roles, relationships = {}, [], []
    for table, columns in schemas.items():
        pks = [c[1] for c in columns if c[5]]
        # Composite keys remain table-grain metadata, not individually unique.
        if len(pks) == 1:
            entities[table] = {'semantic_terms':[table], 'identifier_fields':pks}
            roles.append({'table':table, 'field':pks[0], 'entity':table})
        for fk in foreign_keys[table]:
            target, source_field, target_field = fk[2:5]
            target_pks = [c[1] for c in schemas.get(target, []) if c[5]]
            if target_field is None and len(target_pks) == 1:
                target_field = target_pks[0]
            if target_field and len(target_pks) == 1 and target_field in target_pks:
                roles.append({'table':table,'field':source_field,'entity':target})
            relationships.append({'name':f'{table}_{source_field}_to_{target}', 'table':table,
                'source_field':source_field,'target_table':target,'target_field':target_field})
    semantics = {'entity_roles':entities,'column_roles':roles,'entity_relationships':relationships,
                 'attribute_roles':{'display_name':[c[1] for cols in schemas.values() for c in cols
                     if c[1].lower().endswith(('_name','_label')) or c[1].lower() in {'name','title','label'}]},
                 'semantic_metrics':{}}
    summary = ['# 데이터 설명', '', '이 파일에 업무 용어, 날짜 기준, 상태 코드, 집계 단위와 관계 설명을 추가하세요.',
               '아래는 실제 SQLite 스키마에서 읽은 구조입니다. 값의 업무 의미는 자동으로 추측하지 않습니다.', '']
    for table, cols in schemas.items():
        summary.extend([f'## {table}', ', '.join(f'{c[1]} {c[2]}' for c in cols), ''])
    profile = {'version':1,'name':database.stem,'database':os.path.relpath(database,output),
               'state_database':'runtime_state.sqlite','schema_summary':'schema_summary.md',
               'value_aliases':'value_aliases.json','analysis_semantics':'analysis_semantics.json'}
    output.mkdir(parents=True, exist_ok=True)
    for name, value in [('profile.json',profile),('analysis_semantics.json',semantics),('value_aliases.json',{})]:
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    (output/'schema_summary.md').write_text('\n'.join(summary))
    return output/'profile.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(create_profile(args.database, args.output))
