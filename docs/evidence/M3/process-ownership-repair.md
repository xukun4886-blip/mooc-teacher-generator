# Windows 进程归属修复与边界

2026-10-09。关联 M3-F04、FR13/FR18/FR19、AC09/AC15/AC16、NFR01/NFR02/NFR08。

旧真实视频首次失败 `PROCESS_OWNERSHIP_FAILED` 仍在 [原记录](one-click-real.json)。旧记录没有 Windows 错误码，不能唯一确定那次失败的原因。代码检查发现可修复竞态：Popen 让子进程先运行，随后才 AssignProcessToJobObject；极短命令可在归属前退出，早启动的后代也可能不被正确约束。

`mooc_m1/core.py` 现使用 CREATE_SUSPENDED，先建立 kill-on-close Job Object 并赋予进程，再用 Toolhelp 获取所属主线程并 ResumeThread。失败记录具体 API 和 Windows 错误码，保持严格失败，不在归属失败时放行模型。超时关闭已持有的 Job Object，不按可能复用的 PID 清理；异常和日志句柄在 finally 清理。设计依据：[进程标志](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)、[Job 赋予](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)、[Thread32First](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-thread32first)、[ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread)。

40 个立即退出 Python 子进程压力检查通过；真正 owner 进程死亡、所属 native 子树退出和 SQLite 恢复回归通过，见 [修复检查](../M4/repair-tests.xml)、[全套工程检查](../M4/engineering-tests.xml)。这不构成“偶发错误绝不再发生”的保证。

真实十页照片任务的 [首次重启](../M4/real-generation-restart.json) 在合成边界保存已完成页；初版验证脚本错误地用受短命令 Job 约束的 PowerShell 启动后台服务，发生超时及第二次中断。记录保留，脚本改为独立隐藏 Popen 启动长驻服务。该边界未观察到原生 Python 子进程，所以这一条的模型子树退出结论为空，不冒充原生证明。

随后在实际 SadTalker 运行时执行一次 [原生重启核验](../M4/real-model-restart.json)，记录正在运行的模型 PID，终止正确监听服务后确认所属后代退出。同一个媒体任务恢复到第三次，已完成片段文件摘要保留。后续不再注入重启，避免超过既定三次恢复上限。最终是否完成及缓存命中以 [长课记录](external-long-courses.json) 为准。
