// surface: typescript.primary
// roles: maintainer
// modes: query, edit
// invariants: keep main entry stable
// depends_on: shared.helpers

export function primaryHandler(): string {
  return "primary";
}

// surface: typescript.secondary
// roles: reviewer
// modes: query
// invariants: no writes
// depends_on: typescript.primary

export function secondaryHandler(): string {
  return "secondary";
}
