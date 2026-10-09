# M2 内容接口与版本契约 v1 · 2026-10-02 增量

2026-10-09增量：项目可选`photo_execution`及追加`photo_execution_history`，带revision并拒绝busy修改；服务令牌只取环境变量，外传授权不自动继承到副本/新PPT项目。Web与云端路由见[可选照片工作进程契约](CLOUD_PHOTO_WORKER.md)。旧项目缺该字段继续本机，旧版本/审核/媒体保留。

关联 M2-F01–M2-F06、FR01–FR08/FR12/FR15–FR18/FR20、NFR05–NFR08，以及 AC01–AC03、AC11–AC14、AC18 的前置能力。需求范围与建议指标未更改。正式工作台仅 Vue + FastAPI；元数据采用 SQLite，素材项目独立持有，无共享删除问题。

## 接口

所有 `/api` 路径（登录除外）与文件访问需要 HttpOnly、SameSite=Strict 本地教师会话；来源检查拒绝跨站请求。登录 `POST /api/session` 使用启动器令牌。内容操作需要当前 `revision`，冲突返回 409；一般业务阻断 422，不存在 404。错误返回 `error.code/message/source/remedy`。

| 路径 | 方法与行为 |
| --- | --- |
| `/api/settings` | GET：系统默认、配置容量与 AI 就绪，不暴露密钥 |
| `/api/projects` | GET/POST：列表/创建（name、可选 config） |
| `/api/projects/{pid}` | GET/DELETE：打开/删除独立素材和任务快照；活动任务阻断删除 |
| `/api/projects/{pid}/copy` | POST：物理复制，保存 source_project_id，新建项目和片段 ID |
| `/api/projects/{pid}/assets/{role}` | POST multipart：file、authorization、teacher_id、revision，返回持久化处理任务 |
| `/api/projects/{pid}/assets/{role}/selection` | POST：revision、selection；照片 box 像素坐标，视频/参考音频 start/end 秒，音频另带 transcript |
| `/api/projects/{pid}/commands` | POST：revision、action、data；原子写入整个操作 |
| `/api/projects/{pid}/import-template` | GET：稳定原页映射的 JSON 导入模板 |
| `/api/projects/{pid}/scenes/{sid}/ai` | POST：revision，返回任务；真实配置缺失时明确阻断 |
| `/api/projects/{pid}/scenes/{sid}/audition` | POST：revision，当前确认稿与参考音频快照驱动真实 TTS |
| `/api/projects/{pid}/jobs` | GET：实际 queued/running/completed/failed 与阶段、错误，不虚构进度 |
| `/api/projects/{pid}/files/{relative}` | GET：经验证位于该项目目录的原件、原页或试听文件 |
| `/api/projects/{pid}/preflight` | POST：素材/映射/教学/审核/试听/模型检查，保存当前版本预检，不调用生成 |
| `/api/projects/{pid}/snapshots` | POST：revision，预检就绪后写入独立不可变内容快照 |
| `/api/projects/{pid}/snapshots/{id}` | GET：读取已冻结快照 |

commands 的 action 包括 config、structure、import、script、notes、rollback、review、page_config、listen_review。structure 的 action 包括 reorder、skip、merge、split、plan、play_page。合并只允许连续片段；每个片段保存 source_page_ids 与 play_page_id；拆分归档父片段及原版本。不同操作不能更换永久来源 ID。

新增 `/api/projects/{pid}/ai-batches` POST：`revision`、可选 `scene_ids`（默认所有未跳过片段）、`retry_failed:true`（仅各页最新失败任务）。原子检查 revision、重复活动任务并排队；返回 `batch_id/total/jobs`，每页真实 queued/running/completed/failed。jobs GET 返回完整任务历史，不再截取 30 项。429/503 以 5/15/30 秒有上限等待，阶段 `waiting_ai_rate_limit`；格式、来源错误与网络错误分别报告，失败不算成功。重启中断项明确失败，排队继续，可手工重试。

入队保存当前版本、来源映射/图像摘要、有效配置、整课大纲及前后页上下文。执行后复核输入，排队/生成期间修改讲稿、来源或有效配置会阻断旧输出。AI 使用原页图、正文、备注、整课正文大纲与邻页正文；响应 ID、usage、输入/提示词摘要和原始响应保存在受控存储，密钥仅环境变量。AI 输出字段和答案的当前来源 ID须有效；明显拼音或严重缩短的中文读法稿阻断。内容准确性仍由教师审核。

单来源页的 AI 可显式返回 `source_page_id:"current"`，适配器仅在输入恰有一个来源页时展开为该稳定来源 ID，并记录展开次数；多页或其他无效 ID 均阻断，不按页号猜测。兼容服务字符串内的原始换行，保留原文及原始响应；不补造答案或缺失字段。五问按问题文本去重计数，不能在不同页重复同一问题凑足五问。任务轮询 API 仅返回状态与定位字段，完整上下文快照在受控数据库，不重复传给浏览器。

2026-10-09一键格式契约`complete-object-v2`：只接受完整单个JSON对象，数组不能取首项作为正文，`finish_reason=length`即使JSON可解析也阻断。一键单页最多2次格式纠正，与限流共用最多4次HTTP请求；每次原始输出、结束原因、响应摘要及失败原因持久化。完整当前页讲稿和来源校验通过后才保存版本，格式失败不进入媒体。失败定位、有限制作次数与实际配置修复后新建任务详见[一键流程](ONE_CLICK_FLOW.md)。

2026-10-09续修`complete-object-v3`：严格校验保持；课件请求采用标记明确的资料文本，保留完整当前页/备注/图和邻页，整课每页正文摘要180字，完整输入快照仍持久化。格式纠正带具体缺失字段及被拒绝assistant回答（请求最多8000字符、完整原响应不裁剪），共用原4请求/2纠正上限。官方免费视觉模型不传仅文本支持的response_format，GLM-4.1V不传thinking开关；不假设JSON schema强约束。成功与HTTP错误原文、实际请求参数/提示摘要及真实耗时均存储；HTTP429/1305为模型繁忙、1113为欠费、1308/1310为额度上限，后两类停止当页重复等待。结构校验不是教学语义质量认证，草稿及教师主动确认规则不变。

已有人工、外部、备注、回退稿或确认稿保留为当前稿，AI 新稿追加为 `ai_candidate`；`adopt_ai` command（scene_id/version_id）主动采用并追加版本、撤销当前确认。`checks` command（scene_id/checks）保存未确认教学表单的新版本，不自动审核；人工修改稿保留上一版本教学表。`category` command（course/development）仅分类，不清理项目或证据；列表返回 category/engineering_only。

试听 POST 可带 `draft_preview:true`：未确认稿的真实 TTS 仅存 `preview_audition`，明确未审核、不计入正式试听；正式 audition 仍要求当前确认稿，真人四项核查逐项勾选。未确认或仅草稿试听的项目仍不能冻结快照。草稿预览请求传 `purpose:audition/draft_preview:true/script_confirmed:false`，M1 仅允许 TTS audition 的这个显式预览例外，不放宽人物或正式生成要求。

启动器默认自动打开一次登录地址：`POST /api/session/launch` 使用 120 秒、单次票据交换现有 HttpOnly 会话，跨站/Host 检查保留。已登录的 `POST /api/session/launch-ticket` 可创建重新打开工作台的票据。本机 CLI 从私有文件读取长期令牌，不打印令牌；URL fragment 在前端立即清除。启动器复用已运行服务，源文件更新时重建前端。

## 外部稿与非朗读控制

```json
{
  "schema_version": "m2.scripts.v1",
  "pages": [
    {"source_page_id": "源文件SHA256:slide-原始XML标识", "display_text": "数组 [1,2,3]。", "reading_text": "数组，一二三。{{pause:1.0}}"}
  ]
}
```

须精确覆盖课件所有原页。页码导入不实现，不按位置猜测；合并/拆分后改用片段编辑。稿件原始输入 raw_display/raw_reading、显示正文、处理后的读法正文、非朗读事件独立保存。唯一指令语法为 `{{pause:N}}`，N 为 0–10 秒有限非负数，异常语法阻断；教学括号不删除。术语按最长优先单次替换，重新计算读法事件偏移。

## 审核与配置

2026-10-09 `body-first-v1`：新任务在配置启用时分别固定视觉/文本提供方与请求选项，正文接口仅返回中文文本；本地程序派生读法、控制事件、稳定句子及完整对应，再序列化存储。`draft_runs`保存来源输入/基础版本、视觉/正文/读法/教学核查状态、原响应摘要、逐次错误和有限等待时刻。兼容的视觉资料可复用，显式生成新稿仍追加版本。正文及读法先以`teaching_check_state=pending`版本保存，核查完成追加同正文的新版本；原版本不改写。核查失败只标待完成，不丢正文、不以空核查冒充成功。

`POST /api/projects/{pid}/scenes/{sid}/teaching-check`接收当前revision，仅针对当前pending版本重新排队核查；拒绝忙碌/过期输入。复制、采用或回退的pending版本按其新来源重绑，只补核查，保留原正文/读法。高级界面显示核查状态和错误，支持仅重试核查或教师填写完整表后保存。正式review和预检阻断pending；完整未审核草稿可继续原一键规则，成片保持未审核标识。

每一外部阶段每一任务代最多4次HTTP，格式/内容纠正最多2次，与网络/429/503共用次数。等待含有限退避、抖动及持久next_retry_at，重启等待剩余时间；原响应已保存但未解析时先重验摘要和内容。队列重启恢复新分阶段AI/核查任务，已保存正文/派生结果直接复用。缺正文页之外的页面继续处理，缺页整课不发布成功。旧队列/已有媒体输入继续原契约，不自动重写旧稿、人工稿、审核或成果。

`local-reading-v1`使用配置词典与数字/容量/频率/百分数/范围规则，保留显示原文、替换区间与规则版本；保护数组、引用、科学计数法、型号和未知公式并列待核对。英文缩写的汉字近似读法标为需试听，未知词不猜测。不是语义或视听质量通过声明。字幕仍依据实际生成语音采样时间，不按字数虚拟分配。

2026-10-09 `complete-object-v6`：针对 Lecture 8 第17页出现的重复JSON/解释文字及拼音正文，格式纠正保留原课件图文与具体校验错误，重新构造请求，不再将错误回答作为assistant示例累积；给出汉字数字读法示例并明确只输出一次对象。原响应仍完整存档。JSON后夹带文字/多个答案提供明确诊断，继续阻断而不截取其中一个；中文正文、来源、逐句对应与请求/重试上限保持。实际契约修复沿用有限新任务恢复机制。

2026-10-09 `complete-object-v5`：逐句字段不完整时，只有显示正文与读法正文去除空白后逐字符相同，才允许忽略版面换行，以标点句边界定位两份完整原文的对应区间；不补写正文、不使用拼音逐句字段、不按字符长度分配时间，字幕仍消费真实语音句段采样时间。换行数量相同但位置不同也遵循相同规则。实际内容不同且不能完整逐句对应时继续阻断，所有原始响应和首次失败保留。

2026-10-09 `complete-object-v4`：含中文显示正文的短页也适用中文读法完整性校验，不再只校验超过20个汉字的长页；纯英文来源结束页的AI读法也须包含普通话汉字。封面/结束页不能以拼音代替汉字普通话正文。内部修复指定页AI任务可显式使用`course_draft:true`，执行与一键草稿相同的完整字幕对应及最多两次格式纠正、四次HTTP上限；每次真实响应和旧版本均保留。不是人工补写或自动教师确认。

每次人工编辑、AI 再生成、导入及回退追加唯一版本，旧原文/外部稿/人工稿保留。确认锁定当前版本的知识点、问题答案来源、术语和 pending 清零记录。已锁定审核版本不得原地修改，需新版本。配置来源由系统→项目→片段叠加，保存各层覆盖、版本与有效值；术语改变形成待审新版本，语速/停顿使试听过期，纯布局保留语音并标重合成。片段未覆盖的项目默认更新只影响实际继承项。模式改变保存主动切换记录并重新预检。

试听输入固定审核版本、有效语速/停顿、参考素材选择与摘要。生成期间讲稿/语音配置改变，输出不得成为当前试听。媒体包含真实提供方、原生权重、输入摘要、采样率和时长；工具就绪不自动赋予人工质量通过。至少 5 个理解问题、全部活动片段当前审核和真人试听核查齐备后才允许内容快照。

快照 schema 为 `m2.snapshot.v1`，包含项目/配置版本、完整原页与播放顺序、审核版本、素材和图片摘要、有效配置、当前试听、模型健康及能力。新增编辑只改变实时项目，不能改写历史快照。内容就绪不代表 M1 人工视听评审通过或允许宣称 M3 整课生成成功。

## M1 增量兼容字段

2026-10-09 普通PPT重选：`quick-assets/pptx`在已有有效课件时自动创建新的关联课程，返回新项目的素材任务及`source_project_id`；前端以返回的`project_id`切换URL与继续制作记录。新课程拥有所选教师形象、参考语音原件和已选片段的物理副本，保存`source_asset_id`。不复制旧PPT、原页映射、讲稿版本、审核、试听或成片缓存。创建与解析任务同SQLite事务发布，旧revision、忙碌或复制摘要异常不创建新课程；原项目不修改。高级素材上传接口仍保护已有有效课件，详见[一键流程](ONE_CLICK_FLOW.md)。

2026-10-02 M3 增量：项目/逐页继承新增 `layout:overlay|sidebar`，仅使合成失效。M3 只读不可变正式快照，草稿输入存入独立媒体任务、不进入快照表；媒体/人工评审/布局确认接口见 [M3 契约](M3-media-contract.md)。M1 人物普通调用仍要求 30 秒，仅内部 `purpose:m3_segment` 支持真实短页音频。TTS 时间记录新增 `segment_index`，保留原字段和停顿采样行为。

TTS 请求可设置 `purpose:audition`（最短工程输出 0.1 秒）、`speed_factor`、`pause_before`、`speech_segments:[{text,pause_after}]`。原生工作进程同一引擎逐段真实推理，按实际采样率拼接明确停顿，返回 speech_timeline。未指定这些字段时保留原 M1 行为及 30 秒下限；照片/视频样片下限不变。耗时/费用缺实测值保留 null，人工质量字段仍 false/pending。
