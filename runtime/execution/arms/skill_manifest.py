"""Self-describing skill definition.

Each skill carries a rich, self-describing manifest that includes:

- Detailed usage guidelines (the "soul" of the plugin)
- Capability tags (Interactive, Read, Write)
- Default prompts for user onboarding
- UI metadata (icons, colors, categories)

This allows the Agent to make intelligent decisions about which
skill to use based on rich metadata rather than just tool names.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SkillCapability(StrEnum):
    """Capability tags that describe what a skill can do.

    The three-tier classification is an internal convention used
    to gate tool access and surface UI affordances consistently.
    """

    INTERACTIVE = "Interactive"
    READ = "Read"
    WRITE = "Write"


class SkillCategory(StrEnum):
    """Categories for skill organization."""

    ENGINEERING = "Engineering"
    PRODUCTIVITY = "Productivity"
    COMMUNICATION = "Communication"
    ANALYSIS = "Analysis"
    CREATIVE = "Creative"


@dataclass(frozen=True)
class SkillInterface:
    """UI and metadata interface for a skill.

    This is the information that can be shown to users or used
    by the Agent for skill selection.
    """

    display_name: str
    short_description: str
    long_description: str
    category: SkillCategory = SkillCategory.ENGINEERING
    capabilities: list[SkillCapability] = field(
        default_factory=lambda: [SkillCapability.READ]
    )
    default_prompts: list[str] = field(default_factory=list)
    developer_name: str = "octopus-agent"
    website_url: str = ""
    privacy_policy_url: str = ""
    terms_of_service_url: str = ""
    brand_color: str = "#10A37F"


@dataclass(frozen=True)
class SkillDefinition:
    """A complete, self-describing skill definition.

    Usage guidelines are embedded directly in the description,
    not just a short string. The description IS the instruction
    manual for the Agent.
    """

    name: str
    version: str = "0.1.0"
    description: str = ""  # Detailed usage guidelines
    author: str = "octopus-agent"
    homepage: str = ""
    repository: str = ""
    license: str = "MIT"
    keywords: list[str] = field(default_factory=list)

    # Integration points
    tool_handler: str = ""  # ToolRegistry handler name
    extension_factory: str = ""  # ExtensionRegistry factory name

    # UI and Agent metadata
    interface: SkillInterface | None = None

    # File paths (relative)
    skills_dir: str = ""
    scripts_dir: str = ""
    assets_dir: str = ""

    # Dependencies
    requires_skills: list[str] = field(default_factory=list)
    requires_packages: list[str] = field(default_factory=list)

    def to_tool_schema(self) -> dict:
        """Convert to ToolRegistry-compatible schema."""
        return {
            "name": self.name,
            "description": self.description[:500],  # Truncate for tool prompt
            "interface": {
                "display_name": self.interface.display_name
                if self.interface
                else self.name,
                "capabilities": [c.value for c in self.capabilities]
                if self.interface
                else [],
            },
        }

    def to_extension_config(self) -> dict:
        """Convert to ExtensionRegistry configuration."""
        return {
            "skill_id": self.name,
            "display_name": self.interface.display_name
            if self.interface
            else self.name,
            "config_key": f"skills.{self.name}.enable",
            "dependencies": self.requires_skills,
        }

    @property
    def capabilities(self) -> list[SkillCapability]:
        if self.interface:
            return self.interface.capabilities
        return []

    @property
    def is_interactive(self) -> bool:
        return SkillCapability.INTERACTIVE in self.capabilities

    @property
    def is_read_only(self) -> bool:
        return (
            SkillCapability.READ in self.capabilities
            and SkillCapability.WRITE not in self.capabilities
        )

    @property
    def can_modify(self) -> bool:
        return SkillCapability.WRITE in self.capabilities


class SkillBuilder:
    """Fluent builder for SkillDefinition.

    Usage:
        skill = (
            SkillBuilder("shell_exec")
            .version("1.0.0")
            .description(
                "Execute shell commands on the local system. "
                "Use for: running scripts, installing packages, checking system info. "
                "Do NOT use for: long-running processes (use background_exec instead)."
            )
            .capabilities(SkillCapability.INTERACTIVE, SkillCapability.WRITE)
            .category(SkillCategory.ENGINEERING)
            .default_prompt("Run npm install", "Check disk usage")
            .build()
        )
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._version = "0.1.0"
        self._description = ""
        self._author = "octopus-agent"
        self._homepage = ""
        self._keywords: list[str] = []
        self._tool_handler = ""
        self._extension_factory = ""
        self._capabilities: list[SkillCapability] = []
        self._category = SkillCategory.ENGINEERING
        self._default_prompts: list[str] = []
        self._requires_skills: list[str] = []
        self._requires_packages: list[str] = []

    def version(self, version: str) -> SkillBuilder:
        self._version = version
        return self

    def description(self, desc: str) -> SkillBuilder:
        self._description = desc
        return self

    def author(self, author: str) -> SkillBuilder:
        self._author = author
        return self

    def homepage(self, url: str) -> SkillBuilder:
        self._homepage = url
        return self

    def keywords(self, *kws: str) -> SkillBuilder:
        self._keywords.extend(kws)
        return self

    def tool_handler(self, handler: str) -> SkillBuilder:
        self._tool_handler = handler
        return self

    def extension_factory(self, factory: str) -> SkillBuilder:
        self._extension_factory = factory
        return self

    def capabilities(self, *caps: SkillCapability) -> SkillBuilder:
        self._capabilities = list(caps)
        return self

    def category(self, cat: SkillCategory) -> SkillBuilder:
        self._category = cat
        return self

    def default_prompt(self, *prompts: str) -> SkillBuilder:
        self._default_prompts.extend(prompts)
        return self

    def requires_skill(self, *skills: str) -> SkillBuilder:
        self._requires_skills.extend(skills)
        return self

    def requires_package(self, *packages: str) -> SkillBuilder:
        self._requires_packages.extend(packages)
        return self

    def build(self) -> SkillDefinition:
        interface = SkillInterface(
            display_name=self._name.replace("_", " ").title(),
            short_description=self._description[:200],
            long_description=self._description,
            category=self._category,
            capabilities=self._capabilities,
            default_prompts=self._default_prompts,
        )

        return SkillDefinition(
            name=self._name,
            version=self._version,
            description=self._description,
            author=self._author,
            homepage=self._homepage,
            keywords=self._keywords,
            tool_handler=self._tool_handler,
            extension_factory=self._extension_factory,
            interface=interface,
            requires_skills=self._requires_skills,
            requires_packages=self._requires_packages,
        )


# ── Built-in skill definitions ─────────────────────────────────

SHELL_EXEC_SKILL = (
    SkillBuilder("shell_exec")
    .version("1.0.0")
    .description(
        "Execute shell commands on the local system with environment state persistence.\n\n"
        "USE FOR:\n"
        "- Running scripts and one-off commands\n"
        "- Installing packages (npm, pip, apt, etc.)\n"
        "- Checking system information (disk usage, memory, processes)\n"
        "- File operations within allowed directories\n"
        "- Git operations (status, diff, commit, push)\n\n"
        "DO NOT USE FOR:\n"
        "- Long-running processes (use background_exec instead)\n"
        "- Interactive programs that require user input\n"
        "- Destructive operations on system directories\n\n"
        "NOTES:\n"
        "- Each command inherits the previous command's environment (cwd, env vars)\n"
        "- Dangerous commands (rm, mv, etc.) are blocked by the safe_rm protector\n"
        "- Output is capped at 1MB to prevent memory issues"
    )
    .keywords("shell", "bash", "command", "terminal", "exec")
    .capabilities(
        SkillCapability.INTERACTIVE,
        SkillCapability.READ,
        SkillCapability.WRITE,
    )
    .category(SkillCategory.ENGINEERING)
    .default_prompt(
        "List files in current directory",
        "Install the project dependencies",
        "Check disk usage",
    )
    .build()
)

COMPUTER_USE_SKILL = (
    SkillBuilder("computer_use")
    .version("1.0.0")
    .description(
        "Control the computer's mouse, keyboard, and screen for UI automation.\n\n"
        "USE FOR:\n"
        "- Automating GUI applications\n"
        "- Taking screenshots for visual analysis\n"
        "- Clicking buttons, filling forms, navigating menus\n"
        "- Testing user interfaces\n\n"
        "DO NOT USE FOR:\n"
        "- Accessing sensitive applications without user consent\n"
        "- Automating security-critical operations\n\n"
        "NOTES:\n"
        "- Each action cycle captures a screenshot for LLM analysis\n"
        "- Maximum 50 actions per session to prevent runaway loops\n"
        "- Requires user authorization before first use"
    )
    .keywords("computer", "mouse", "keyboard", "screenshot", "automation")
    .capabilities(
        SkillCapability.INTERACTIVE,
        SkillCapability.READ,
        SkillCapability.WRITE,
    )
    .category(SkillCategory.ENGINEERING)
    .default_prompt(
        "Take a screenshot of the current screen",
        "Click the submit button on the form",
        "Type 'hello' into the active text field",
    )
    .build()
)

FILE_EDIT_SKILL = (
    SkillBuilder("file_edit")
    .version("1.0.0")
    .description(
        "Read and edit files in the workspace.\n\n"
        "USE FOR:\n"
        "- Reading file contents\n"
        "- Editing code files\n"
        "- Creating new files\n"
        "- Searching file contents\n\n"
        "DO NOT USE FOR:\n"
        "- Editing binary files\n"
        "- Modifying files outside the workspace\n"
        "- Deleting critical project files\n\n"
        "NOTES:\n"
        "- All edits are tracked in the StepEntry system\n"
        "- Large files (>100KB) are read in chunks"
    )
    .keywords("file", "edit", "read", "write", "code")
    .capabilities(SkillCapability.READ, SkillCapability.WRITE)
    .category(SkillCategory.ENGINEERING)
    .default_prompt(
        "Read the main.py file",
        "Add a logging statement to the function",
        "Create a new configuration file",
    )
    .build()
)

# Registry of all built-in skills
BUILTIN_SKILLS: list[SkillDefinition] = [
    SHELL_EXEC_SKILL,
    COMPUTER_USE_SKILL,
    FILE_EDIT_SKILL,
]
