from dataclasses import dataclass
from pathlib import PurePosixPath

CODE_EXTENSIONS = {
    ".java": "java", ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".css": "css", ".scss": "scss",
    ".less": "less", ".html": "html", ".htm": "html", ".sql": "sql", ".jsp": "jsp", ".jspf": "jsp",
    ".sh": "shell", ".bash": "shell", ".ksh": "shell", ".zsh": "shell", ".ps1": "powershell",
    ".bat": "batch", ".cmd": "batch", ".groovy": "groovy", ".kt": "kotlin", ".scala": "scala",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".go": "go", ".rb": "ruby",
    ".php": "php", ".pl": "perl", ".vue": "vue", ".gradle": "groovy",
}
TEXT_EXTENSIONS = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".rst": "rst", ".log": "log",
                   ".adoc": "asciidoc"}
STRUCTURED_EXTENSIONS = {
    ".json": "json", ".xml": "xml", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".properties": "properties", ".cfg": "ini", ".conf": "conf", ".env": "dotenv", ".xsd": "xml",
    ".wsdl": "xml", ".tf": "hcl",
}
KNOWN_FILENAMES = {
    "dockerfile": ("code", "dockerfile"), "makefile": ("code", "makefile"), "jenkinsfile": ("code", "groovy"),
    "readme": ("text", "text"), "license": ("text", "text"), ".gitignore": ("text", "text"),
    ".gitattributes": ("text", "text"), ".editorconfig": ("structured", "ini"),
}
# Documents and spreadsheets go to dedicated parsers (see parsers/registry.py).
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".odt", ".rtf"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv"}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svgz", ".webp", ".tif", ".tiff",
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".jar", ".war", ".ear", ".class",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib", ".pyc", ".pyo", ".whl", ".bin", ".dat",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".ttf", ".otf", ".woff", ".woff2", ".eot", ".db",
    ".sqlite", ".gguf", ".iso", ".dmg", ".msi",
}


@dataclass(frozen=True, slots=True)
class FileKind:
    file_type: str  # code | text | structured | document | spreadsheet | binary | unknown
    language: str | None


def classify(path: PurePosixPath) -> FileKind:
    name = path.name.lower()
    if name in KNOWN_FILENAMES:
        return FileKind(*KNOWN_FILENAMES[name])
    ext = path.suffix.lower()
    if ext in CODE_EXTENSIONS:
        return FileKind("code", CODE_EXTENSIONS[ext])
    if ext in TEXT_EXTENSIONS:
        return FileKind("text", TEXT_EXTENSIONS[ext])
    if ext in STRUCTURED_EXTENSIONS:
        return FileKind("structured", STRUCTURED_EXTENSIONS[ext])
    if ext in DOCUMENT_EXTENSIONS:
        return FileKind("document", ext[1:])
    if ext in SPREADSHEET_EXTENSIONS:
        return FileKind("spreadsheet", ext[1:])
    if ext in BINARY_EXTENSIONS:
        return FileKind("binary", None)
    return FileKind("unknown", None)


def is_excluded(rel: PurePosixPath, excluded_dirs: set[str]) -> bool:
    return any(part in excluded_dirs for part in rel.parts[:-1])
