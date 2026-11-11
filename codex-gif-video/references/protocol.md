# Codex 会话调用协议 v1

## 职责

Python 3.10+、Pillow 10.4+，兼容 macOS arm64。native_gif.py 是离线协议/检查工具，不读取密钥或 OAuth。本文介绍 Codex 会话流程；用户已授权的可选 API 入口由独立 official_api.py 执行，见 official-api.md。两者共用数据协议。Skill 代理负责自然语言理解、口播拆解和视觉判断；只传口播不提供 shots 会返回 semantic_planning_required_supply_shots。

## 请求

schema_version=1；mode 为 shot 或 narration；shots 为非空数组。model 是目标模型，只允许 gpt-image-2.6-sunburst/flare，默认 sunburst。它不控制宿主路由，不等于实际执行模型。

| 镜头字段 | 规则 |
|---|---|
| id | 唯一英数/横线/下划线，不含目录 |
| intent | 要表达的含义 |
| initial_state / action / end_state | 初始状态、具体动作、完成状态，均必填 |
| source_text | narration 模式必填且来自原文 |
| source_start | 原文片段重复时必填；Python Unicode 字符索引，非 UTF-16 |
| time_range_s | 可空；填写时为调用方提供的 [start,end]，不推测音频时间戳 |
| target_duration_s | 默认 2.4，实际时长以文件为准 |
| frame_count | 2–16；省略时按精确时长选择最大可整除帧数。显式帧数不兼容则拒绝 |
| duration_policy | 默认 exact；quantize 需明确接受近似，并记录 timing_plan 的实际时长与误差 |
| aspect_ratio | 默认 16:9，可选 9:16/1:1 |
| size | auto/省略会按比例解析为明确保守尺寸：9:16→288x512、16:9→512x288、1:1→512x512；显式两边须为16倍数，模型像素限制不伪造 |
| loop | once（默认）或 seamless，动作意图与文件循环字段分开记录 |

比例偏差超过 2%、帧数/延时/指定尺寸与请求不符时不能技术通过；不裁切或重编码原文件掩盖差异。这些规格只有在工具实际暴露相应字段时才作为参数，否则作为输出要求；不能发明 tool 参数。

角色/风格对象包含 id、version、description、invariants、allowed_changes、forbidden_changes、references。style 的 preset 可用目录中的任一风格 ID（含 Lemo 条目、papercut/flat/clay），或 custom。reference 包含相对请求文件的 path、source、可选 role；主参考用 character，风格用 style，衔接末帧用 initial_state。Codex 原生工具只接受最多 5 张静态 PNG/JPEG/WebP。prepare 复制并哈希冻结参考；主参考不随上次动画的漂移更换。

## 会话工作流

```bash
python3 codex-gif-video/scripts/native_gif.py doctor
python3 codex-gif-video/scripts/native_gif.py prepare --request examples/shot.json --out runs/shot-001
python3 codex-gif-video/scripts/native_gif.py native-request --bundle runs/shot-001 --shot burden-up --budget-file evidence/generation-budget.json
```

native-request 返回 reservation、native_tool_arguments、prompt、reference_paths、目标参数、spec_sha256，**没有发起生成**。代理先确认当前原生 schema 有 gif 字段，再使用 native_tool_arguments（prompt、gif、transparent_background 和可选参考路径）。不能把目标参数里的 model/size/output_format 当成当前原生工具字段；它们只有提示与验收意义。缺 gif 字段立即报告入口不可用，不再用 prompt-only 静态调用测试。带功能的 CLI 可以临时启用 --enable image_generation_animation，但不会热更新当前桌面会话。详情见 native-entry.md。

本地参考先按宿主要求查看再传入。首个原生请求收到真实 GIF 且模型证据成立后才能继续批次。PNG/单帧、模型未知、工具失败均停止本轮批次。HTTP 400 “GIF output is not enabled for this request.” 属于服务端拒绝，不以换提示词、改帧数或切对话模型反复重试；不切 API。

保存原生返回文件和原始工具记录，不搜索其他会话附件。evidence.json 格式：

```json
{
  "source_kind": "codex_native_gif",
  "asset_sha256": "原文件实际SHA256",
  "reported_model": null,
  "spec_sha256": "native-request返回的规格哈希",
  "tool_log": "native-tool-log.txt"
}
```

reported_model 仅来自工具/服务真实元数据，缺失保持 null。日志是操作者提供的原始证据，导入器不能加密认证真假，独立审阅须检查日志。PNG 等失败结果也可导入保存，不转换成 GIF。

```bash
python3 codex-gif-video/scripts/native_gif.py import-native --bundle runs/shot-001 --shot burden-up --file original.gif --evidence evidence.json --budget-file evidence/generation-budget.json --reservation-id RESERVATION_ID
```

同一 reservation+文件+日志+规格可幂等重导，写盘中断恢复不新增额度。不能用原 reservation 换结果。没有返回文件时：

```bash
python3 codex-gif-video/scripts/native_gif.py finish-attempt --budget-file evidence/generation-budget.json --reservation-id RESERVATION_ID --status failed --reason "原生工具真实错误"
```

超时不确定是否执行用 outcome_unknown，仍占额度。已尝试资产的新生成需显式 native-request --retry，不覆盖旧记录；入口失败后不能自动重试整批。

参考图也在当前会话生成；之前 reserve --kind reference --label hero-v1；收到后保存原图和工具记录，finish-attempt --status reference_received。只表示收到，不代表视觉通过，也不能换其他模型补参考。

## 检查与输出

工作包含 manifest、参考图、按尝试保存的原文件与 receipt、原生工具日志、审阅记录。状态包括 planned、pending_review、pending_model_evidence、technical_failed、not_ready、ready。

Codex工具未报告模型时仍保持来源未知。官方API的新请求可由 official_request_evidence 通过来源门槛，reported_model 缺失仍为 null；见 official-api.md。历史未知记录不迁移，矛盾模型报告仍拒绝。不得用提示词中的模型名、后缀或像素变化代替来源证据和完整观看。

```bash
python3 codex-gif-video/scripts/native_gif.py inspect ORIGINAL_FILE
python3 codex-gif-video/scripts/native_gif.py review --bundle runs/shot-001 --shot burden-up --in review.json
python3 codex-gif-video/scripts/native_gif.py export --bundle runs/shot-001 --out runs/ready-001
```

review 格式见 quality.md。脚本记录操作者声明，不能认证人的感知。缺正常速度完整播放、全帧检查或任何质量维度非 pass 都不能 ready。准备后的规格与参考冻结；变动要新建 bundle。导出重验文件/参考/证据哈希，并复制原生工具日志。

ready 清单 kind=ready_gif_assets；所有路径相对清单。每项含 path、sha256、intent、source_text、source_span、time_range_s、loop_intent、technical、model_evidence、receipt、review、prompt、parameters。technical 含 width/height/frame_count/frame_durations_ms/duration_s/encoded_loop。下游以实际参数为准，不用目标时长代替实际时长。

encoded_loop=null 为未声明，0 通常表示无限循环；不等同于动作适合循环。一次性动作由下游按一个实际周期使用，原始 GIF 不重编码；选做的长 GIF / MP4 是另存的衍生产物。

stdout 为 JSON；错误 stderr 为 JSON、退出码 2。导入技术失败/模型未知也返回 2 并保留原产物。无 ready 素材时 export 失败。命令退出码 0 不等于整体视觉验收通过。

首次探索跨批次共用预算，8 次 GIF / 3 次参考图，失败/超时也计数。只有调用方授权新预算后才能另建账本，不得清空已有记录绕过上限。

## 风格选择字段

style 可用 preset ID、完整中文名/英文名、auto 或已有自定义档案对象。省略时自动推荐。style_lock（也可保存在 character 对象）用于跨批次保持风格，显式 style 优先。topic 提供风格选择上下文；avoid_styles 为排除 ID/完整名称数组。prepare 将 style_selection 的结果、依据、候选及固定上游提交写入 manifest。

source_materials 为与 references 同格式的静态来源图数组，和角色/风格参考合计最多 5 张。纪实/实证类缺少来源时需明确 illustrative_only=true，否则阻塞；生成示意不能作为真实事件或测量证据。

## 长 GIF / 视频素材请求

按 [movie.md](movie.md) 导出用户选择的长 GIF 或静音 MP4，不添加字幕或声音。原 GIF 保持不变；`--review-copy` 仅供待审导出，不能绕过技术、来源或明确视觉失败门槛。
