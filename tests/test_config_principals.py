from app.core.config import Settings

LEGACY_KEY = "k" * 32
STRUCTURED_KEY = "s" * 32


def test_legacy_api_key_mapping_remains_owner_compatible() -> None:
    settings = Settings(
        _env_file=None,
        api_keys_json={LEGACY_KEY: "workspace-a"},
    )
    principal = settings.api_keys_json[LEGACY_KEY]

    assert principal.workspace_id == "workspace-a"
    assert principal.role == "owner"
    assert principal.groups == ["*"]


def test_structured_principal_is_parsed() -> None:
    settings = Settings(
        _env_file=None,
        api_keys_json={
            STRUCTURED_KEY: {
                "workspace_id": "workspace-a",
                "subject": "sales-user",
                "role": "viewer",
                "groups": ["sales", "sales", " support "],
            }
        },
    )
    principal = settings.api_keys_json[STRUCTURED_KEY]

    assert principal.subject == "sales-user"
    assert principal.groups == ["sales", "support"]
