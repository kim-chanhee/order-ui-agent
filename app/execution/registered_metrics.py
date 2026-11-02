"""Compile configured population/subset metrics without model-authored joins.

The profile declares two sources, their stable keys, filters, time fields and
allowed groupings. The same compiler handles any domain with that structure.
"""
import re
from time import perf_counter

from sqlglot import exp

from app.execution.analysis_semantics import load_analysis_semantics, timeline_anchor


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError('Registered metric identifiers must be simple SQLite names')
    return '"' + value + '"'


def compile_registered_metric(plan):
    plan = plan.model_dump(mode='json') if hasattr(plan, 'model_dump') else plan
    metric = plan.get('metric') or {}
    definition = load_analysis_semantics().get('semantic_metrics', {}).get(metric.get('semantic_id'), {})
    if not definition.get('population'):
        return None
    if metric.get('kind') != definition['kind']:
        raise ValueError('Registered metric kind does not match its definition')
    if plan.get('target_conditions') or plan.get('unresolved_constraints'):
        raise ValueError('Registered metric extra conditions must be resolved into supported structured filters')
    population, subset = definition['population'], definition['subset']
    groups = plan.get('group_by', [])
    if set(groups) - set(definition.get('group_by', [])):
        raise ValueError('Unsupported registered metric grouping')
    # Independent metrics cannot silently disappear into a single metric result.
    for extra in plan.get('metrics', []):
        compatible_count = extra.get('kind') == 'count' and extra.get('field') == definition['field'] and not extra.get('semantic_id')
        if extra != metric and extra.get('semantic_id') != metric.get('semantic_id') and not compatible_count:
            raise ValueError('Registered metric execution requires compatible additional metrics')
    period = plan.get('date_range') or {'mode':'all_time'}
    anchor = timeline_anchor()
    ctes = []
    if period['mode'] in {'relative', 'preset'}:
        if period['mode'] == 'relative':
            days = period['relative_days']
        else:
            match = re.fullmatch(r'(?:last_)?(\d+)_?days?', period['preset'])
            if not match:
                raise ValueError('Registered metric preset must specify calendar days')
            days = int(match.group(1))
        if not anchor:
            raise ValueError('Relative registered metrics require a profile timeline_anchor')
        ctes.append(f'data_anchor AS (SELECT MAX({_identifier(anchor[1])}) AS anchor_at FROM {_identifier(anchor[0])})')
    def window(source):
        if period['mode'] == 'all_time':
            return []
        field = 'b.' + _identifier(source['time_field'])
        if period['mode'] in {'relative','preset'}:
            return [f"date({field}) BETWEEN date(anchor_at, '-{days-1} days') AND date(anchor_at)"]
        return [f'date({field}) BETWEEN {exp.convert(period["date_from"]).sql()} AND {exp.convert(period["date_to"]).sql()}']
    def source_cte(name, source, include_groups):
        columns = [f'b.{_identifier(source["key"])} AS entity_key']
        for group in groups if include_groups else []:
            expression = ({'day':"date",'month':"month",'year':"year"}.get(group))
            if expression:
                field = f'b.{_identifier(source["time_field"])}'
                value = f'date({field})' if group == 'day' else f"strftime('{ '%Y-%m' if group == 'month' else '%Y'}', {field})"
            else:
                value = 'b.' + _identifier(group)
            columns.append(f'{value} AS {_identifier(group)}')
        conditions = [f'b.{_identifier(k)} = {exp.convert(v).sql(dialect="sqlite")}' for k,v in source.get('filters', {}).items()]
        conditions += window(source)
        for item in plan.get('filters', []):
            field, value = item['field'], item['value']
            if field in population.get('filters', {}) or field in subset.get('filters', {}):
                if value not in [population.get('filters', {}).get(field), subset.get('filters', {}).get(field)]:
                    raise ValueError('Filter conflicts with registered population/subset semantics')
                continue
            if not include_groups:
                continue
            if field not in definition.get('filter_fields', definition.get('group_by', [])):
                raise ValueError('Unsupported registered population filter')
            column = 'b.' + _identifier(field)
            operator = item['operator']
            if operator in {'eq','neq','gte','gt','lte','lt'}:
                symbol = {'eq':'=','neq':'<>','gte':'>=','gt':'>','lte':'<=','lt':'<'}[operator]
                conditions.append(f'{column} {symbol} {exp.convert(value).sql(dialect="sqlite")}')
            elif operator in {'in','not_in'} and isinstance(value,list) and value:
                conditions.append(f'{column} {"NOT IN" if operator == "not_in" else "IN"} ('+
                    ', '.join(exp.convert(v).sql(dialect='sqlite') for v in value)+')')
            else:
                raise ValueError('Unsupported registered population filter operator')
        from_sql = _identifier(source['table'])+' b'
        if period['mode'] in {'relative','preset'}:
            from_sql += ', data_anchor'
        return f'{name} AS (SELECT DISTINCT '+', '.join(columns)+f' FROM {from_sql}'+(' WHERE '+' AND '.join(conditions) if conditions else '')+')'
    ctes += [source_cte('population', population, True), source_cte('subset', subset, False)]
    projections = ['p.'+_identifier(group) for group in groups]
    projections += ['COUNT(DISTINCT p.entity_key) AS population_count','COUNT(DISTINCT s.entity_key) AS subset_count']
    if definition['kind'] == 'ratio':
        projections.append('ROUND(1.0 * COUNT(DISTINCT s.entity_key) / NULLIF(COUNT(DISTINCT p.entity_key), 0), 4) AS rate')
    sql = 'WITH '+',\n'.join(ctes)+'\nSELECT '+', '.join(projections)+' FROM population p LEFT JOIN subset s ON p.entity_key = s.entity_key'
    if groups:
        sql += ' GROUP BY '+', '.join('p.'+_identifier(g) for g in groups)
    if plan.get('sort'):
        order=[]
        for sort in plan['sort']:
            field=sort['field']
            if field == 'metric':field='rate' if definition['kind']=='ratio' else 'subset_count'
            if field not in {*groups,'population_count','subset_count','rate'}:
                raise ValueError('Unsupported registered metric sort field')
            direction=sort['direction'].upper()
            if direction not in {'ASC','DESC'}:raise ValueError('Invalid sort direction')
            order.append(_identifier(field)+' '+direction)
        sql += ' ORDER BY '+', '.join(order)
    if plan.get('limit') is not None:
        limit=plan['limit']
        if not isinstance(limit,int) or not 1<=limit<=10000:raise ValueError('Invalid limit')
        sql += f' LIMIT {limit}'
    return sql


def try_registered_metric(confirmed_context):
    if confirmed_context is None:
        return None
    start=perf_counter()
    sql=compile_registered_metric(confirmed_context.confirmed_plan)
    if sql is None:
        return None
    from app.execution.fast_sql_agent import FastSqlResult
    from app.execution.schema_tools import get_table_schema
    from app.execution.sql_tools import SqlToolState, make_query_checker_tool, make_execute_query_tool
    from app.execution.sql_ast import extract_physical_tables
    tables=sorted(extract_physical_tables(sql))
    schema=str(get_table_schema.invoke({'table_names':','.join(tables)}))
    state=SqlToolState(inspected_tables=set(tables), schema_context=[schema], require_schema_inspection=True)
    kwargs=dict(question=confirmed_context.semantic_validation_text(), confirmed_plan=confirmed_context.confirmed_plan,
                temporal_context=confirmed_context.temporal_context, state=state)
    checked=make_query_checker_tool(**kwargs).invoke({'sql':sql})
    if checked.startswith('Error:'):
        raise ValueError(checked)
    execute, successes=make_execute_query_tool(**kwargs)
    result=execute.invoke({'sql':checked})
    if not successes:
        raise ValueError(result)
    executed, columns, rows=successes[-1]
    return FastSqlResult(answer=f'등록된 지표 정의로 {len(rows)}행을 조회했습니다.', sql=executed,
        columns=columns, rows=rows, elapsed_ms=round((perf_counter()-start)*1000), tables=tables,
        returned_row_count=len(rows),result_truncated=state.last_result_truncated,memory_eligible=bool(rows),
        execution_route='registered_metric')
