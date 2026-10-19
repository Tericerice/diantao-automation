from deploy.register_all_in_one import register, SCRIPT_DIR, TARGET_ID


def test_register_adds_entry_to_fresh_registry(tmp_path):
    registry = tmp_path / "tools" / "managed_process" / "registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("targets:\n  - id: diantao-anchor\n", encoding="utf-8")

    register(tmp_path)
    source = registry.read_text(encoding="utf-8")
    assert f"  - id: {TARGET_ID}\n" in source
    assert 'name: "点淘一键全部执行"' in source
    assert (SCRIPT_DIR / "一键全部执行.py").as_posix() in source
    assert source.index(f"id: {TARGET_ID}\n") < source.index("id: diantao-anchor\n")


def test_register_replaces_existing_entry_without_duplicating(tmp_path):
    registry = tmp_path / "tools" / "managed_process" / "registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "targets:\n"
        f"  - id: {TARGET_ID}\n"
        '    name: "旧名字"\n'
        '    description: "旧说明"\n\n'
        "  - id: diantao-anchor\n",
        encoding="utf-8",
    )

    register(tmp_path)
    source = registry.read_text(encoding="utf-8")
    assert source.count(f"  - id: {TARGET_ID}\n") == 1
    assert "旧名字" not in source
    assert "旧说明" not in source

    register(tmp_path)
    assert registry.read_text(encoding="utf-8") == source


def test_register_requires_known_anchor(tmp_path):
    registry = tmp_path / "tools" / "managed_process" / "registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("targets:\n  - id: something-else\n", encoding="utf-8")
    try:
        register(tmp_path)
    except ValueError as exc:
        assert "注册位置" in str(exc)
    else:
        raise AssertionError("缺少锚点时应报错")
