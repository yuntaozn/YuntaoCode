from __future__ import annotations

from runtime.source_update import (
    choose_latest_tag,
    compare_release_versions,
    normalize_release_version,
    parse_ls_remote_tags,
    release_page_url,
)


def test_normalize_release_version_accepts_tag_refs() -> None:
    assert normalize_release_version("refs/tags/v0.1.2") == "0.1.2"
    assert normalize_release_version("v0.1.2") == "0.1.2"
    assert normalize_release_version("0.1.2") == "0.1.2"


def test_compare_release_versions() -> None:
    assert compare_release_versions("0.1.0", "0.1.1") == -1
    assert compare_release_versions("0.1.1", "0.1.0") == 1
    assert compare_release_versions("0.1.0", "v0.1.0") == 0


def test_parse_ls_remote_tags_filters_non_semver_tags() -> None:
    output = "\n".join([
        "abc123 refs/tags/v0.1.0",
        "def456 refs/tags/notes",
        "fedcba refs/tags/v0.2.0",
    ])

    tags = parse_ls_remote_tags(output)

    assert [tag["tag"] for tag in tags] == ["v0.1.0", "v0.2.0"]
    assert choose_latest_tag(tags) == {"tag": "v0.2.0", "version": "0.2.0", "sha": "fedcba"}


def test_release_page_urls_for_public_hosts() -> None:
    assert (
        release_page_url("https://github.com/yuntaozn/YuntaoCode.git", "v0.1.0")
        == "https://github.com/yuntaozn/YuntaoCode/releases/tag/v0.1.0"
    )
    assert (
        release_page_url("https://gitee.com/yuntaozn/YuntaoCode.git", "v0.1.0")
        == "https://gitee.com/yuntaozn/YuntaoCode/releases/tag/v0.1.0"
    )
