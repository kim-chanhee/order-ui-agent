"""Check identifier roles through CTEs before accepting a relational join.

Only configured roles are authoritative. Unknown roles remain unknown rather
than guessing that every pair of columns ending in `_id` is incompatible.
"""
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.execution.analysis_semantics import load_analysis_semantics
from app.execution.sql_ast import SqlContractViolation


def validate_join_roles(tree: exp.Query) -> None:
    config = load_analysis_semantics()
    rules = config.get('column_roles', [])
    identifiers = {}
    for entity, definition in config.get('entity_roles', {}).items():
        for field in definition.get('identifier_fields', []):
            identifiers.setdefault(field.casefold(), set()).add(entity.casefold())

    def roles(column, scope, seen=None):
        seen = set() if seen is None else set(seen)
        key = (id(scope), column.table, column.name)
        if key in seen:
            return set()
        seen.add(key)
        name = column.name.casefold()
        if column.table:
            sources = [(column.table, scope.sources.get(column.table))]
            if sources[0][1] is None and scope.parent:
                return roles(column, scope.parent, seen)
        else:
            sources = list(scope.selected_sources.items())
            sources = [(alias, value[1]) for alias, value in sources]
            if len(sources) != 1:
                # An anchor CTE often accompanies the fact table. A configured
                # identifier name still has its declared entity role even when
                # several sources make physical column resolution unavailable.
                return identifiers.get(name, set())
        result = set()
        for alias, source in sources:
            if isinstance(source, Scope):
                for projection in source.expression.selects:
                    if projection.alias_or_name.casefold() != name:
                        continue
                    value = projection.this if isinstance(projection, exp.Alias) else projection
                    while isinstance(value, (exp.Paren, exp.Cast)):
                        value = value.this
                    if isinstance(value, exp.Column):
                        result |= roles(value, source, seen)
                continue
            if not isinstance(source, exp.Table):
                continue
            matched = [r for r in rules if r.get('table', '').casefold() == source.name.casefold()
                       and r.get('field', '').casefold() == name]
            if not matched:
                result |= identifiers.get(name, set())
            for rule in matched:
                if rule.get('entity'):
                    result.add(rule['entity'].casefold())
                discriminator = rule.get('discriminator')
                if not discriminator:
                    continue
                for predicate in scope.expression.find_all(exp.EQ):
                    if predicate.find_ancestor(exp.Select) is not scope.expression:
                        continue
                    for left, right in [(predicate.this, predicate.expression), (predicate.expression, predicate.this)]:
                        if (isinstance(left, exp.Column) and left.name == discriminator
                            and (left.table == alias or not left.table and len(scope.selected_sources) == 1)
                            and isinstance(right, exp.Literal)):
                            entity = rule.get('entities', {}).get(right.this)
                            if entity:
                                result.add(entity.casefold())
        return result

    for scope in traverse_scope(tree):
        for predicate in scope.expression.find_all(exp.EQ):
            if predicate.find_ancestor(exp.Select) is not scope.expression:
                continue
            left, right = predicate.this, predicate.expression
            if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                continue
            left_roles, right_roles = roles(left, scope), roles(right, scope)
            if left_roles and right_roles and left_roles.isdisjoint(right_roles):
                raise SqlContractViolation('incompatible_join_keys',
                    f'{left.sql()} identifies {sorted(left_roles)}, but {right.sql()} identifies '
                    f'{sorted(right_roles)}. Join columns representing the same entity; inspect the '
                    'relationship direction and qualifier. An empty result does not validate this join.')
