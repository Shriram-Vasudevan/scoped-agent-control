# surface: demo.primary
# roles: maintainer
# modes: query, edit
# invariants: keep function name editable_value
# depends_on: demo.helper

def editable_value():
    return 1


# surface: demo.helper
# roles: maintainer
# modes: query
# invariants: helper remains read only

def helper_value():
    return 5
