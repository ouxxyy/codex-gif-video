# Codex GIF Video · 无声 GIF / 视频素材 Skill

把一段动作描述、分镜或口播文字，做成方便放进剪辑软件的动态素材。你可以保留每个镜头的原始 GIF，也可以选择保存成**一个长 GIF**或**静音 MP4**。全程不加字幕、配乐、配音或音效。

我做这个 Skill，是想把人物、画风和动作先做稳，再把干净的素材交给后续剪辑。它内置 **66 种 Lemo 风格资料与 3 种基础预设**，支持按内容推荐风格、复用同一人物主参考。

> [!TIP]
> 🎁 扫码关注公众号「欧八同学」，免费领取 AI 案例与 Skill《大厂产品AI经验编程 200 套》→ [去扫码](#author)

[9 种动图示例](#demo) · [安装与使用](#install) · [选择格式](#formats) · [风格与致谢](#credits)

<a id="demo"></a>

## 先看 9 种风格

从 69 种风格中选了 9 种，先看画面、材质和动作差别。下方都是这个 Skill 通过官方 API 生成的虚构小样，图内不加字幕或水印；点动图可查看原始 GIF。

<table>
<tr>
<td align="center" width="33%"><strong>纸片立体书</strong><br><a href="codex-gif-video/assets/samples/paper-wave.gif"><img src="assets/style-gallery/paper-popup.gif" alt="纸片立体书：角色抬手招呼，无字幕 GIF 动作小样" width="256"></a><br><sub>人物讲解 · 童话场景</sub></td>
<td align="center" width="33%"><strong>水彩笔刷</strong><br><a href="assets/style-gallery/originals/watercolor.gif"><img src="assets/style-gallery/watercolor.gif" alt="水彩笔刷：银杏叶由浅到深绘出，无字幕 GIF 动作小样" width="256"></a><br><sub>自然科普 · 观察笔记</sub></td>
<td align="center" width="33%"><strong>中国水墨</strong><br><a href="assets/style-gallery/originals/ink-wash.gif"><img src="assets/style-gallery/ink-wash.gif" alt="中国水墨：小鱼游过荷叶下方，无字幕 GIF 动作小样" width="256"></a><br><sub>东方意境 · 情绪表达</sub></td>
</tr>
<tr>
<td align="center" width="33%"><strong>厚涂油画</strong><br><a href="assets/style-gallery/originals/impasto.gif"><img src="assets/style-gallery/impasto.gif" alt="厚涂油画：厚油彩中的帆船轻摆，无字幕 GIF 动作小样" width="256"></a><br><sub>情绪短片 · 生活场景</sub></td>
<td align="center" width="33%"><strong>黏土微缩</strong><br><a href="assets/style-gallery/originals/clay.gif"><img src="assets/style-gallery/clay.gif" alt="黏土微缩：黏土小鸟展开双翼，无字幕 GIF 动作小样" width="256"></a><br><sub>角色表演 · 轻松内容</sub></td>
<td align="center" width="33%"><strong>16-bit 像素 RPG</strong><br><a href="assets/style-gallery/originals/pixel-rpg.gif"><img src="assets/style-gallery/pixel-rpg.gif" alt="16-bit 像素 RPG：冒险者打开水晶宝箱，无字幕 GIF 动作小样" width="256"></a><br><sub>游戏感表达 · 冒险叙事</sub></td>
</tr>
<tr>
<td align="center" width="33%"><strong>低多边形等距</strong><br><a href="assets/style-gallery/originals/lowpoly-island.gif"><img src="assets/style-gallery/lowpoly-island.gif" alt="低多边形等距：小岛上的风车转动，无字幕 GIF 动作小样" width="256"></a><br><sub>产品概念 · 小世界展示</sub></td>
<td align="center" width="33%"><strong>蓝图 / 工程制图</strong><br><a href="assets/style-gallery/originals/blueprint.gif"><img src="assets/style-gallery/blueprint.gif" alt="蓝图 / 工程制图：钢笔沿装配轴拆开再合拢，无字幕 GIF 动作小样" width="256"></a><br><sub>结构拆解 · 原理示意</sub></td>
<td align="center" width="33%"><strong>50s 复古卡通</strong><br><a href="assets/style-gallery/originals/midcentury-toon.gif"><img src="assets/style-gallery/midcentury-toon.gif" alt="50s 复古卡通：讲解员打开台灯，无字幕 GIF 动作小样" width="256"></a><br><sub>操作说明 · 轻量讲解</sub></td>
</tr>
</table>

每段 2.4 秒。这里使用 256px 轻量动图预览，点击后查看未经改动的原始 GIF。小样只覆盖选中的 9 种；连续动作、人物一致性仍需按具体任务复核。[查看全部 69 种风格](codex-gif-video/references/style-index.md) · [小样来源与参数](assets/style-gallery/gallery.json)。

<details>
<summary>再看同一人物、同一画风的两个动作</summary>

同一位虚构角色，同一套纸艺风格，两个不同动作。人物由 AI 生成，不是真人照片。

| 招手 | 指向旁边 |
| --- | --- |
| ![同一虚构纸艺角色的招手 GIF 动作素材](codex-gif-video/assets/samples/paper-wave.gif) | ![同一虚构纸艺角色的指向 GIF 动作素材](codex-gif-video/assets/samples/paper-point.gif) |

每段 2.4 秒、12 帧。已有静态全帧身份检查，但正常速度完整播放和响应自报模型仍有未核验项。[查看人物小样检查范围](codex-gif-video/assets/samples/identity-results.json)。

</details>

## 它怎么工作

1. 你给动作描述或口播文字，并指定画幅、时长和输出格式。
2. Agent 拆镜头、选择风格；需要同一人物时，先锁定主参考和服装配色。
3. 调用当前可用的原生 GIF 入口，保存原文件、请求记录与质量检查结果。
4. 按你的选择交付短 GIF、串接后的长 GIF，或静音 MP4，同时保留清单和导出回执。

口播只用于理解画面，不会自动变成字幕或配音。技术检查、画面检查和完整播放检查分别记录；未完成的项目不会被写成“通过”。

<a id="install"></a>

## 安装与第一次使用

先把 Skill 放进 Codex 的技能目录：

```bash
git clone https://github.com/ouxxyy/codex-gif-video.git
cd codex-gif-video
mkdir -p ~/.codex/skills
cp -R codex-gif-video ~/.codex/skills/codex-gif-video
```

如果已经安装，更新现有副本即可，不要把同名目录套在旧目录里面。重新打开 Codex 会话后使用 `$codex-gif-video`。其他 Agent 可以复制同一个 Skill 目录，但必须具备可用的生成入口。

本地检查与格式导出需要 Python 3.10+、Pillow；MP4 额外需要 FFmpeg。macOS（含 Apple Silicon）可使用：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
brew install ffmpeg  # 只在需要 MP4 且尚未安装时执行
```

第一次可以直接说：

```text
使用 $codex-gif-video，做一段“人物把越来越多的书抱在怀里”的动作素材。
用纸艺风格，16:9，2.4 秒，保存成 GIF，不加字幕和声音。
```

**生成入口有前提**：Codex 当前工具必须真实提供 GIF 能力；只有文字提示、没有 `gif` 参数时不能生成原生动画。也可由使用者明确选择官方 OpenAI API，准备自己的密钥和可用模型权限，费用由服务商收取。[入口检查](codex-gif-video/references/native-entry.md) · [API 配置](codex-gif-video/references/official-api.md)。本仓库不附带密钥，也不保证每个账户已经开放 GIF。

<a id="formats"></a>

## 自己选：长 GIF 或视频

| 你要什么 | 怎么说 | 得到什么 |
| --- | --- | --- |
| 一组短动作素材 | “每个镜头分别保存 GIF” | 原始短 GIF 与清单 |
| 一个长 GIF 文件 | “把这几个镜头按顺序保存成一个 15 秒长 GIF” | 单个 `.gif`，按原速串接 |
| 视频格式 | “保存成 15 秒 MP4 视频素材” | 单个静音 `.mp4`，无字幕、无音轨 |
| 两种都保留 | “长 GIF 和 MP4 都要” | 同一组镜头分别导出，不重复生成 |

例如：

```text
使用 $codex-gif-video，把“拿起书—走到窗边—放下书”拆成三个镜头。
沿用同一人物和纸艺风格，9:16，总长 9 秒，最后保存成一个长 GIF。
```

长文件来自多个短镜头串接，不代表模型一次生成了长动画。导出保留原速和真实时长，不靠循环、慢放、停帧或插帧凑长度。GIF 体积可能较大，重新编码也可能改变调色板；长内容或剪辑素材通常更适合 MP4。[导出命令与限制](codex-gif-video/references/movie.md)。

## 风格、人物与已知限制

- [69 种风格目录](codex-gif-video/references/style-index.md)：66 种上游资料加 3 种基础预设；目录覆盖不等于逐一完成生成测试。
- [人物一致性流程](codex-gif-video/references/character-testing.md)：固定脸型、服装、配色与参考图；换风格仍可能漂移。现有跨风格小样存在服装保色失败，已保留记录。
- 单镜头规划为 2–16 帧，适合短而清楚的动作；默认尺寸为 16:9 的 512×288、9:16 的 288×512、方形 512×512。放大导出不会增加原生细节或运动帧。
- 生成需要联网；口播、提示词和所选参考图会发送给你选择的生成服务。本地规划、检查和导出可以离线运行。
- 代码路径和导出在 macOS Apple Silicon 上验证；Python 使用 `fcntl`，不直接支持原生 Windows。其他 Agent 的完整交互未逐一验证。
- 缺完整播放或视觉检查时，只能明确交付待审文件。文件能解码不代表动作自然、人物完全稳定或没有画面文字。

## 开发与本地验证

以下命令在仓库根目录、已安装 Python 依赖的环境中运行，不触发生成或计费：

```bash
python3 -m unittest discover -s tests -v
python3 codex-gif-video/scripts/native_gif.py prepare \
  --request examples/shot.json --out runs/example-plan
python3 codex-gif-video/scripts/package_skill.py --out dist/codex-gif-video.skill
```

测试使用明确标注的合成夹具验证来源检查、时长、长 GIF 串接、静音 MP4 和格式拒绝规则；合成夹具不作为 AI 生成效果展示。内部脚本名 `native_gif.py` 和时间线标识保留兼容；仓库名、安装目录、Skill 标识及调用名称均为 `codex-gif-video`。

## English

**Codex GIF Video** is an Agent Skill for creating silent animated GIF and MP4 assets from action briefs or narration text. It plans short native GIF shots, keeps character/style references, and exports individual GIFs, one concatenated long GIF, or a silent MP4. No subtitles, music, voiceover, or sound effects are added. Install the `codex-gif-video/` directory and invoke `$codex-gif-video`; native GIF generation requires an enabled Codex tool or a separately authorized official API. Style coverage is not a quality guarantee.

<a id="credits"></a>

## 致谢与来源

**特别感谢 [Lemomo（@lemomo-ai）](https://github.com/lemomo-ai) 创作并开源 [Lemo-Opuscar](https://github.com/lemomo-ai/lemo-opuscar)。我大量参考了这个仓库的风格资料，尤其是材质、配色、人物表现、动作和镜头语言；这部分积累是本项目的重要基础。**

这里固定引用上游提交 `9eb7739a0fca4c6990fe966cb8b87b1930f7193a` 的 66 份风格指南与对应元数据，再适配为原生 GIF 生成约束。上游原作使用代码制作影片，本项目使用模型生成短 GIF；生成方式与质量边界不同。没有打包上游演示影片、音乐、字体或角色资产。

原始资料及 LemoLab 版权声明随包保留，见 [来源说明](codex-gif-video/CREDITS.md)、[上游 MIT 许可证](codex-gif-video/references/lemo-source/LICENSE) 和 [固定版本记录](codex-gif-video/references/lemo-source/provenance.json)。也欢迎直接去原仓库看完整作品并支持作者。

## 相关项目

- [欧八同学项目合集](https://github.com/ouxxyy/ouba-classmate)：按用途寻找 AI Skills 与工具。
- 全部项目与作者主页：[github.com/ouxxyy](https://github.com/ouxxyy)

<a id="author"></a>

## 作者

作者全平台同名：**欧八同学**。9 年网易、搜狐大厂产品，跳槽换行 7 次，涨薪 10 倍。

[联系我](https://albertou.redboook.cn/)

- 微信公众号：扫码关注，免费领取 AI 案例与 Skill《大厂产品AI经验编程 200 套》
- 抖音：[搜索“欧八同学”](https://www.douyin.com/search/%E6%AC%A7%E5%85%AB%E5%90%8C%E5%AD%A6)
- 小红书：[搜索“欧八同学”](https://www.xiaohongshu.com/search_result?keyword=%E6%AC%A7%E5%85%AB%E5%90%8C%E5%AD%A6)
- X：[搜索“欧八同学”](https://x.com/search?q=%E6%AC%A7%E5%85%AB%E5%90%8C%E5%AD%A6&src=typed_query)

<p align="center"><img src="assets/wechat-qr.jpg" alt="欧八同学微信公众号二维码" width="260"></p>
<p align="center"><sub>扫码关注「欧八同学」，免费领取《大厂产品AI经验编程 200 套》</sub></p>

如果它帮你省下了整理素材的时间，欢迎点个 Star。遇到问题可提交 [Issue](https://github.com/ouxxyy/codex-gif-video/issues)，附上脱敏命令、报错与最小复现；不要上传密钥或私人参考照片。

## 许可证

项目代码与原创文档使用 [MIT](LICENSE)。上游风格文档保留各自的 MIT 声明；README 的虚构人物 GIF 是 AI 生成示例，不代表上游作者的作品。二维码仅用于作者标识与关注入口。
