# M1 原型适配器契约 v1

状态：已实现并运行真实模型，视听质量待评审。关联 [M1 spec](M1-capability-validation.spec.md) 的 M1-F03–M1-F06，不改变 FR/NFR/AC 或 P0 范围。

实现入口：[LocalModelAdapter](../mooc_m1/adapters.py)、[原生工作进程](../mooc_m1/model_worker.py)、[预检](../mooc_m1/preflight.py)。正式工作台/API/持久化队列不在此契约范围。

## 配置字段

`config/m1.local.json` 中 `models` 按 `tts/photo/video` 配置各自对象，未配置时为 null。各模型对象包含：

| 字段 | 行为 |
| --- | --- |
| repo / python | 本地代码目录和独立解释器的绝对路径 |
| code_revision | Git 完整提交 SHA；health 校验实际 HEAD 和已跟踪代码未修改 |
| weight_version | 配置的权重版本标记；不作为实际加载证明 |
| weights | 全部主/辅助权重文件的 `path`、`sha256` 清单；存在且摘要相等才可继续 |
| usage_review | `accepted:true`、来源链接及说明；未核查使用条件时不可采纳 |
| device | cuda 或 cpu；cuda 要求模型解释器的 torch.cuda.is_available() |
| chinese / reference_timbre | TTS 两者均须显式 true；官方声明与实测字段分开 |
| constraints | 每项素材可配置 min_seconds/max_seconds/min_short_edge；未知项不编造 |
| timeout_seconds | 默认 900 秒；是原型配置，不是冻结性能指标 |
| tts_config | TTS 特有的显式 custom YAML；主要权重必须与摘要清单对应，拒绝缺路径回退 |
| tokenizer_backend / fasttext_cache / nltk_data | TTS 显式 jieba 适配及离线语言资产路径；语言模型固定在清单中，禁止运行时下载和备用小模型回退 |
| size | SadTalker 原型默认 256，实际能力仍待实测 |
| ascii_work_root | MuseTalk 的受控临时目录，须 ASCII 且无空格，并设置访问权限 |
| memory_profile | MuseTalk 可显式选 native 或 cpu_staged_fp16；后者使用同一权重，CPU 暂存并转 FP16 后转入 CUDA，不改变人物或音轨模式 |

当前媒体异常静音策略可配置：-45 dB、持续 1 秒、静音比例 0.95；完全低电平短音频也失败。这是异常检查工程阈值，不能代替 V1.1 的视听质量指标或人工试听。

## 方法与结果

- `health()`：返回 role、ready、blockers、dependencies、model_loaded:false。检查配置文件、权重摘要、必要运行时模块存在、torch/CUDA，以及视频环境 mmcv.ops 的二进制导入；不生成，不证明全部模型能在显存中加载或质量通过。每个阻断项含 code、message、source、remedy。
- `capabilities()`：返回 schema_version、提供方、代码/配置权重版本、输入类型、中文/参考音色 declared 与 verified、实际约束、取消和资源字段。未知耗时/模型显存为 null；未验证不填 true。
- `generate(request)`：同步在独立模型进程执行，分配 UUID；状态与请求保存在受控目录。返回 request_id、真实阶段、输出元数据或明确错误。生成前授权、确认稿、当前音频和实际约束必须可用。TTS、照片、视频均没有普通音色、静态照片、无人物或固定说话片段回退。
- `status(request_id)`：从磁盘读取状态，不能传目录路径。进程已退出而状态仍 running 时记录 RUN_FAILED。没有自动重试、中断接口或原生服务重启承诺；完整异步队列/取消归 M3。

状态为 `running/preflight`、`running/native_generation`、`failed`、`media_ready/awaiting_human_review`。media_ready 表示媒体工具检查通过，`quality_verified` 仍 false，不是正式成功。错误输出为空，失败文件不会作为成功片段使用。

媒体返回路径、SHA-256、真实时长、采样率/帧率、编码、分辨率。记录当前驱动音频摘要、代码提交及实际原生版本。隔离进程跟踪成功的 torch.load/safetensors.load_file 调用和文件摘要；TTS 另记录引擎实际选择的主权重。该跟踪范围不包括所有潜在的自定义加载接口。原生日志随执行写入受控目录，超时或失败保留日志。

设备采样包含桌面及其他进程；单进程另记录 torch 的峰值 allocated/reserved，二者范围不同。每个请求启动新进程，标 cold_process。TTS 可传 measure_warm:true，在同一引擎再次推理并验证 audio-warm.wav；人物请求可传 warm_audio（另一份至少 30 秒真实音频），原生实例保留在同一进程，对当前新音频重新生成 video-warm.mp4。视频预热要求显式 cpu_staged_fp16。warm_seconds 测量相应第二次推理/生成，不把第二个新进程当预热；预热媒体同样必须解码、非异常静音及核对实际音频时长。

预检只做文件、授权、解码、摘要、约束和依赖检查，不执行 native generation、不查询付费服务。已配置三类真实模型；实际首次 MuseTalk 加载显存不足、TTS 依赖缺失及语言资产下载停滞等失败见原生证据，不用注入的 OOM 字符串代替真实故障。

## 统一错误码

| 错误码 | 含义 |
| --- | --- |
| INPUT_MISSING / AUTHORIZATION_MISSING | 缺素材或缺适用授权/教师映射 |
| INPUT_INCOMPATIBLE | 稿件未确认、实际输入类型/时长/大小/分辨率不兼容 |
| SERVICE_CONFIG_MISSING | 服务/本地解释器/必要配置缺失 |
| MODEL_NOT_READY | 代码/权重/摘要/使用条件未就绪 |
| RESOURCE_INSUFFICIENT | CUDA 不可用或进程报告 out of memory；后者的注入测试不证明实机已发生显存不足 |
| TIMEOUT | 超过配置时限，终止当前拥有的进程树 |
| UNDECODABLE / NO_VALID_MEDIA | 真实解码失败、空文件、无有效流或时长 |
| ABNORMAL_SILENCE / DURATION_MISMATCH | 异常静音或与驱动音频时长不符 |
| RUN_FAILED | 原生进程失败、所有者退出、其他执行失败 |

## 已验证边界

M2 兼容增量：TTS 可显式传 `purpose:audition` 生成短页试听（工程下限 0.1 秒）、`speed_factor`、`pause_before` 及 `speech_segments`，同一引擎逐段推理并按实际采样率插入明确停顿，返回实际 speech_timeline；见 [M2 契约](M2-content-contract.md) 与 [真实控制证据](../docs/evidence/M2/control-validation.json)。不指定时 M1 原请求行为和 30 秒样片下限保持不变，照片/视频下限不变。M2 短页试听不能替代 M1 30 秒样片或人工音色/口型质量通过。

验证记录见 [M1 证据](../docs/evidence/M1/README.md)。已产生真实 TTS 及照片/视频样片，工具测试与文件解码不能证明音色、身份和口型质量。不同音频对照、模型预热及人工评审按实际记录更新，未完成不得标为通过。
