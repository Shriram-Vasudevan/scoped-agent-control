# surface: shared.duplicate
# roles: maintainer
# modes: query
# invariants: duplicate ids should warn
# depends_on: shared.helpers

def first_duplicate():
    return 1


# surface: shared.duplicate
# roles: maintainer
# modes: edit
# invariants: duplicate ids should warn again
# depends_on: shared.helpers

def second_duplicate():
    return 2


# roles: maintainer
# modes: query
# invariants: missing surface id should warn
# depends_on: shared.helpers

def malformed_block():
    return 3
