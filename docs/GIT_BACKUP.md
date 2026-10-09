# Git 与 GitHub 备份范围

2026-10-10 公开更新：用户选择先脱敏历史再公开。当前 [mooc-teacher-generator](https://github.com/xukun4886-blip/mooc-teacher-generator) 已公开，8份课程证据中的教师邮箱及历史合计49处已替换为脱敏标记。为隔离旧提交缓存，原仓库保留为 [私有存档](https://github.com/xukun4886-blip/mooc-teacher-generator-private-archive-20261010)，公开地址使用独立仓库，仅上传脱敏历史。本机另有完整Git bundle和原始证据备份；两个旧提交在公开仓库的匿名请求均不可访问。详见 [公开核验](evidence/M4/github-public-visibility-20261010.json)。下方私有上传记录属于早期过程。

2026-10-10：用户授权建立本地 Git 提交，并上传至账号 `xukun4886-blip` 的私有仓库 `mooc-teacher-generator`。已完成上传，main分支跟踪origin/main；实际推送退出码和远端提交一致性已核实，见 [项目状态](PROJECT_STATUS.md) 及 [备份预检记录](evidence/M4/git-import-preflight.json)。

仓库保存应用源代码、项目 Skills、需求文档、阶段规格、配置模板、依赖锁定文件、测试、部署说明及文字验收记录。现有需求文档保持原文件；上传不表示 M1–M4 或首版验收已通过。

## 留在本机的文件

- `storage/`：教师照片、视频、参考语音、课程原件、数据库、运行日志、审核快照、生成成果、授权记录及备份。
- `.tools/`、`.venv*/`：模型代码、下载资源及独立运行环境。
- `config/*.local.json`、环境文件、私钥及会话凭据。
- 模型权重和音视频文件。
- `docs/evidence/` 下的截图：可能包含教师形象、课件页面和工作台内容。
- 前端依赖及构建目录：通过 `frontend/package-lock.json` 重新安装和构建。

排除规则见 [`.gitignore`](../.gitignore)。文件仍保存在本机，并未删除。文字证据中的截图及受控存储链接需要在原机器或授权备份中查看；从 GitHub 克隆后，这些链接可能无法打开。

## 克隆与恢复

GitHub 代码备份不包含教师素材、既有课程数据、模型权重或全部运行环境。新机器需按 [部署说明](DEPLOYMENT.md) 准备独立模型环境和本地配置；课程数据需另行进行受控备份及迁移。当前另机完整重建仍待验证。

当前仓库已公开，私有存档不公开。公开证据文本已脱敏，不能把公开文本的文件摘要视为本机原始证据摘要；原始记录仍保留。后续新增证据须再次检查个人联系方式、密钥和教师素材。第三方模型与权重的使用条件仍按 [M1 本地使用记录](evidence/M1/model-usage-local.md) 执行，此次备份未为第三方组件授予新许可。
