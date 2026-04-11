# surface: python.primary
# roles: maintainer, reviewer
# modes: query, edit
# invariants: keep main entry stable
# depends_on: shared.helpers

def primary_handler():
    return "primary"


# surface: python.secondary
# roles: reviewer
# modes: query
# invariants: no writes
# depends_on: python.primary

def secondary_handler():
    return "secondary"
