from ofinto.config import PromptClientConfig


def test_config_reads_dotenv_and_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_MODEL", "OPENAI_API_KEY", "OPENAI_TIMEOUT", "OPENAI_MAX_RETRIES", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "OPENAI_MODEL=file-model\nOPENAI_API_KEY=test-key\n"
        "OPENAI_TIMEOUT=90\nOPENAI_MAX_RETRIES=3\n",
    )
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")

    config = PromptClientConfig.from_env()

    assert config.model == "environment-model"
    assert config.api_key == "test-key"
    assert config.timeout == 90
    assert config.max_retries == 3
    assert "test-key" not in repr(config)
