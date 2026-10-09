# Lecture 9 第11页契约诊断与真实续跑 · 2026-10-09

最终结论见[24页真实媒体收尾](../M3/lecture9-finish.md)：当前完整草稿已完成播放下载复验、111项工程检查通过，保留原失败与原10页历史。下面是契约诊断及分阶段执行快照，教学质量/阶段退出未标通过。

关联 M2-F03/F06、M3-F01–F06、FR05/FR11/FR14/FR18/FR19、NFR01/NFR03/NFR08、AC02/AC08/AC11/AC15/AC16。用户授权继续原课程、不调用付费服务、不代填教师确认；指标未冻结，阶段退出不变。

## 原始失败证据

实时检查：课程 `11604689-6106-451f-b40b-95089e07b5b5`，旧制作 `b37b5c2a-0c8f-48d9-b32e-a06f4b1e7a23` 已失败、generation=3、10/24页有稿、没有媒体成果。旧文档8/24是历史快照。[修复前证据](lecture9-contract-v3-before.json)记录第11页7次请求，完整响应位于项目受控 `ai-responses/`。

最终响应 `2026100911102871ccb2301c9c4b98` 为HTTP200/stop，completion_tokens=2146、prompt_tokens=8007，未触及8000输出上限。顶层仅 `config/kind/pages`，缺少全部七个必需字段：`display_text/reading_text/knowledge_points/questions/terms/pending/extensions`。讲稿及核查内容嵌入 `pages` 内的大纲条目，不是合法顶层讲稿。不能抽取内部条目或补造正文。此前同页完整对象的显示/读法与sentence_pairs内容不一致，严格字幕校验阻断；另有截断输出及HTTP429/1305，均保留。

原纠正请求只追加user“讲稿字段缺失”，没有具体字段名、失败assistant输出或被拒绝映射内容。课件以大段JSON提交，当前页、大纲及完整布局配置重复出现在输入，模型多次回显输入。这里只能确定实际输出和请求缺陷；不能从一次修复证明模型对整课稳定，不能把HTTP200内容错误归因账户余额。

官方[接口契约](https://docs.bigmodel.cn/api-reference/模型-api/对话补全.md)注明response_format仅文本模型支持，thinking配置仅GLM-4.5及以上支持；[当前模型](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.1v-thinking-flash)为免费且内置思考。以前“HTTP200/有效JSON探针”不能证明两参数在该视觉模型生效，json_object也不是完整JSON schema约束。未使用未经支持的json_schema。当前官方文档副本存受控 `storage/m4-review/lecture9-official-completion.txt`。

官方[错误码](https://docs.bigmodel.cn/cn/api/api-code.md)区分HTTP429/1305模型访问量过大、1302账户速率限制、1308/1310使用上限、1113账户欠费。旧响应不是1113；没有证据证明欠费。服务原始错误与HTTP状态须一起判断，1305在HTTP400下另有含义。

## 已实施修复

- `complete-object-v3`保持完整对象、正文、来源、截断及完整字幕对应校验，不取首项、不从嵌套条目抽取答案、不代写正文。
- 用标记明确的课件资料文本替代答案形状JSON，当前页及备注完整保留、保留原页图；整课大纲每页摘要180字、邻页正文保留，不发送无关布局参数。输出要求位于system和资料结束后的明确任务指令。
- 纠正带回实际失败assistant回答（请求上下文最多8000字符，完整响应独立保留）及具体缺失字段名。仍最多2次格式纠正、每页4次HTTP请求、每任务3代；不增加tokens或重试。
- 当前免费视觉模型过滤response_format，GLM-4.1V过滤不支持的thinking控制。请求参数、提示摘要、原始HTTP错误响应和每次真实耗时均持久化；欠费/使用上限立即停止当页重复等待，模型繁忙仍有限等待。
- 首页用尽重试文案说明服务/配置修复后可继续，不把高级编辑变成普通流程必经步骤。

数据库一致性备份在受控 `storage/m4-review/lecture9-before-v3.sqlite3`，旧配置在 `lecture9-config-before-v3.json`。全部仓库文件原为未跟踪工作区，不执行覆盖还原或提交。核验脚本每次检查旧任务、旧10页版本及素材摘要不变；不删除失败或审核历史。

## 真实复验

新有限制作 `84d7c4ab-221a-4fd6-b404-1104713acf5d` 从第11页开始。第11页第一次HTTP200/stop（24.578秒）返回无效JSON，严格拒绝；第二次HTTP200/stop（27.875秒）返回完整对象，完整两稿按明确句界建立对应后保存真实版本。实际版本ID及原响应引用见[实时证据](lecture9-contract-v3-latest.json)，不是人工补稿。后续仅继续缺稿页。

**结构通过不等于教学质量通过**：第11页读法包含“200–2000”读成“二零零至二零零”、“降低”写成“低下”等模型错误；旧第4页数字读法也存在偏差。已保留原始版本、未代填教师审核，完整草稿可继续生成，但AC02/AC03教学准确性不能标通过。保存的旧10页按用户指令保持，不静默润色。

8765原进程4420（10:50启动）在空闲队列上替换为当前代码。原API已返回具体第11页错误；原构建 `index-DaAljF_U.js`在HTTP侧与磁盘一致。重新构建后真实浏览器刷新加载 `index-Mfzcx2aY.js`，课程与实际进度可见。没有用户截图对应浏览器的可访问实例，不能证明其当时缓存或打开地址；本次受控浏览器核查与历史截图需区别。

[最终105项全套回归](lecture9-contract-v3-regression-final.xml)通过（280.70秒），含免费视觉参数过滤及账户/额度错误检查；[14项新增与提供方专项](lecture9-contract-v3-new-checks.xml)、[28项相关回归](lecture9-contract-v3-tests-final.xml)通过，不累加重复用例数量。初次运行测试的旧模拟提供方依赖JSON输入/缺少原始text，失败记录保留（`lecture9-contract-v3-tests.xml`、`lecture9-contract-v3-regression.xml`），已更新替身适配实际请求；不算真实模型证据。Vue构建通过，[411个本地文档链接检查](lecture9-contract-v3-links.json)无缺失。

新任务已在第1代完成全部24页讲稿，其中14页为本次新生成，18次真实HTTP200、请求耗时累计299.972秒，期间格式失败保留。自动创建媒体`89055bfa-566c-4e86-b4e9-969073b1a9ae`，复用GPT-SoVITS/SadTalker及已选照片/参考音色。第1页19.02秒真实音频、19.04秒1080p/25fps页视频均有效，人物audio_sha256匹配该页当前语音；整课仍须等待所有片段、最终导出与浏览器验证。进度及每页实测摘要见[实时证据](lecture9-contract-v3-latest.json)。

[真实浏览器记录](lecture9-contract-v3-browser.json)与[进度截图](lecture9-contract-v3-progress.png)显示24/24讲稿、真实逐层页数；整课未完成时没有播放下载入口。抽取第1页5秒画面到受控`storage/m4-review/lecture9-page1-frame5.png`，原页、新照片人物、未审核水印可见；长句字幕较大且覆盖部分页面，视听质量未通过，不能以媒体文件可解码代替无遮挡/字幕排版评审。

整课语音、照片人物、实测字幕、播放和下载结论以最终实时检查补充。暂不宣布整课成功、人工质量或阶段退出；无提交、推送、对外部署或付费回退。

短结束页原AI版本“gan xie Thank you!”漏过旧长中文阈值，v4把中文读法检查覆盖短页并在来源指令中明确汉字要求。内部指定页任务可使用与整课一致的完整字幕对应及有限格式纠正；旧版本不改、真实AI新版本追加，之后正常一键生成变更输入。[108项全套回归](lecture9-contract-v4-regression.xml)通过（303.30秒），[25项短页及内容检查](lecture9-short-reading-tests.xml)通过，不重复累加；[真实短页记录](lecture9-short-reading-real.json)尚在等待当前不可变媒体空闲，不虚报已发请求。字幕和长页真实补验见[M3报告](../M3/lecture9-real.md)。

进一步防止纯英文结束页绕过普通话要求：AI读法无汉字时严格拒绝，不影响原文/外部稿入口。新增测试首次有遗留断言变量NameError，[首轮33项](lecture9-short-reading-tests-English-first.xml)保留32通过/1测试代码失败；修正后[两项语言边界](lecture9-short-language-boundary.xml)通过。108项全套报告生成于这一额外边界前，不冒称最新109项全套运行，不重复累加数量。
