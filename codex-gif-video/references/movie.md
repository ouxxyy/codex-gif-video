# 长 GIF 与静音 MP4 导出

同一组原生 GIF 可按用户选择保存成一个长 GIF 或一个 MP4。两种格式都只提供视觉素材，不加字幕、标题、水印、配乐、配音或音效。原始 GIF 不修改；导出文件是重新编码的衍生素材，不是模型一次生成的长动画。

## 时间与尺寸

- 先拆镜头并规划真实总时长，再生成。例如 15 秒可用 5 段×3 秒，每段 15 帧×200ms。
- 每镜头只用一个原始周期，不循环、慢放、停帧或插值凑长度；源时长之和必须等于目标时长。
- 画幅必须与源文件一致，只允许等比缩放。默认源为 288×512 时，输出 1080×1920 是放大，不是原生高清。
- MP4 用 25/50/100fps 编码以精确保留 GIF 帧边界，同一画面按原延时保持；不会新增真实运动。
- 长 GIF 保留原始帧延时，按镜头顺序串接，无额外循环指令。播放器可能自行选择循环方式。GIF 颜色会受调色板限制，连续相同帧可能合并但延时相加。
- 长 GIF 建议沿用源尺寸。解码帧数×输出像素超过 1 亿时会拒绝以控制内存；请降低尺寸或选择 MP4，不缩短实际时长。

## 格式选择

在仓库根目录运行（示例文件必须是已生成且审阅合格的清单）：

```bash
# 一个长 GIF：保留竖版源尺寸
python3 codex-gif-video/scripts/compose_movie.py \
  --manifest runs/ready/manifest.json --out exports/assets.gif \
  --width 288 --height 512 --duration 15

# 静音 MP4：同一组镜头，不需重新生成
python3 codex-gif-video/scripts/compose_movie.py \
  --manifest runs/ready/manifest.json --out exports/assets.mp4 \
  --width 288 --height 512 --duration 15
```

输出扩展名决定格式；只接受 `.gif` 或 `.mp4`。没有 `--audio` 或 `--subtitles` 参数，旧命令传入会直接报错。安装到 Agent 后，将命令前缀换为实际 Skill 目录。

默认要求 ready 及有效审阅记录。技术与来源合格但缺完整播放检查时，显式加 `--review-copy`，状态保留 `rendered_pending_review`。技术、比例、哈希、明确视觉失败或来源不足不能借此放行。输出旁的 `.render.json` 保存源哈希、时间线及实际参数；已存在文件不覆盖。

## 跨批次选择镜头

用 `--timeline timeline.json` 替代 `--manifest`，组合旧 bundle 的合格镜头与新 bundle 的修正版，不改旧记录：

```json
{"kind":"native_gif_movie_timeline","sources":[{"manifest":"bundle/manifest.json","shot_id":"01"},{"manifest":"replacement/manifest.json","shot_id":"02-fixed"}]}
```

路径相对 timeline 文件。`native_gif_movie_timeline` 是为兼容旧文件保留的数据标识，不是 Skill 名称。所选原始文件、时间线和每个源 manifest 均绑定哈希，并在渲染后复核。

## 验收

完整解码输出文件，核对尺寸、比例、总时长和镜头顺序。MP4 必须只含视频流；两种格式逐帧确认没有文字叠加层，再正常速度完整观看。静态接触表不能证明连续动作自然；未完成的检查如实保留。
