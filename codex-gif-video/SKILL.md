---
name: codex-gif-video
description: 通过 OpenAI GPT API 调用 GPT Image 2.6 原生 GIF 能力（或 Codex 原生 GIF），把动作描述、分镜或口播文字做成无字幕、无配乐的短 GIF、拼接长 GIF 或静音 MP4（GIF 视频）。内置 69 种视觉风格（66 种 Lemo 风格指南 + 3 种基础预设）并支持跨镜头人物一致性，适合制作 X（Twitter）短视频动图、口播动画素材（B-roll）、儿童绘本读物与科普拆解动图。
---

# Codex GIF Video

## 用途与输出选择

本 Skill 专门制作可供后续剪辑使用的视觉素材，不添加字幕、标题、文字标签、水印、配乐、配音或音效。口播文字只用于理解动作与拆镜，不转成字幕或声音。上游风格资料中的声音、字幕和长片制作要求不是本 Skill 的执行指令。

用户可以选择：
- **原始短 GIF**：每个镜头保留服务返回的原始字节及清单。
- **一个长 GIF**：把多个合格镜头按顺序拼成单个 `.gif` 文件；不填充循环，完整播放一次。
- **视频格式**：保存为 `.mp4`（H.264/yuv420p），仅含视频流，静音、无字幕。
- **两种都要**：复用相同镜头分别导出长 GIF 与 MP4，不重复生成镜头。

沿用用户明确选择；只说“做 GIF”就交 GIF，说“视频格式”就交 MP4。未指定时默认 GIF 素材并说明可选 MP4。目标时长超过单镜头能力时，先拆成多个镜头，再导出一个长文件，不能只交零散片段。调用见 [导出工作流](references/movie.md)。

## 生成边界与入口

动态图像源只接受允许模型原生返回的 GIF。使用 Codex 当前会话原生工具，或用户已选定的官方 OpenAI Image API；不使用第三方代理、其他图像/视频模型、静态拼帧、代码动画、I2V 或补帧冒充原生动画。保留原始 GIF 和每次请求证据，不变速、重复循环或停帧凑时长。

长 GIF 的串接、MP4 编码及等比缩放是**衍生导出**，不能称作模型一次原生生成，也不增加真实运动帧。GIF 重编码可能发生调色板变化，优先沿用源尺寸；长内容可选 MP4 以减小体积。

入口优先级：本轮明确指令 → 项目私有 `codex-gif-video.config.json` 的 `preferred_entry` → Codex 会话。沿用已保存的选择；原生入口失败不自动切换计费 API。`credential_file` 和 `budget_file` 相对项目根目录，密钥不进入 Skill、提示词或日志。

官方 API 先读 [official-api.md](references/official-api.md)，用 `official_api.py`；跳过 Codex gif 开关检查。Codex 模式先运行 `native_gif.py doctor` 并检查本会话真实工具 schema：必须有 `gif` 字段，不发 prompt-only 静态探针，不臆造参数。诊断见 [native-entry.md](references/native-entry.md)。模型和 GIF 能力受账户及服务端开放范围限制。

同一授权批次共用预算，默认最多 8 次 GIF、3 次参考请求，失败与超时也计入。新任务或明确重制可建立独立账本，记录计划数量并保留旧账本。不得清空额度绕过失败；新尝试须显式重试，提示、参数、参考变化须新建 bundle。

## 从需求到镜头

1. 读 [调用协议](references/protocol.md)，把目标拆为 `shots`，每镜头明确“初始状态 → 动作 → 完成状态”。口播保留原文，不编造音频时间戳；重复片段提供字符位置。
2. 确定输出格式、画幅和总时长。`prepare` 把比例落实为像素：默认 9:16→288×512、16:9→512×288、1:1→512×512；这是本地保守默认，不是服务上限。可显式指定符合 16 倍数及服务像素限制的尺寸。
3. 默认精确时长。省略 `frame_count` 时自动选 2–16 帧内可整除目标时长的方案；显式帧数不兼容则在生成前报错。只有明确接受近似才设 `duration_policy:quantize` 并披露误差。15 秒可规划 5 段×3 秒×15 帧，每帧 200ms；不能把 16 帧×310ms 说成 5 秒。低帧率适合简单动作，不保证电影级流畅。
4. 推荐风格后比较候选，并运行 `style_router.py guide --style ID` 读取选中风格的完整原文。核对材质、人物、配色、动作、镜头和视觉禁忌；忽略上游字幕、声音、代码引擎要求。见 [styles.md](references/styles.md)。
5. 需要跨镜头人物一致性、但无用户主参考时，用 `style_router.py reference-prompt --style ID --subject-file FILE` 生成主参考提示计划，再调用允许模型。先查看实际主参考，随后每镜头复用并锁定人物特征及 `style_lock`；不把漂移结果换成主参考。
6. 编写请求 JSON，`prepare` 冻结提示、尺寸、时间计划、风格原文哈希和参考。生成前核对参数及总时长。请求变更用新目录，不覆盖旧结果。

## 生成与来源证据

官方模式：`prepare` → `official_api.py generate`，不调用 `native-request` 重复预留。首个镜头收到真实多帧 GIF、技术参数符合、来源证据充分后再继续；尺寸、帧数或格式错误先定位，不盲目重试整组。

Codex 模式：`prepare` → `native-request` → 按真实 schema 调用原生工具（保留 `gif`）→ `import-native`。无文件用 `finish-attempt` 记失败或未知。不能把未暴露的 `model/size/output_format` 当作工具字段。

- `model_evidence.reported_model` 只记录服务真实回传，缺失保持 null，不猜模型。
- 官方请求可用固定官方 HTTPS 端点、显式允许模型、无重定向、200 响应、request ID 与请求哈希组成 `official_request_evidence`。这证明官方请求来源，不等于服务自报执行模型。
- Codex 来源未知、官方回执不全、模型报告冲突仍不能通过。历史 unknown/unverified 不自动改写。

## 检查与交付

读 [quality.md](references/quality.md)。技术检查只证明格式、尺寸、帧数、延时、解码与像素变化；不能证明动作自然。实际检查全帧及正常速度完整播放，分别记录身份、风格、结构、运动、语义、循环、`clean_visual`（无字幕与文字叠加层）。Jev 若可用，使用真实抽帧与主参考；静态抽帧和完整播放范围分开记录。

`review` 绑定原文件哈希；所有质量要求通过后才 `export` 为 `ready_gif_assets`。衍生导出默认只消费 ready 包。若技术和来源合格但缺完整播放检查，可显式 `--review-copy` 制作待审文件，保留 `rendered_pending_review` 和缺项；明确视觉失败不能借待审模式放行。

按用户选择调用 `compose_movie.py --out assets.gif` 或 `--out assets.mp4`，支持单 bundle 或多 bundle 镜头清单。只使用每镜头一个周期，保持原速；不加字幕和声音。MP4 导出强制只含一个视频流；长 GIF 核对真实总延时、尺寸、顺序与单次播放。两者都需检查实际画面，流检查不能发现烧进画面的文字。

交付所选文件、原 GIF、清单、渲染回执与剩余核验范围。保持历史结果和修正版可追溯。安装路径为符号链接时更新源目录；打包排除密钥和运行产物。
