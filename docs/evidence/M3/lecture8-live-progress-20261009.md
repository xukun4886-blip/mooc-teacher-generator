# Lecture 8 生成速度与停滞排查

检查时间：2026-10-09 20:20–20:22（Asia/Shanghai）。对应 M3-F01/F04、FR08–FR10/FR13/FR19、NFR01–NFR03。按 mooc-media-pipeline 执行只读运行诊断，未修改代码、任务、模型、执行位置或重启服务。

- 项目 `877fc5f9-cd0e-445f-b3f9-59c1e00cd1d5`，Lecture 8；当前媒体 `653a6a02-1ae8-4852-9a7c-441636e569f7` 第1代 running/photo_native_generation，error=null。SQLite 使用 mode=ro/query_only。
- 22页中语音17页有效、人物16页有效、合成16页有效；第17页 active_stage=portrait，语音实测96.14秒；第18–22页尚待处理。
- 本机 SadTalker 子进程 PID 20272（包装进程36532），请求 `70be4e5f-47ad-4b73-95fa-652785a381da`。原生日志位于受控存储 `storage/m2/projects/877fc5f9-cd0e-445f-b3f9-59c1e00cd1d5/m3/native/requests/70be4e5f-47ad-4b73-95fa-652785a381da/native.log`。
- 连续读取真实日志从1981–1992/2403推进到2052–2055/2403，约3.1帧/秒，最新86%；逐帧阶段已运行10分26秒，模型日志估计尚需约1分51秒。此估计仅覆盖人物逐帧渲染，后续编码、校验及页面合成另计，不能作为整课完成时间。
- nvidia-smi当次采样：RTX 3050 Laptop，GPU利用率91%，显存3745/4096 MiB，86°C，61.56W。设备占用含桌面等进程，不能据此单独判定降频。本次确实在本机计算，项目没有photo_execution云端配置。
- `/api/health` 返回worker_alive=true；当前日志持续推进，检查窗口内无停滞证据。
- `frontend/src/OneClick.vue` 仅显示语音/人物/合成已完成页数；`mooc_m3/pipeline.py` 的progress仅累计valid/not_required阶段。因此长页逐帧计算期间人物页数仍为16/22，页面不显示本页模型内进度，容易被理解为卡死。
- 旧媒体 `a7376062-d076-4bbb-a728-c48ce85d1344` 第3代为failed/tts_native_generation；旧稿独立标点引起的失败及兼容修复见既有M2证据。本次新任务第17页语音已成功，不是仍在该语音错误点。

结论：当前瓶颈是本机照片数字人逐帧生成，加上界面仅显示完成页数；当次未发现工作进程停止。96.14秒/2403帧按约3.1帧/秒需要约13分钟逐帧计算。整课尚未完成，不据此声明质量或阶段通过。
