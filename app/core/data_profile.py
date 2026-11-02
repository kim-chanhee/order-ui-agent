"""Select a database and its metadata together, before importing DB modules."""
import json
import os
from pathlib import Path

PROFILE_FIELDS = {
    'database': 'ORDER_UI_DB_PATH',
    'state_database': 'ORDER_UI_STATE_DB_PATH',
    'schema_summary': 'SCHEMA_SUMMARY_PATH',
    'value_aliases': 'SCHEMA_VALUE_ALIASES_PATH',
    'analysis_semantics': 'ANALYSIS_SEMANTICS_PATH',
}


def apply_data_profile(path=None):
    configured = str(path or os.environ.get('DATA_PROFILE_PATH', '')).strip()
    if not configured:
        return None
    root = Path(__file__).resolve().parents[2]
    source = Path(configured).expanduser()
    if not source.is_absolute():
        source = root / source
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or set(payload) - {'version', 'name', *PROFILE_FIELDS}:
        raise ValueError('Data profile must contain only documented profile fields')
    if payload.get('version') != 1 or not all(payload.get(key) for key in PROFILE_FIELDS):
        raise ValueError('Data profile version 1 requires database, state_database, schema_summary, value_aliases, analysis_semantics')
    resolved = {}
    for key, env in PROFILE_FIELDS.items():
        value = Path(payload[key]).expanduser()
        value = (source.parent / value).resolve() if not value.is_absolute() else value.resolve()
        if key != 'state_database' and not value.is_file():
            raise ValueError(f'Data profile file is missing: {key}')
        resolved[env] = str(value)
    if resolved['ORDER_UI_DB_PATH'] == resolved['ORDER_UI_STATE_DB_PATH']:
        raise ValueError('Query database and state database must be separate')
    # Apply atomically after validation. One selection overrides stale per-file
    # settings together, so a new database never inherits the old domain docs.
    os.environ.update(resolved)
    return payload
