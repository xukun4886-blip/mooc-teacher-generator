# M2 实施与验证证据 · 2026-10-02

2026-10-09 用户授权讲稿可靠性架构改造：见[实现与验证](draft-reliability-implementation.md)、[三课件两轮真实请求](draft-reliability-real.json)、[有限局部恢复](draft-reliability-recovery.json)、[原任务保留与真实语音字幕](draft-reliability-activation.json)、[专项测试](draft-reliability-tests.xml)、[全量回归](draft-reliability-regression.xml)。正文不再消费模型JSON；独立核查仍严格校验且可待完成，不能把免费服务限流或教学待审写成成功率通过。

Lecture 9最终收尾见[完整报告](../M3/lecture9-finish.md)、[末页第一次失败](lecture9-short-reading-first.json)、[第二次失败](lecture9-short-reading-real.json)、[原响应严格重验证](lecture9-saved-response-revalidation.json)、[33项空白对应专项](lecture9-identity-tests-final.xml)。历史失败未改写，完整正文未补造，原10页版本前缀仍保留。

2026-10-09第11页继续修复：[原响应与输出契约](lecture9-contract-v3.md)、[实时24页状态](lecture9-contract-v3-latest.json)、[短页读法补验](lecture9-short-reading-real.json)、[108项工程回归](lecture9-contract-v4-regression.xml)。保留最初10页版本及全部失败，最新媒体另见[M3](../M3/lecture9-real.md)。历史8/24与100项检查不表示当前整课已通过。

2026-10-09用户新24页课件第3页AI失败：见[原因、修复与真实有限复验](lecture9-format-repair.md)、[首次失败](lecture9-format-first.json)、[实际制作状态](lecture9-format-latest.json)。100项回归通过，前2页稿/旧3代失败保留，真实第3页完整讲稿已保存，整课仍制作；不计正式评分或媒体成功。

2026-10-02 本轮：复用真实授权 Lecture 2.pptx（63 页），接入真实智谱 GLM-4.6V-Flash，批量任务/失败重试与教师审核表单已实施。用户指定原页 5–14 为正式验证课时；AI 草稿、问题、读法及试听仍待教师判断，M1/M2 未通过。

- [真实 AI 批量任务](course-ai-real.json)：实际请求、逐页版本/来源与最终最新状态；不能把排队/失败页当成功。
- [本轮行为测试](tests-round2.xml)：批量入队/上下文、重复阻断、排队后编辑冲突、失败页重试、人工稿候选与审核失效、启动票据、教学表单保存和草稿试听隔离。服务替身测试只证明编排；真实 AI 证据另列。
- 最终真实 AI：63/63 页草稿完成，最新失败页 0；旧失败/重试历史保留。服务原生 JSON 模式实际调用成功并用于最后 3 页，未用模拟结果补足。
- [正式课时审核准备](formal-lesson-review.json)：原页 5–14，10 个不重复的理解问题及稳定原页来源，10 份真实 GPT-SoVITS 草稿试听均已重新完整解码/摘要检查。教师确认 0 页、正式快照 0 份；未确认冻结返回 422。审核包及原始响应/媒体仍在受控存储，仅位置和摘要进入证据。
- [本轮文档检查](document-round2-check.json)：稳定编号、M1/M2 未通过状态及本地链接一致性检查。
- [最终一致性检查](final-round2-check.json)：54 项测试报告、构建文件摘要、公开代码/证据中的密钥值检查，以及隔离工程读法版本从数据库重开的验证。
- [桌面审核表单](browser-review-form.png)、[窄屏审核表单](browser-review-narrow.png)、[未审核预检阻断](browser-preflight-blocked.png)、[正式课时工作台](browser-formal-lesson.png)：真实浏览器操作。54 项测试与 Vue 构建通过；浏览器保存/重开保留版本，教师确认及冻结没有被自动执行。
- [本轮浏览器检查](browser-round2-check.json)、[读法应用](browser-reading-applied.png)、[具体审核清单](browser-review-reference.png)：实际表单操作追加版本并保留原显示稿，旧试听失效；正式课时仍 0 确认。一次启动票据已消费后重放为 401，临时窄屏设置已恢复。

以下为 2026-10-01 上轮原始证据说明，保留其当时的限制与结果。本轮状态以以上增量及新证据为准。

上轮 M2 进行中：M2-F01–M2-F06 的前后端内容链路已实现；当时 M1 人工评审未通过，M2 正式教学审核、人工试听与真实 AI 服务验证未通过。没有提交、推送、部署、付费调用或训练。

| 工作项 | 实现与验证 | 剩余验证 |
| --- | --- | --- |
| M2-F01 | 项目 CRUD/复制、受限文件访问、Windows ACL、素材上传、真实格式/容量/解码、照片裁剪与视频/语音选取；SQLite 保存重开 | 授权范围与真实教师材料继续由使用者核查 |
| M2-F02 | M1 原页处理复用，十页真实重新渲染；稳定映射的跳过/重排/相邻合并/拆分/播放原页/用途规划 | 正式课时原页保真与教学安排人工评审 |
| M2-F03 | 原备注/外部稿字面保留，错位原子阻断；AI 真实多模态兼容接口及服务失败阻断，测试替身验证上下页/页图输入 | AI 实际服务未配置，测试替身不能算真实 AI 验证 |
| M2-F04 | 追加版本、回退、教师核查锁定、修改撤销确认、教学问题来源、不可变快照隔离与提交阻断 | 正式十页教学审核/至少 5 问及最终快照退出未通过 |
| M2-F05 | 三页不同配置及继承/恢复/批量行为；控制语法/术语/符号保留；原生 TTS 短页与实际采样停顿 | 人工音色、术语、漏句/重复核查未填写 |
| M2-F06 | 课程列表、素材页、三栏编辑工作台、预检定位、实际异步任务状态与配置错误 | 完整退出仍阻断；M3/M4 正式验收未执行 |

- [最终测试报告](tests.xml)：43 项通过（M1 21 项、M2 22 项），包含真实子进程异常退出与单进程锁验证；模拟 AI 只验证编排与输入，不证明模型真实生成质量。tests-initial.xml / tests-content.xml 保留为开发中历史记录，其中问题均已修复，以最终报告为准。
- [真实内容链路](real-content-chain.json)：实际 HTTP 素材上传、PowerPoint 十页重新渲染、保存重开、原文与外部稿及逐页 GPT-SoVITS 试听。媒体位置和 SHA-256 关联受控存储，没有把原件或大型输出放进 Git。
- [浏览器检查](browser-check.json)：本机真实工作台页面、编辑/重开和控制状态；截图见对应记录。
- [补充控制验证](control-validation.json)：显式视频选取、真实语音前后/内部停顿的采样级验证，结果按实测填写。
- [环境与检查](environment-check.json)：锁定运行版本、构建、文档与依赖检查，既有继承环境问题如实记录。
- [文档一致性](document-check.json)：本地链接、24 项稳定工作项及 M1/M2 未通过状态检查；不替代阶段验收。

工程样例用此前用户确认的 M1 中文稿连续片段验证十页 TTS。其任意页映射不代表真实课时讲稿获审核；证据保留 engineering_only 与 pending 状态，预检应阻断正式内容交接。AI 服务问题已请求必要配置，其余工作已独立完成。

重现与操作见 [M2 指南](../../M2_RUNBOOK.md)，接口见 [M2 契约](../../../specs/M2-content-contract.md)，执行工具见 [真实证据脚本](../../../tools/m2_real_evidence.py)。
