# 官方 API 兼容模式

用户已授权 API 入口时使用。它是可选入口，不覆盖 Codex 会话模式；不能只因凭据存在而推定新任务接受 API 费用。可用项目私有的 `codex-gif-video.config.json` 保存入口、允许模型和凭据文件位置；用户当前指令优先。

## 私有配置

只从指定的 .env.local 或 OPENAI_API_KEY 进程环境读取密钥。指定 --env-file 时以该文件为准；权限须为 0600 或更严格，拒绝符号链接和其他用户可读的文件。不执行 shell 展开。密钥不进入聊天、日志、脚本、请求 JSON、命令参数或素材包。

```bash
python3 <skill>/scripts/official_api.py status --env-file /path/to/project/.env.local
```

status 不联网，只报告配置存在与权限，不能据此声称密钥有效。分发包不带密钥；使用者需指定自己的凭据位置。

## 调用

先按共有协议 prepare；API 模式不调用 native-request，以免重复预留。

```bash
python3 <skill>/scripts/native_gif.py prepare --request request.json --out runs/api-batch
python3 <skill>/scripts/official_api.py generate --bundle runs/api-batch --shot SHOT_ID --budget-file evidence/generation-budget.json --env-file .env.local
```

- 固定 https://api.openai.com/v1，不支持第三方 base URL、重定向或 Codex OAuth。
- 无参考调用 images/generations；有参考调用 images/edits，JSON images/image_url 携带已冻结的静态参考。
- 只允许 gpt-image-2.6-sunburst/flare；显式 output_format=gif、n=1 及帧数/延时/尺寸。共用协议最多 5 张参考。
- 每个命令只生成一个镜头，无隐式重试。缺密钥不计数；发请求前计入共享预算。401/403/限流/不支持均保留错误，不换模型。
- 超时/响应中断归为结果未知；重试可能再次计费，必须显式 --retry。已生成待审、模型证据待核验或 ready 的素材直接复用。
- Key 仅进入发往官方 HTTPS 地址的 Authorization header，不保存 headers；远端错误正文脱敏后仅保留必要字段。

官方 Images 响应结构不承诺顶层 model。缺失时保留 requested_model、request ID 与 reported_model=null，model_evidence仍unverified；新请求另记录 official_request_evidence，验证固定官方端点、无重定向、API key方式、200、request ID及请求哈希，支持通过来源门槛进入pending_review。这不是伪造服务端执行模型。若自报模型冲突、回执不全或来源不明，仍pending_model_evidence。历史记录不自动升级。generate退出码0不代表视觉通过，继续实际检查。

首次探索所有入口共用 GIF 8 次/参考 3 次预算，失败也计数。不得跨入口重置账本绕过上限。

依据：[官方 GIF 指南](https://developers.openai.com/api/docs/guides/image-generation#generate-animated-gif-output)、[生成接口](https://developers.openai.com/api/reference/resources/images/methods/generate)、[编辑接口](https://developers.openai.com/api/reference/resources/images/methods/edit)。

## 人物主参考

新增 reference 命令生成同一允许模型的静态 PNG，并计入 reference 额度：

```bash
python3 <skill>/scripts/official_api.py reference --prompt-file character.txt --out profiles/hero.png --budget-file evidence/generation-budget.json --env-file .env.local
```

此命令不会把静态图拼成动画。图像需实际检查后才能作为主参考，已有文件不覆盖。详细一致性流程见 character-testing.md。

尺寸由prepare从aspect_ratio解析为明确size；size=auto不是比例锁。exact时长计划在生成前完成，超限/API不支持只记录真实错误，不自行换模型。

人物参考同样验证来源：reported_model明确冲突时保留文件但返回reference_model_mismatch；官方回执不全时reference_pending_source_evidence，CLI退出2。null+完整官方请求证据可进入reference_generated_pending_visual_review，不等于静态视觉已通过。
