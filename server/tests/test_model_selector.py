"""The five models are declarative config, and capabilities are flags."""

import pytest

from resumix_server import model_selector as ms

TOML = """
[provider]
api_key_env = "PROVIDER_KEY"
base_url_env = "PROVIDER_URL"
base_url = "https://provider.example/v1"

[defaults]
max_tokens = 8000
timeout_seconds = 30

[models.detect]
model = "detect-1"
structured_output = "none"
max_tokens = 100

[models.summary]
model = "summary-1"
temperature = 0.1
reasoning_effort = "low"
thinking = "on"
web_search = true

[models.cv]
model = "cv-1"
structured_output = "json_schema_strict"
thinking = "on"
thinking_budget = 6000
reasoning_effort = "high"

[models.review]
model = "review-1"
structured_output = "none"
temperature = 0.0

[models.highlight]
model = "highlight-1"
thinking = "off"
reasoning_effort = "high"
"""


def write(tmp_path, toml):
    (tmp_path / "models.toml").write_text(toml)
    return tmp_path


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """build_model loads .env; the developer's own must not leak in here."""
    monkeypatch.setattr(ms, "load_dotenv", lambda: None)


@pytest.fixture
def config(tmp_path):
    return ms.load_model_config(write(tmp_path, TOML))


@pytest.fixture
def provider_key(monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY", "x")


# --- parsing + validation ---------------------------------------------------
def test_parses_the_five_roles(config):
    assert sorted(config.models) == ["cv", "detect", "highlight", "review", "summary"]
    assert config.models["review"].structured_output == "none"
    assert config.models["review"].temperature == 0.0
    assert config.models["cv"].thinking_budget == 6000
    assert config.models["summary"].web_search is True
    assert config.models["cv"].web_search is False  # defaulted
    assert config.max_tokens == 8000
    assert config.timeout == 30


def test_a_missing_role_is_rejected(tmp_path):
    toml = TOML.replace('[models.highlight]', '[models.unused]')
    with pytest.raises(ValueError, match=r"unknown model role"):
        ms.load_model_config(write(tmp_path, toml))


def test_leaving_a_role_out_is_rejected(tmp_path):
    toml = TOML[: TOML.index("[models.highlight]")]
    with pytest.raises(ValueError, match=r"models\.highlight"):
        ms.load_model_config(write(tmp_path, toml))


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown key"):
        ms.load_model_config(write(tmp_path, TOML + '\ntyop = 1\n'))


def test_missing_model_name_is_rejected(tmp_path):
    toml = TOML.replace('model = "cv-1"', "")
    with pytest.raises(ValueError, match="missing 'model'"):
        ms.load_model_config(write(tmp_path, toml))


def test_a_thinking_mode_that_does_not_exist_is_rejected(tmp_path):
    toml = TOML.replace('thinking = "off"', 'thinking = "maybe"')
    with pytest.raises(ValueError, match="expected one of"):
        ms.load_model_config(write(tmp_path, toml))


def test_a_budget_without_thinking_is_rejected(tmp_path):
    # A budget caps reasoning tokens; with thinking off there are none to cap.
    toml = TOML.replace('thinking = "off"', 'thinking = "off"\nthinking_budget = 6000')
    with pytest.raises(ValueError, match="thinking_budget needs"):
        ms.load_model_config(write(tmp_path, toml))


@pytest.mark.parametrize(
    "bad",
    ['reasoning_effort = "extreme"', 'structured_output = "yaml"'],
)
def test_capability_values_are_checked_against_the_allowed_set(tmp_path, bad):
    toml = TOML.replace('thinking = "off"\nreasoning_effort = "high"', bad)
    with pytest.raises(ValueError, match="expected one of"):
        ms.load_model_config(write(tmp_path, toml))


# --- [provider] --------------------------------------------------------------
def test_missing_provider_table_is_rejected(tmp_path):
    toml = TOML[TOML.index("[defaults]"):]
    with pytest.raises(ValueError, match=r"\[provider\]"):
        ms.load_model_config(write(tmp_path, toml))


def test_missing_provider_key_is_rejected(tmp_path):
    toml = TOML.replace('api_key_env = "PROVIDER_KEY"', "")
    with pytest.raises(ValueError, match="api_key_env"):
        ms.load_model_config(write(tmp_path, toml))


def test_provider_without_any_base_url_is_rejected(tmp_path):
    toml = TOML.replace('base_url_env = "PROVIDER_URL"', "").replace(
        'base_url = "https://provider.example/v1"', ""
    )
    with pytest.raises(ValueError, match="base_url"):
        ms.load_model_config(write(tmp_path, toml))


def test_unknown_provider_key_is_rejected(tmp_path):
    toml = TOML.replace("[provider]", "[provider]\ntyop = 1")
    with pytest.raises(ValueError, match="unknown key"):
        ms.load_model_config(write(tmp_path, toml))


# --- numbered providers (use_alternate_provider = N) ------------------------
CV_ON_PROVIDER_2 = TOML.replace('model = "cv-1"', 'model = "cv-1"\nuse_alternate_provider = 2')


@pytest.fixture
def provider_2(monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY2", "y")
    monkeypatch.setenv("PROVIDER_URL2", "https://alt.example/v1")


def test_a_model_can_call_a_numbered_provider(tmp_path, provider_key, provider_2):
    config = ms.load_model_config(write(tmp_path, CV_ON_PROVIDER_2))
    models = ms.build_models(config, quiet=True)
    assert str(models["cv"].llm.base_url).startswith("https://alt.example/v1")
    assert models["cv"].llm.api_key == "y"
    assert str(models["summary"].llm.base_url).startswith("https://provider.example/v1")
    assert models["summary"].llm.api_key == "x"


def test_a_numbered_key_is_only_needed_by_models_that_use_it(tmp_path, monkeypatch, provider_key):
    monkeypatch.delenv("PROVIDER_KEY2", raising=False)
    config = ms.load_model_config(write(tmp_path, CV_ON_PROVIDER_2))
    ms.build_model("summary", config, quiet=True)
    with pytest.raises(RuntimeError, match="PROVIDER_KEY2"):
        ms.build_model("cv", config, quiet=True)


def test_a_numbered_provider_does_not_inherit_the_literal_base_url(tmp_path, monkeypatch):
    # [provider]'s literal base_url is a different endpoint; provider 2 must
    # name its own.
    monkeypatch.setenv("PROVIDER_KEY2", "y")
    monkeypatch.delenv("PROVIDER_URL2", raising=False)
    config = ms.load_model_config(write(tmp_path, CV_ON_PROVIDER_2))
    with pytest.raises(RuntimeError, match="PROVIDER_URL2"):
        ms.build_model("cv", config, quiet=True)


def test_numbering_a_provider_without_base_url_env_is_rejected(tmp_path):
    toml = CV_ON_PROVIDER_2.replace('base_url_env = "PROVIDER_URL"', "")
    with pytest.raises(ValueError, match="base_url_env"):
        ms.load_model_config(write(tmp_path, toml))


@pytest.mark.parametrize("bad", ["true", "0", '"2"'])
def test_use_alternate_provider_must_be_a_provider_number(tmp_path, bad):
    # `true` is the trap: Python's True == 1 would silently mean [provider].
    toml = TOML.replace('model = "cv-1"', f'model = "cv-1"\nuse_alternate_provider = {bad}')
    with pytest.raises(ValueError, match="use_alternate_provider"):
        ms.load_model_config(write(tmp_path, toml))


def test_base_url_env_wins_over_literal(config, monkeypatch):
    provider = config.provider
    monkeypatch.setenv("PROVIDER_URL", "https://override.example/v1")
    assert provider.resolved_base_url() == "https://override.example/v1"
    monkeypatch.delenv("PROVIDER_URL")
    assert provider.resolved_base_url() == "https://provider.example/v1"


# --- env overrides -----------------------------------------------------------
def test_env_overrides_the_fundamental_settings(tmp_path, monkeypatch):
    # summary has no thinking_budget in the fixture, so overriding thinking
    # away from "on" doesn't collide with it (unlike cv).
    monkeypatch.setenv("RESUMIX_SUMMARY_MODEL", "summary-2")
    monkeypatch.setenv("RESUMIX_SUMMARY_TEMPERATURE", "0.7")
    monkeypatch.setenv("RESUMIX_SUMMARY_THINKING", "off")
    monkeypatch.setenv("RESUMIX_SUMMARY_STRUCTURED_OUTPUT", "json_schema")
    config = ms.load_model_config(write(tmp_path, TOML))
    summary = config.models["summary"]
    assert summary.model == "summary-2"
    assert summary.temperature == 0.7
    assert summary.thinking == "off"
    assert summary.structured_output == "json_schema"
    # Untouched roles keep their models.toml values.
    assert config.models["cv"].model == "cv-1"


def test_a_non_numeric_temperature_override_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMIX_CV_TEMPERATURE", "hot")
    with pytest.raises(ValueError, match="RESUMIX_CV_TEMPERATURE"):
        ms.load_model_config(write(tmp_path, TOML))


def test_env_moves_a_role_to_a_numbered_provider(tmp_path, monkeypatch, provider_2):
    monkeypatch.setenv("RESUMIX_CV_USE_ALTERNATE_PROVIDER", "2")
    config = ms.load_model_config(write(tmp_path, TOML))
    cv = ms.build_model("cv", config, quiet=True)
    assert str(cv.llm.base_url).startswith("https://alt.example/v1")
    assert config.models["summary"].use_alternate_provider == 1


def test_a_non_integer_provider_override_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMIX_CV_USE_ALTERNATE_PROVIDER", "yes")
    with pytest.raises(ValueError, match="RESUMIX_CV_USE_ALTERNATE_PROVIDER"):
        ms.load_model_config(write(tmp_path, TOML))


def test_env_overrides_reasoning_effort_and_thinking_budget(tmp_path, monkeypatch):
    # summary has no thinking_budget in the fixture, so it can take one from
    # the environment without first needing to clear anything.
    monkeypatch.setenv("RESUMIX_SUMMARY_REASONING_EFFORT", "high")
    monkeypatch.setenv("RESUMIX_SUMMARY_THINKING_BUDGET", "4000")
    config = ms.load_model_config(write(tmp_path, TOML))
    summary = config.models["summary"]
    assert summary.reasoning_effort == "high"
    assert summary.thinking_budget == 4000


def test_a_non_integer_thinking_budget_override_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMIX_SUMMARY_THINKING_BUDGET", "lots")
    with pytest.raises(ValueError, match="RESUMIX_SUMMARY_THINKING_BUDGET"):
        ms.load_model_config(write(tmp_path, TOML))


def test_an_empty_thinking_budget_override_unsets_it(tmp_path, monkeypatch):
    # cv declares both thinking_budget and reasoning_effort in the fixture;
    # the budget normally wins (test_thinking_budget_drops_conflicting_
    # reasoning_effort). Unsetting it from the environment is how
    # reasoning_effort gets back into the request without editing models.toml.
    monkeypatch.setenv("RESUMIX_CV_THINKING_BUDGET", "")
    config = ms.load_model_config(write(tmp_path, TOML))
    cv = config.models["cv"]
    assert cv.thinking_budget is None
    assert cv.effective_reasoning_effort() == "high"


def test_an_empty_reasoning_effort_override_unsets_it(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMIX_SUMMARY_REASONING_EFFORT", "")
    config = ms.load_model_config(write(tmp_path, TOML))
    assert config.models["summary"].reasoning_effort is None


# --- request shaping --------------------------------------------------------
def test_thinking_on_sends_the_switch_and_the_budget(config):
    assert config.models["cv"].thinking_extra_body() == {
        "enable_thinking": True,
        "thinking_budget": 6000,
    }
    assert config.models["summary"].thinking_extra_body() == {"enable_thinking": True}


def test_thinking_off_forces_reasoning_off(config):
    highlight = config.models["highlight"]
    assert highlight.thinking_extra_body() == {"enable_thinking": False}
    # Nothing to spend effort on once thinking is off, so it is dropped.
    assert highlight.effective_reasoning_effort() is None


def test_thinking_auto_sends_nothing(tmp_path):
    toml = TOML.replace('thinking = "off"', 'thinking = "auto"')
    config = ms.load_model_config(write(tmp_path, toml))
    assert config.models["highlight"].thinking_extra_body() is None
    assert config.models["highlight"].effective_reasoning_effort() == "high"


def test_thinking_budget_drops_conflicting_reasoning_effort(config):
    # A budget and reasoning_effort are mutually exclusive; summary has no
    # budget at all, so its effort survives.
    assert config.models["cv"].effective_reasoning_effort() is None
    assert config.models["summary"].effective_reasoning_effort() == "low"


# --- building ---------------------------------------------------------------
def test_build_models_carries_the_declared_settings(config, provider_key):
    models = ms.build_models(config, quiet=True)
    assert sorted(models) == ["cv", "detect", "highlight", "review", "summary"]
    summary = models["summary"]
    assert summary.model == "summary-1"
    assert summary.temperature == 0.1
    assert summary.reasoning_effort == "low"
    assert summary.supports_web_search is True
    assert summary.max_tokens == 8000
    assert models["detect"].max_tokens == 100  # its own, over [defaults]
    assert models["cv"].extra_body == {"enable_thinking": True, "thinking_budget": 6000}
    assert models["highlight"].temperature is None  # not declared -> provider default
    # 0.0 is a value, not "unset": it must reach the request.
    assert models["review"].temperature == 0.0


def test_the_shipped_reviewer_does_not_sample():
    """The review loop converges only if the same CV draws the same verdict
    twice. That used to be pinned in code; it is the review role's own setting
    now, so the shipped file is what has to hold it."""
    review = ms.load_model_config().models["review"]
    assert review.temperature == 0
    assert review.structured_output == "none"      # the reply is text


def test_build_model_raises_naming_the_provider_var(config, monkeypatch):
    monkeypatch.delenv("PROVIDER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PROVIDER_KEY"):
        ms.build_model("cv", config)


def test_unknown_role_is_a_key_error(config):
    with pytest.raises(KeyError):
        ms.build_model("proofreader", config)


# --- ModelSelector capabilities --------------------------------------------
def test_response_format_follows_declared_capability():
    schema = {"type": "object"}
    strict = ms.ModelSelector("p", "k", "https://x/v1", "m",
                              structured_output="json_schema_strict")
    hint = ms.ModelSelector("p", "k", "https://x/v1", "m",
                            structured_output="json_schema")
    plain = ms.ModelSelector("p", "k", "https://x/v1", "m",
                             structured_output="json_object")
    none = ms.ModelSelector("p", "k", "https://x/v1", "m",
                            structured_output="none")

    assert strict.response_format("n", schema)["json_schema"]["strict"] is True
    assert hint.response_format("n", schema)["json_schema"]["strict"] is False
    assert plain.response_format("n", schema) == {"type": "json_object"}
    assert none.response_format("n", schema) is None
    # No schema to send: fall back to plain JSON mode.
    assert strict.response_format("n") == {"type": "json_object"}


def test_with_web_search_is_a_noop_without_the_capability():
    plain = ms.ModelSelector("p", "k", "https://x/v1", "m", supports_web_search=False)
    assert plain.with_web_search() is plain

    searchy = ms.ModelSelector("p", "k", "https://x/v1", "m",
                               supports_web_search=True,
                               extra_body={"enable_thinking": False})
    clone = searchy.with_web_search()
    # Merges rather than replacing, so provider keys already set survive.
    assert clone.extra_body == {"enable_thinking": False, "enable_search": True}
    assert searchy.extra_body == {"enable_thinking": False}


def test_with_rejects_unknown_overrides():
    sel = ms.ModelSelector("p", "k", "https://x/v1", "m")
    with pytest.raises(TypeError):
        sel.with_(temprature=0.5)
