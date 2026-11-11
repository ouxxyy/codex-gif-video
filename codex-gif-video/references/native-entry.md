# 原生入口：版本、开关、参数、服务端

以 2026-11-10 的官方源码及本机实测为依据，不把实现存在等同于账户可用。

## 四层检查

1. **实际客户端**：shell 中的 codex 可能不是桌面内置版本。`doctor` 分别检查 shell 和 `/Applications/ChatGPT.app` 内置 CLI；`doctor --binary /path/to/codex` 可额外检查指定官方客户端。只读，不修改配置。
2. **客户端功能**：官方 PR #59073 新增 `image_generation_animation`，默认关闭。旧版报 Unknown feature flag，说明代码不存在，仅写配置不能补上。支持版本可在单次运行用 `--enable image_generation_animation`；不要把未知开关写进仍在使用旧客户端的全局配置。
3. **工具调用**：当前会话实际 schema 必须有 `gif`。`gif: {}` 请求默认值，或用 `gif: {"frame_count":9,"frame_duration_ms":200}`。仅 prompt 中出现 GIF 不会设置这个字段。原生工具不接受 API 的 output_format/model 参数。
4. **服务端能力**：能显示 gif 字段不等于服务端允许。若原生工具返回 `GIF output is not enabled for this request.`，记录原始错误后停止；客户端无法凭开关授予服务端权限。具体是账户开放、路由还是配置缺陷需要服务方确认，不擅自归因于订阅等级。

## 能力限制

本地历史测试出现过客户端缺开关、以及服务端拒绝 GIF 的情况；不能据此判断其他账户。入口检查失败时保存真实错误，不重复静态探针，不改全局配置。只有本次用户授权了可用的官方 API 才切换入口；该入口另行计费。

## 来源

- [官方原生 GIF 实现 PR](https://github.com/openai/codex/pull/59073)：开关、gif 参数、保留 GIF 原字节。
- [0.169.0-alpha.7 原生工具源码](https://github.com/openai/codex/blob/rust-v0.169.0-alpha.7/codex-rs/ext/image-generation/src/tool.rs)：当前工具参数及固定请求模型标识。该标识不能证明服务端实际权重；对话模型选择也不是图像模型选择。
- [公开同类问题及用户复现](https://github.com/openai/codex/issues/59890)：部分更新客户端启用开关后仍被服务端拒绝，不能据此推断全账户不可用。
