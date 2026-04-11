"""Typed models shared across the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True, frozen=True)
class RoleConfig:
    name: str
    description: str = ""
    query_paths: tuple[str, ...] = ()
    edit_paths: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ValidatorConfig:
    name: str
    command: str
    modes: tuple[str, ...] = ("edit",)
    timeout_seconds: int = 300


@dataclass(slots=True, frozen=True)
class GitHubIntegrationConfig:
    enabled: bool = False
    workflow_path: str = ".github/workflows/scoped-control.yml"


@dataclass(slots=True, frozen=True)
class StubIntegrationConfig:
    enabled: bool = False


@dataclass(slots=True, frozen=True)
class IntegrationsConfig:
    github: GitHubIntegrationConfig = GitHubIntegrationConfig()
    slack: StubIntegrationConfig = StubIntegrationConfig()
    email: StubIntegrationConfig = StubIntegrationConfig()


@dataclass(slots=True, frozen=True)
class LimitsConfig:
    max_changed_files: int = 5
    max_diff_lines: int = 400


@dataclass(slots=True, frozen=True)
class ExecutorConfig:
    command: tuple[str, ...] = ()
    query_args: tuple[str, ...] = ()
    edit_args: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExecutorsConfig:
    default: str = "claude_code"
    codex: ExecutorConfig = ExecutorConfig(command=("codex",), query_args=("exec",), edit_args=("exec",))
    claude_code: ExecutorConfig = ExecutorConfig(command=("claude",))


@dataclass(slots=True, frozen=True)
class AppConfig:
    version: int = 1
    default_provider: str = "claude_code"
    roles: tuple[RoleConfig, ...] = ()
    validators: tuple[ValidatorConfig, ...] = ()
    integrations: IntegrationsConfig = IntegrationsConfig()
    limits: LimitsConfig = LimitsConfig()
    executors: ExecutorsConfig = ExecutorsConfig()

    def get_role(self, name: str) -> RoleConfig:
        for role in self.roles:
            if role.name == name:
                return role
        raise KeyError(name)


@dataclass(slots=True, frozen=True)
class SurfaceRecord:
    id: str
    file: str
    line_start: int
    line_end: int
    roles: tuple[str, ...] = ()
    modes: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    hash: str = ""


@dataclass(slots=True, frozen=True)
class IndexRecord:
    root: str
    surfaces: tuple[SurfaceRecord, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ResolverMatch:
    surface: SurfaceRecord
    score: int
    reasons: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExecutionBrief:
    kind: str
    role_name: str
    request: str
    allowed_files: tuple[str, ...] = ()
    target_surfaces: tuple[SurfaceRecord, ...] = ()
    dependency_files: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    validators: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ValidationResult:
    name: str
    ok: bool
    command: str
    output: str = ""


@dataclass(slots=True, frozen=True)
class RunResult:
    kind: str
    ok: bool
    summary: str
    reason: str = ""
    output: str = ""
    changed_files: tuple[str, ...] = ()
    validations: tuple[ValidationResult, ...] = ()


@dataclass(slots=True, frozen=True)
class CheckReport:
    ok: bool
    repo_root: Path
    config_path: Path
    errors: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class RepoPaths:
    root: Path
    control_dir: Path
    config_path: Path
    index_path: Path


@dataclass(slots=True)
class RepoContext:
    paths: RepoPaths
    config: AppConfig | None = None
    config_error: str | None = None


@dataclass(slots=True)
class AppState:
    repo_root: Path
    config_path: Path
    index_path: Path
    config_loaded: bool
    config_error: str | None = None
    last_message: str = ""
    logs: list[str] = field(default_factory=list)

    def append_log(self, message: str) -> None:
        self.logs.append(message)
        self.last_message = message
