# 数字人教师慕课生成系统

需求基线：V1.1。实施规则见 [AGENTS.md](AGENTS.md)，进度见 [项目状态](docs/PROJECT_STATUS.md)。

Git/GitHub 保存范围、排除文件与另机恢复限制见 [备份说明](docs/GIT_BACKUP.md)。教师素材、课程运行数据、模型权重及证据截图保存在本机受控存储。

2026-10-08：默认 Web 首页为教师照片/视频、课程 PPT、参考语音三项上传和一键生成，完成后播放下载未审核草稿，再由教师主动确认。原逐页编辑与正式审核移入高级入口，全部历史保留。运行 `tools/m2_start.ps1` 打开本机工作台；操作见 [M3 指南](docs/M3_RUNBOOK.md)，设计见 [一键流程](specs/ONE_CLICK_FLOW.md)。

当前已有 M1 命令行验证工具与 M2 Vue + FastAPI 内容工作台；M1/M2 均未阶段通过。M1 已真实解析/渲染 10 页工程课件与用户 63 页课程，固定三个独立 CUDA 环境和主/辅助权重，并生成 49.7 秒中文语音及照片/视频两条各 30 秒样片。能力、失败预检、原生显存/耗时和不同音频对照持续记录；音色、人物、口型及课程保真仍待人工评审，见 [真实验证](docs/evidence/M1/native-validation.md)。

- [M1 操作与素材准备](docs/M1_RUNBOOK.md)
- [本轮验证证据](docs/evidence/M1/README.md)
- [适配器契约](specs/M1-adapter-contract.md)
- [阶段规格索引](specs/README.md)

在项目根目录执行：

```powershell
.\.venv-m1\Scripts\python.exe -m mooc_m1 inventory --output docs/evidence/M1/environment.json
.\.venv-m1\Scripts\python.exe -m mooc_m1 preflight --manifest config/samples.example.json --output docs/evidence/M1/preflight.json
.\.venv-m1\Scripts\python.exe -m pytest -q
```

当前示例配置的预检退出码为 2，表示明确阻断，不产生成功媒体。大媒体、模型文件、授权记录和本地配置不进入 Git。没有训练入口，不默认将素材用于训练。
## M2 内容工作台

内容链路已建立可运行的 Vue + FastAPI 应用，启动与操作见 [M2 指南](docs/M2_RUNBOOK.md)，真实证据见 [M2 验证](docs/evidence/M2/README.md)。M1/M2 阶段仍待人工评审及退出验证，不代表首版完成。

M4预验收与交付准备已启动，尚未正式通过。最新证据见[M4记录](docs/evidence/M4/README.md)；[部署与启动](docs/DEPLOYMENT.md)、[教师指南](docs/TEACHER_GUIDE.md)、[指标与评审待确认包](docs/M4_REVIEW.md)可用于本机交付核验。
