"""Drawn Video Board: independent CS Board production workflow."""

__version__ = "1.0.0"


def main(argv=None):
    """Keep dependency failures inside the CLI's JSON/exit-code protocol."""
    try:
        from .cli import main as execute
    except ModuleNotFoundError as error:
        import json
        print(json.dumps({"ok": False, "code": 3, "error": f"缺少依赖 {error.name}，请运行 uv sync --locked"}, ensure_ascii=False))
        return 3
    return execute(argv)
