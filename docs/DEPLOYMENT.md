# 本机交付与启动

本轮交付为 Windows 本机工作台与预验收资料；M1–M4 尚未正式通过。现有机器使用 Vue + FastAPI、SQLite WAL、本地文件和三个独立模型环境。真实启动证据见 [交付核验](evidence/M4/delivery-startup.json)，版本及权重见 [实测清单](evidence/M4/version-inventory.json)。该核验使用隔离目录，未替换现有课程，也不等于新电脑完整安装验证。

## 已有机器启动

在 PowerShell 中执行：

```powershell
Set-Location -LiteralPath 'D:\XuTao_Task'
.\.venv-m1\Scripts\python.exe -m mooc_m2 --port 8765 --open
```

命令在当前终端运行服务并用短期一次票据打开浏览器；保持终端运行，Ctrl+C 停止。已运行时执行 `.\.venv-m1\Scripts\python.exe tools/m2_open.py` 打开已有工作台，该工具先核验服务身份和工作进程再发送本机登录凭据。端口默认8765，只监听127.0.0.1。已有机器前端已构建；新机器先按下节构建。需要后台运行时：

```powershell
Start-Process -FilePath 'D:\XuTao_Task\.venv-m1\Scripts\python.exe' -ArgumentList '-m','mooc_m2','--port','8765' -WorkingDirectory 'D:\XuTao_Task' -WindowStyle Hidden -RedirectStandardOutput 'D:\XuTao_Task\storage\workbench.stdout.log' -RedirectStandardError 'D:\XuTao_Task\storage\workbench.stderr.log'
.\.venv-m1\Scripts\python.exe tools/m2_open.py
```

第二条命令应在服务启动完成后执行；如尚未就绪，检查上述日志并重试打开。健康检查：`Invoke-RestMethod http://127.0.0.1:8765/api/health`。`worker_alive=true` 只代表工作进程存活，不代表模型或课程质量通过。电脑重启后重新运行启动器；未配置开机自启。改代码后在可中断点停止并重启；不要启动两个使用同一存储目录的服务。

允许运行本地PowerShell脚本的环境也可使用 `tools/m2_start.ps1`，自动检查前端构建并核验已运行服务。默认Windows PowerShell策略可能拒绝`.ps1`；本轮[首次最终启动](evidence/M4/final-startup-first.json)确实遇到此问题，改用以上Python入口后[复测](evidence/M4/final-startup.json)通过，两条成片及项目保持不变。无需修改系统执行策略。隔离交付检查中的脚本测试使用仅该进程的Bypass参数，不代表默认策略可直接执行脚本。

需要单独核验启动、一次票据、访问限制与保存重开时运行：

```powershell
.\.venv-m1\Scripts\python.exe -m tools.m4_delivery_check
```

该命令使用 8766 端口及 `storage/m4-delivery/`，实际启动两次并停止自己的监听进程，保留验证项目和日志。8766 应未被其他服务占用。课程制作期间可执行这一核验，不调用生成模型。

## 新机器准备与限制

已实测环境与安装版本以版本清单为准：Windows、Python 3.10、Node、FFmpeg/ffprobe 和已安装的 Microsoft PowerPoint。PowerPoint 承担原页放映渲染，python-pptx 只解析结构。必须保留渲染字体，原页保真需教师复核。当前照片只有 180×168，1080p 是合成画布尺寸，不提升原人物细节。

1. 复制源代码，按 `requirements-m2.txt` 建立控制环境 `.venv-m1`；模型依赖不得装进控制环境。前端进入 `frontend` 执行 `npm.cmd ci --no-audit --no-fund`、`npm.cmd run build`。锁定清单是 `frontend/package-lock.json`。
2. 依据 [模型版本清单](evidence/M4/version-inventory.json) 检出 GPT-SoVITS、SadTalker、MuseTalk 的精确提交，分别建立 Python 环境；项目内依赖入口为 `config/gpt-runtime.requirements.txt`、`config/sad-runtime.requirements.txt`、`config/muse-runtime.requirements.txt`。CUDA PyTorch 与辅助权重必须按实测 freeze 与摘要准备，不用三个模型的合并 requirements。使用条件见 [本地使用记录](evidence/M1/model-usage-local.md)。新机器重新安装及模型复测尚未完成。
3. 新建 `config/m1.local.json`：可从 `config/m1.example.json` 开始，但三个 null 模型必须补齐，契约见 [适配接口](../specs/M1-adapter-contract.md)。设置当前机器的 Python、repo、代码 revision、权重文件/摘要、FFmpeg/ffprobe、推理参数和 TTS YAML 路径。不要直接复制另一机器的绝对路径。4 GB GPU 的 MuseTalk 使用已验证 `cpu_staged_fp16`，TTS 使用 `jieba`；这些选择不保证其他机器质量和性能。
4. 从 [配置模板](../config/m4.example.json) 新建 `config/m2.local.json`，调整受控存储路径与页数上限。默认 50 页；现有授权课件 63 页的本地配置是特定测试设置。单 GPU 密集任务串行，任务总时限 21600 秒，模型单请求时限来自 M1 配置。新上传自动讲稿需要已配置的真实服务；无服务时明确阻断，可从高级入口使用备注或外部稿。
5. 讲稿服务密钥只放环境变量；模板不含密钥。外部服务须显式 `allow_external=true`。既有免费GLM-4.6V-Flash持续429/1305后，本轮核查并切换同一智谱接口的免费GLM-4.1V-Thinking-Flash，`allow_paid=false`，不是运行中自动回退。免费白名单按官方当前模型文档精确匹配名称和地址，其他模型不能凭“Flash”后缀绕过费用授权。实际兼容性和新上传结果见[技术决定](evidence/M4/ai-alternative-decision.json)与[独立复验](evidence/M3/fresh-ai-validation.json)。发给服务的是授权课件图文/备注/大纲，人物及参考语音在本机处理。不要把永久会话令牌、素材或完整响应日志放到公共仓库。
   2026-10-09新课件修复将本机及模板的输出额度设为8000；结束原因`length`始终失败，不接受截断正文。每页格式最多两次纠正，与429/503共同限制在四次请求内。已有服务只在任务空闲时重启加载配置，旧失败记录不删除；实际契约/配置修复后可新建有限制作任务，已完成稿保留。见[真实修复记录](evidence/M2/lecture9-format-repair.md)。
6. 运行每个环境的 `python -m pip check`，模型预检及两条真实路径重新验证。示例空配置预检被阻断是预期结果，不算部署成功。

## 数据迁移与备份

原课程位于 `storage/m2/`，SQLite 是 `content.sqlite3`，项目文件在 `projects/<UUID>/`，永久本机会话凭据在 `.session-token`。模型和大媒体被 Git 忽略。授权、素材、讲稿、快照、成片及审核必须随受控存储一起保存，不能只迁移数据库或只拷贝 MP4。

备份前先停止服务，确认当前模型进程退出，再整体复制 `storage/m2` 到受控目录；不在运行时单独复制 WAL 数据库。现有复制/删除 API 操作各项目的物理副本；删除不可恢复，应由教师明确操作。新机器迁移后检查路径、Windows ACL 和文件摘要，不共享旧机器会话凭据。完整迁移/备份恢复实演尚待另机条件，本轮只验证本机持久化和进程重启。

## 验证交付

```powershell
.\.venv-m1\Scripts\python.exe -m pytest -q --junitxml=docs/evidence/M4/engineering-tests.xml
.\.venv-m1\Scripts\python.exe -m tools.m4_delivery_check
.\.venv-m1\Scripts\python.exe -m tools.m4_real_validation collect
.\.venv-m1\Scripts\python.exe -m tools.m4_real_validation collect --external
.\.venv-m1\Scripts\python.exe -m tools.m4_real_validation collect --report fresh-ai
```

首次失败记录不覆盖，修复复测另存。测试替身只证明编排，真实输出与人工评分另行记录。正式验收还缺素材数量、评审及指标冻结，详见 [预验收结果](evidence/M4/README.md) 和 [待确认材料](M4_REVIEW.md)。没有提交、推送或对外部署。
