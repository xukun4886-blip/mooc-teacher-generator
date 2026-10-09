# M3 实施与证据 · 2026-10-02

Lecture 9最终当前稿收尾见[报告](lecture9-finish.md)，原24页725.60秒完整草稿保留在[补修前任务快照](lecture9-media-before-short-repair.json)。最终当前输入的真实重合成、播放和四类下载以收尾报告及[实时记录](../M2/lecture9-contract-v3-latest.json)为准。

2026-10-09 Lecture 9原24页真实照片路径：[媒体续修报告](lecture9-real.md)、[首代OOM失败](lecture9-media-first-failure.json)、[完整帧CUDA存储探针](lecture9-memory-cuda-probe.json)、[实际单页字幕修复](lecture9-subtitle-size-repair.json)、[实时逐页证据](../M2/lecture9-contract-v3-latest.json)。第3页长音频修复后真实有效，全部24页与最终播放下载仍以实际终态复验为准，不丢弃失败或自动确认质量。

M3-F01–M3-F06 已实施待正式验证；复用 Vue/FastAPI/SQLite、原页和 GPT-SoVITS/SadTalker/MuseTalk。M1 人工评审、M2 教师确认/正式快照仍待完成，M3 退出不勾选。

2026-10-08 主流程改造增量：见 [一键制作验证报告](one-click-validation.md)、[真实记录](one-click-real.json)、[最终一致性与浏览器核查](one-click-final-check.json)、[75 项全套检查](one-click-final-tests.xml)、[最终一键专项检查](one-click-coordinator-final.xml)。两套已有讲稿两页 1080p 草稿真实完成并播放下载；新上传自动 AI 全链路受服务 HTTP429，明确保持待完整验证。首页三项输入，高级功能折叠，成片后教师主动确认，不代填或标正式通过。此前记录全部保留。

- [真实草稿媒体](real-draft-media.json)：独立原页 5–7 摘句副本，照片/原视频序列各三页 720p 草稿，两个不同当前音频人物页和一个主动隐藏页。真实模型输出、完整解码/音轨/静音/时长检查，明确未审核；不替代十页/约三分钟正式验证。
- [最终工程测试](tests.xml)：正式门槛、幂等、取消晚到结果、有限重试、缓存范围、实际编码/四类导出、真正终止工作进程后的 SQLite 恢复及所属原生子树退出。替身只算编排，真实能力只取上一条记录。
- [最终一致性核查](final-check.json)：70 项测试、两条真实媒体/当前音轨对应、八份实际 HTTP 导出摘要、源课时审核阻断、文档链接与实现摘要。浏览器发现 AAC 拼接的 21 毫秒偏移后，已修正为零起点；[边界回归](tests-timestamp.xml) 验证精确页跳转，旧输出和问题历史保留。
- tests-initial.xml / tests-media.xml 保留开发记录，最终以 tests.xml 为准。
- [正式生成阻断截图](browser-formal-blocked.jpg)：原页 5–14 无正式快照，正式按钮禁用；教师确认保持 0，不代填。
- [浏览器记录](browser-check.json)：原素材及 A/B 加载/播放、独立工程副本待评草稿保存/重开、真实整片/页跳转/导出及窄屏检查。

见 [M3 契约](../../../specs/M3-media-contract.md)、[操作指南](../../M3_RUNBOOK.md)。本轮没有提交、推送、部署、付费调用或 M4 全量验收。长课质量、低清照片及接缝仍须教师评审，短工程片不计阶段通过。

2026-10-09补验：[原新输入AI失败与十页上传](long-course-validation.json)、[十页独立外部稿真实媒体报告](long-course-validation.md)、[新上传AI双路径功能报告](fresh-ai-validation.md)、[Windows进程修复](process-ownership-repair.md)、[M4预验收](../M4/README.md)。免费4.1V两页AI双路径均从三项新上传完成；十页外部稿双路径均163.88秒，不替代正式三分钟或人工质量。完整未审核草稿流程保持，原AI失败保留，阶段退出仍未通过。
