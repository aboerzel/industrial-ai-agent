from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def test_frontend_static_assets_are_present_and_use_es_modules() -> None:
    index = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    css = FRONTEND_ROOT / "css" / "app.css"
    api = FRONTEND_ROOT / "js" / "api.js"
    markdown = FRONTEND_ROOT / "js" / "markdown.js"
    marked = FRONTEND_ROOT / "js" / "vendor" / "marked.esm.js"
    dompurify = FRONTEND_ROOT / "js" / "vendor" / "purify.es.mjs"
    app = (FRONTEND_ROOT / "js" / "app.js").read_text(encoding="utf-8")

    assert css.is_file()
    assert api.is_file()
    assert markdown.is_file()
    assert marked.is_file()
    assert dompurify.is_file()
    assert '<script type="module" src="js/app.js"></script>' in index
    assert 'from "./api.js"' in app
    assert 'from "./markdown.js"' in app


def test_frontend_workspace_keeps_the_input_panel_fixed_and_allows_result_growth() -> None:
    css = (FRONTEND_ROOT / "css" / "app.css").read_text(encoding="utf-8")

    assert ".shell {\n  width: calc(100% - 32px);" in css
    assert "grid-template-columns: 495px minmax(0, 1fr);" in css
    assert ".investigation-panel,\n.result-panel {\n  min-width: 0;" in css
    assert "@media (max-width: 760px)" in css
    assert ".workspace {\n    grid-template-columns: 1fr;" in css


def test_frontend_http_transport_is_isolated_to_api_module() -> None:
    api = (FRONTEND_ROOT / "js" / "api.js").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "js" / "app.js").read_text(encoding="utf-8")

    assert 'const API_BASE_URL = "http://localhost:8000"' in api
    assert "fetch(" in api
    assert "fetch(" not in app
    assert "createRun" in api
    assert "getRun" in api


def test_frontend_has_no_secrets_or_backend_implementation_imports() -> None:
    frontend_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (FRONTEND_ROOT / "js").glob("*.js")
    )
    forbidden = (
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "industrial_ai_agent",
        "import mcp",
        "import langgraph",
        "import langchain",
        "import ollama",
    )

    assert all(value not in frontend_sources for value in forbidden)
