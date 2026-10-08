from deploy.register_one_click import register


def test_register_splits_existing_entry_and_preserves_other_targets(tmp_path):
    registry = tmp_path / "tools" / "managed_process" / "registry.yaml"
    registry.parent.mkdir(parents=True)
    anchor = '  - id: diantao-anchor\n    name: "主播打卡粉丝礼"\n'
    prefix = 'api_version: "process-target-registry/v1"\n\ntargets:\n'
    registry.write_text(
        prefix + '  - id: diantao-one-click\n    name: "旧入口"\n'
        '    description: "全部九项任务"\n\n' + anchor,
        encoding="utf-8",
    )

    register(tmp_path)
    source = registry.read_text(encoding="utf-8")
    assert source.startswith(prefix)
    assert source.endswith(anchor)
    assert source.count("  - id: diantao-one-click\n") == 1
    assert source.count("  - id: diantao-one-click-tasks\n") == 1
    assert 'description: "连通性 → 下滑"' in source
    assert 'description: "主播 → 签到 → 睡觉 → 钻石 → 摇一摇 → 购物 → 打工"' in source
    assert "一键任务执行.py" in source
    assert "全部九项任务" not in source

    register(tmp_path)
    assert registry.read_text(encoding="utf-8") == source


def test_register_adds_both_entries_to_fresh_registry(tmp_path):
    registry = tmp_path / "tools" / "managed_process" / "registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("targets:\n  - id: diantao-anchor\n", encoding="utf-8")
    register(tmp_path)
    source = registry.read_text(encoding="utf-8")
    assert source.index("id: diantao-one-click\n") < source.index("id: diantao-one-click-tasks\n")
    assert source.index("id: diantao-one-click-tasks\n") < source.index("id: diantao-anchor\n")
