"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global application settings."""

    # LLM providers
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # LLM routing
    llm_primary: str = "claude-sonnet-4-20250514"
    llm_fast: str = "gemini-2.0-flash"
    llm_local: str = "ollama/llama3.1:8b"

    # Language
    default_language: str = "Spanish"

    # FSRS
    fsrs_desired_retention: float = 0.9

    # Storage
    data_dir: str = "./data"
    db_path: str = "./data/polyglot.db"
    chroma_path: str = "./data/chroma"
    profiles_dir: str = "./data/user_profiles"

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    gradio_server_port: int = 7860

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
