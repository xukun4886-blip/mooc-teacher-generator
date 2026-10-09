# 可选云端照片工作进程契约 v1

2026-10-09，用户追加在Web中调用已有云服务器的授权。属于M1-F04/F06、M2-F06、M3-F01/F04/F05/F06的可选部署位置，不改变三项上传、一键完整未审核草稿、播放下载、教师主动确认，也不改变P0照片/视频、画质或审核标准。

## 工作台

`POST /api/projects/{pid}/photo-server/check`接收服务器设置，读取服务健康，不上传/生成/修改项目。`PUT /api/projects/{pid}/photo-server`接收`{revision,settings}`，拒绝运行中项目和旧revision；云端配置须有当前课程的明确外传授权、健康版本及足够计算授权。写入`photo_execution`及追加`photo_execution_history`。原本无字段的项目继续本机；副本回本机，换PPT新项目不继承外传授权。

`settings`字段：`mode(local/cloud)`、`url(HTTPS)`、`token_env`、`batch_size(1/2/4)`、`timeout_seconds(30..7200)`、`allow_uploads`、`allow_paid`、`max_cost`。只保存令牌环境变量名；不接收或存储凭据值。保存时固定协议、模型/运行环境/实现摘要、价格声明。配置显式允许SSH隧道时可使用127.0.0.1/localhost的HTTP端点；远端API仍绑定127.0.0.1，不开放公网端口。

## 工作进程

协议`mooc.photo-worker.v1`，所有接口需Bearer令牌。部署以独立单教师工作进程为界，不是共享SaaS账户系统。

- `GET /v1/health`：`protocol,model,price,ready,blockers,resident_loaded,quality_verified=false`。ready仅表示声明与依赖就绪，不代表已经真实生成或通过质量评审。
- `HEAD/PUT /v1/blobs/{sha}?kind=photo|audio`：PUT为字节流，声明`X-Content-Bytes`，照片最多20MiB、音频100MiB；真实格式、SHA通过才发布。同SHA完整输入可免上传，半份输入不能命中。
- `POST /v1/jobs`：仅接收`idempotency_key,photo_sha256,audio_sha256,model_key,batch_size,max_seconds,allow_paid,max_cost`。默认单片段最多120秒，同幂等键参数不一致HTTP409；缺输入/依赖/费用授权不得入队。
- `GET /v1/jobs/{id}`：持久`queued/running/completed/failed/canceled`、当前输入绑定、执行代次、恢复/失败历史、真实计时/显存及输出摘要。不能以读取完成任务的耗时计新推理。
- `GET /v1/jobs/{id}/result`：仅completed且文件完整SHA一致时下载，支持Range；不接受远端返回的任意URL或本机路径。
- `POST /v1/jobs/{id}/cancel`：取消queued/running，旧结果不能覆盖终态。进程重启对running任务最多两次恢复，保留执行目录/日志；同GPU仅一个工作线程/一个进程锁。

SadTalker照片路径保持256/full/25fps/无增强/FP32与CPU逐帧offload策略。同照片预处理可缓存首帧3DMM、裁剪和crop_info；每次由当前音频生成audio2coeff与人物。模型代码、实际权重及实现/运行环境变更须进入模型key，不能误命中本机旧人物。切换服务器不无条件清理TTS/PPT缓存或删旧成果。

客户端提交前持久化收据。网络中断使用同操作幂等键查询恢复，明确云端failed/canceled且本机有限重试才建立新attempt。下载到`.part`续传，全文件SHA及现有完整媒体检查通过后原子发布。必要文件、音轨、异常静音、时长和最终整课检查保持。没有静态人物、错口型或普通声音降级成功。

实现、配置、限制、部署和30秒/82秒对照详见[本轮记录](../docs/evidence/M3/cloud-photo-interface-implementation.md)。接口工程测试不替代真实数字人质量或阶段退出。
