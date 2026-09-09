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
    assert "renderNextSteps" in app
    assert "turn.next_steps" in app
    assert "renderInvestigationSteps" in app
    assert "turn.investigation_steps" in app
    assert "investigation-summary" in app
    markdown_source = markdown.read_text(encoding="utf-8")
    assert "NEXT_STEP_HEADINGS" not in markdown_source
    assert "addListItemActions" not in markdown_source


def test_frontend_nginx_configuration_serves_es_module_mime_types() -> None:
    nginx = (FRONTEND_ROOT / "nginx.conf").read_text(encoding="utf-8")

    assert "location ~ \\.mjs$" in nginx
    assert "default_type application/javascript;" in nginx


def test_frontend_workspace_uses_a_full_width_scrollable_conversation() -> None:
    index = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    css = (FRONTEND_ROOT / "css" / "app.css").read_text(encoding="utf-8")

    assert ".shell {" in css
    assert "width: 100%;" in css
    assert "max-width: none;" in css
    assert ".result-panel {" in css
    assert "min-width: 0;" in css
    assert "grid-template-columns" not in css
    assert "max-width: 1440px;" not in css
    assert ".conversation-history {" in css
    assert "overflow-y: auto;" in css
    assert ".toolbar-controls {" in css
    assert ".toolbar-selectors" in css
    assert ".toolbar-actions" in css
    assert 'data-status="completed_with_attention"' in css
    assert 'data-status="failed"' in css
    assert 'data-status="running"' in css
    assert '<h2 id="result-title">Investigation</h2>' in index
    assert ">CHAT<" not in index
    assert "Active investigation" not in index
    assert "investigation-metadata" not in index
    assert 'aria-label="Send message"' in index


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
