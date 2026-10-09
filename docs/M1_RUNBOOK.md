# M1 操作与素材准备

更新：2026-10-01。范围：M1-F01–M1-F06；真实教师能力未通过。当前工具仅在本机运行，不提供多人工作台、HTTP 上传、付费 API 或模型训练。

## 需要准备的素材

照片、视频和参考语音应来自同一位同意参与的教师，可以使用你本人。放在本地目录并提供位置；授权文件单独保存，不把个人签名或联系方式放入 Git 证据。

| 素材 | 准备方式 | 建议/上限 |
| --- | --- | --- |
| 课程 PPTX | 约 10 页，含正文、备注、图表、公式、至少一页纯图片；尽量提供原始可编辑文件 | 默认 1–50 页，可配置 max_ppt_pages；100 MB；PPT 转换本轮尚未实现 |
| 教师照片 | 清晰正脸，人物可辨识，无遮挡，JPG/JPEG/PNG | 20 MB；建议短边至少 512 像素，建议不是硬门槛 |
| 教师视频 | 同一人，清晰面部、自然眨眼和头部动作，避免频繁切镜或大幅转头 | MP4，5–60 秒，500 MB；建议 H.264 |
| 参考语音 | 同一人，单人普通话、少噪声、无背景音乐，附准确文字 | WAV/MP3/M4A，50 MB；建议 20–60 秒 |
| 确认测试稿 | 阅读下方草稿，确认专业术语读法及内容；保留审核记录 | 最终由实际 TTS 时长检查，草稿字数不能证明有 30 秒语音 |
| 授权记录 | 素材来源、权利人、参与教师同意、允许用途、有效范围和保留/删除方式 | 覆盖课件处理、照片动画、视频口型修改、音色合成 |

可采用如下授权说明并由相关权利人确认：“本人有权提供所列课件，且同意本项目在本地进行课件解析与渲染、本人照片动画、本人视频口型处理和本人音色合成，用于 M1 能力验证；不默认用于模型训练。素材来源、使用范围、保留期限及删除联系人另附。”课件权利人与教师不是同一人时分别确认。此文本仅是准备样例，不替代真实授权证据。

参考语音原文件的 20–60 秒是输入建议。已核查的 GPT-SoVITS 源码对一次参考片段检查 3–10 秒；后续应明确选择清晰子片段并记录原文件摘要、起止时间和对应文字。工具不会把长参考音频静默截短，也不会退回普通音色。实际采纳版本的约束需重新确认。

## 中文测试稿草稿

用户已在本会话确认本次测试稿，实际读法稿保存于受控 config/samples.local.json 和原生请求中，已生成 49.7 秒真实语音。下方为最初建议草稿，部分句子与最终确认版本不同，仅保留作编写示例；复现应使用当前已确认请求，不能将示例视为审核版本。显示文本、读法文本与停顿提示分开保存，不把括号、数组和引用标记作为通用垃圾字符删除。

显示文本：

> 今天我们用能量与质量的关系介绍模型输入和结果核查。公式 E = mc² 中，E 表示能量，m 表示质量，c 表示光速。先看一个数值例子：输入质量为 1.2 千克时，要先统一单位，再代入公式。数组 [1, 2, 3] 表示三次实验编号，不是需要删除的控制指令。请注意“采样率”“帧率”和“音色”是不同概念。2026 年的这次验证，会分别检查中文术语、完整句子和口型同步。最后，对照原始课件和实际生成音频，检查是否漏句、重复，以及视频连接处是否出现跳变。

建议读法文本：

> 今天我们用能量与质量的关系介绍模型输入和结果核查。公式，E 等于 m 乘以 c 的平方。其中，E 表示能量，m 表示质量，c 表示光速。先看一个数值例子：输入质量为一点二千克时，要先统一单位，再代入公式。数组，一、二、三，表示三次实验编号，不是需要删除的控制指令。请注意，采样率、帧率和音色，是不同概念。二零二六年的这次验证，会分别检查中文术语、完整句子和口型同步。最后，对照原始课件和实际生成音频，检查是否漏句、重复，以及视频连接处是否出现跳变。

非朗读停顿提示：公式解释后、数组解释后各建议停顿一次。当前原型只将确认读法文本交给模型，停顿事件的精确插入属于后续内容/媒体链路，尚未实现；不能宣称停顿参数已生效。

## 本机环境与重现

当前使用 `.venv-m1`（Python 3.10.4）作为验证/控制环境。为复用机器已有的 pywin32、pytest、PyYAML，该环境启用了 system-site-packages；新增解析依赖只安装在此环境，没有修改全局依赖。模型不能安装在此环境，每个模型应有自己的解释器/服务，避免 CUDA 和 PyTorch 覆盖。

本轮 pip 的 HTTPS 连接出现 SSLEOFError，未关闭证书检查。通过 PowerShell 从 PyPI 官方 JSON 获取 wheel，核查官方 SHA-256 后离线安装；准确版本见 [requirements-m1.txt](../requirements-m1.txt) 和 [工具来源记录](evidence/M1/toolchain.json)。重建时可在网络正常的机器使用：

后续定位到 Python 读取的 Windows 代理导致连接失败/停滞。`tools/m1_pip_direct.py` 在当前 pip 进程关闭自动代理读取，对 PyPI 官方索引/文件使用 PowerShell HTTPS 传输，保留证书、pip 解析和摘要校验，不修改系统代理或全局依赖。该方式已实际安装三个独立模型环境；CUDA wheels 按官方索引摘要校验。准确安装结果和完整冻结见 [模型环境](evidence/M1/model-environments.json)。

```powershell
python -m venv .venv-m1
.\.venv-m1\Scripts\python.exe -m pip install -r requirements-m1.txt
.\tools\m1_storage.ps1 -Mode Initialize
```

FFmpeg 是官方网站链接的 gyan.dev Windows 构建，本轮安装在 `.tools/ffmpeg/`，没有修改系统 PATH。PowerPoint 16.0 负责原页静态 PNG 导出；python-pptx 1.0.2 仅解析结构。导出在独立进程进行、禁用宏、只读打开；无法取得独立 PowerPoint 进程时失败，避免关闭用户已打开的课件。导出目录必须为空，防止旧页混入结果。

```powershell
.\.venv-m1\Scripts\python.exe -m mooc_m1 ppt 'D:\素材\课件.pptx' --output storage/m1/course-check --render
.\.venv-m1\Scripts\python.exe -m mooc_m1 media 'D:\素材\教师视频.mp4' --kind video --output storage/m1/video-inspection.json
.\.venv-m1\Scripts\python.exe tools/m1_engineering_fixture.py
.\.venv-m1\Scripts\python.exe tools/m1_fault_evidence.py
.\.venv-m1\Scripts\python.exe -m pytest -q --junitxml=docs/evidence/M1/tests.xml
```

最后三条使用工程课件、测试波形或故障刺激，不是教师真实能力验证。需要目视检查原课件与导出页的字体、公式、图表和嵌入媒体显示。

## 本地配置及模型准备

复制 [m1.example.json](../config/m1.example.json) 到 `config/m1.local.json`、[samples.example.json](../config/samples.example.json) 到 `config/samples.local.json`，填写本地路径、同一 teacher_id、授权摘要/受控记录位置和确认稿。示例所有授权默认 false。

`models.tts/photo/video` 的配置字段见 [适配器契约](../specs/M1-adapter-contract.md)。当前代码、独立解释器、主/辅助权重及使用条件已固定，见 [模型环境](evidence/M1/model-environments.json)、[使用记录](evidence/M1/model-usage-local.md)。本机 4 GB GPU 已产生真实 TTS 和两条 30 秒样片；尚未采纳为正式质量达标方案，不声称支持并发和长课。权重下载工具分别为 tools/m1_fetch_gpt_weights.py、tools/m1_fetch_sad_weights.py、tools/m1_fetch_muse_weights.py，CUDA wheel 工具为 tools/m1_cuda_wheels.py；当前配置包含 SHA-256 清单，缺主/辅助资产不允许生成。

```powershell
.\.venv-m1\Scripts\python.exe -m mooc_m1 --config config/m1.local.json preflight --manifest config/samples.local.json --output storage/m1/authorized-preflight.json
.\.venv-m1\Scripts\python.exe -m mooc_m1 --config config/m1.local.json generate --role tts --request storage/m1/tts-request.json
.\.venv-m1\Scripts\python.exe -m mooc_m1 --config config/m1.local.json generate --role photo --request storage/m1/photo-request.json
.\.venv-m1\Scripts\python.exe -m mooc_m1 --config config/m1.local.json generate --role video --request storage/m1/video-request.json
```

角色请求：TTS 使用 `text`、`reference_audio`、`reference_transcript`、`script_confirmed:true`；照片使用 `photo` 和 `audio`；视频使用 `video` 和 `audio`。全部请求须含 `authorized:true` 和 `authorization_record`。照片与视频必须使用同一份当前真实 TTS 音频；至少 30 秒，通过完整解码、异常静音和驱动时长核对后仍只进入 `media_ready/awaiting_human_review`。确认语音、身份和口型不通过时，不记阶段通过。之后另用不同讲解音频重跑，验证驱动对应关系。

GPT-SoVITS 加载前拒绝配置回退；实际主权重与版本另记录，fastText 和 NLTK 明确使用本地资产，禁止运行时下载/备用小模型回退。三类模型实际加载的 torch/safetensors 文件均有摘要跟踪（范围不包含所有潜在的自定义加载接口）。MuseTalk 上游含拼接 shell 命令，包装器完整复制源视频和驱动音频到 ASCII 无空格 UUID 目录，使用完整原序列；本次短视频为正放后倒放，转向/口型仍需连续播放评审。

MuseTalk 原生加载曾真实 OOM，显式 memory_profile=cpu_staged_fp16 在 CPU 暂存同一 UNet 权重、入卡前转 FP16 后生成成功；不是视频模式切换或模型替换。完整日志和实际失败保留，不把注入 OOM 测试当硬件实测。资源数据见 [真实验证](evidence/M1/native-validation.md)。

TTS 请求可增加 measure_warm:true，在同一引擎再次合成真实 audio-warm.wav；人物请求可增加 warm_audio 指向另一份至少 30 秒的真实讲解音频，在同一原生实例中重新生成 video-warm.mp4。视频预热需 cpu_staged_fp16。当前音频 B 为完整已确认 TTS 的 10–40 秒连续区间；输出 A/B 均需独立解码、音轨/时长检查及观看口型。预热耗时以第二次实际生成计，不把新进程启动当预热，也不以换音轨代替重新推理。

## 存储与删除

`storage/m1` 已设置仅当前 Windows 用户、SYSTEM、Administrators 可访问的 ACL；该设置只覆盖本机 M1 默认目录。`.gitignore` 排除素材、媒体、权重环境和本地配置。配置为外部存储时，应另外设置其权限。没有任何默认训练或自动素材上传路径。

请求日志可能包含教学文本，留在受控存储。发布证据只记录摘要、工具版本、已脱敏失败原因和访问位置。主动删除指定请求可执行：

```powershell
.\tools\m1_storage.ps1 -Mode DeleteRequest -RequestId '这里填写请求 UUID' -WhatIf
.\tools\m1_storage.ps1 -Mode DeleteRequest -RequestId '这里填写请求 UUID'
```

删除工具只允许默认 `storage/m1/requests/<UUID>`，检查目录边界并拒绝重解析点。没有默认保留期限或自动清理任务；素材原件与其他目录需按约定另行删除。
