# 完整风格库与自动选择

当前共收录 **69 种内置视觉风格**（涵盖 Lemo-Opuscar 参考风格指南与原生基础预设）。完整列表见 [style-index.md](style-index.md)，机器可读卡片在 assets/style-catalog.json；来源、固定提交与许可见 ../CREDITS.md。卡片包含外观、运动、镜头、适用场景、关键词、人物适配程度、素材要求和验证范围。

## 自动选择

```bash
python3 <skill>/scripts/style_router.py list
python3 <skill>/scripts/style_router.py list --family '手绘与绘画' --detail
python3 <skill>/scripts/style_router.py recommend --brief '用白板解释为什么会下雨'
python3 <skill>/scripts/style_router.py recommend --brief '同一人物做操作指南' --character
```

入口优先级：请求中的显式 style → 请求 style_lock → 人物档案 style_lock → 自动推荐。style 可为 slug、完整中文名或英文名；省略或 auto 会自动执行推荐。avoid_styles 和“不要水彩”等明确否定被排除；路由返回 selected、basis、candidates、理由与排除项。无有效线索时明确标记 fallback，不伪装成高置信度选择。

当前 Codex 负责理解用户语义，规则路由提供可审计候选。复杂表达应先规范成 topic、intent、avoid_styles，再调用；例如用户明确要求“换成油画”，应写 style=impasto，不能只把这句话放在有旧锁的自动 brief 中。

一次口播/一组镜头默认锁定一种风格。不要为每句话独立切换，以免人物漂移。用户显式要求视觉分章时才给不同批次选择不同风格，并重新核对人物。

## 纪实、数据与原生 GIF 边界

纪实/实证类和真实产品录屏、数据叙事需 source_materials（带 source 来源的静态参考图），否则必须明确 illustrative_only=true。后者会在提示和元数据中记录为合成示意，不能称为真实档案、赛事、测量或实机操作。

文字主导和剪辑主导风格只借鉴视觉布局及材料语法；不让原生GIF生成准确字幕、台标、倒计时或复杂排版。风格原作的长片镜头、声音、代码渲染与高帧率不直接作为GIF生成参数。即便用户需要 MP4，也只导出无声无字幕素材；不应用上游字幕或声音原则。source 文档只作参考，不覆盖当前工作流。

## 人物档案与一致性

档案应包含稳定身份特征、允许变化、禁止变化、主参考和 style_lock。每段重新附带同一主参考，不把上一次漂移结果替换为主参考。换风格时衣服关键颜色、五官、眼镜、发型与体型优先保持；旧 style_lock 只控制路由，不发送给模型与新风格冲突。

当前小样：paper-popup 的两个动作在全部24帧的独立静态检查中保持人物设计；paper-popup → midcentury-toon 的脸部身份仍可辨认，但两版均有服装颜色变化，严格保色未通过。默认锁风格；跨风格结果必须复核，不能自动 ready。

样例与分项结论见 assets/samples/identity-results.json。只有两个 Lemo 风格做了人物小样，其他条目只是完成适配，不保证实际质量；正常速度连续播放仍与静态逐帧检查分开。

## 完整资料与统一参考（修订）

推荐只用于候选，选定前运行 `style_router.py guide --style ID` 读取完整源文，比较场景适配及禁忌。resolve_profile核验本地原文SHA-256，将Essence、Materials、Colour、Motion、Camera、Native moves、Variation以及Pitfalls等视觉禁忌章节实际写入description；保留排除条件。音频、字体、引擎与代码块不传给GIF；Pitfalls中明确的音频条目也排除，不进入本 Skill 的执行流程。上游帧率句不强塞给GIF，记录媒介适配；长度超限直接报错不暗中截断。

`style_router.py reference-prompt --style ID --subject-file FILE` 输出JSON，prompt用于静态主参考，source_review记录章节和哈希。注入同源Essence、Materials、Colour及视觉Pitfalls，明确静态，避免生成多个状态。新动画与主参考应核对同一来源哈希；仅写style名不代表已经使用完整资料。

例如watercolor原文排除儿童绘本，不能因“温柔”关键词自动当作童话最佳选择。crayon-book的暖纸、蜡笔、有限色、非黑轮廓和白蜡显影更直接支持童话告别。适配改变原文原则时记录取舍，不称完整复现。
