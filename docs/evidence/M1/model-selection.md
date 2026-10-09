# 候选核查与环境划分

核查日期：2026-10-01。当前三个模型已用于本地真实 M1 推理，尚未采纳为正式质量达标方案。实际组合固定为 GPT v2、SadTalker v0.0.2/256、MuseTalk v15，见 [真实验证](native-validation.md)、[独立环境及全部版本](model-environments.json)、[逐组件使用条件](model-usage-local.md)。候选提交见 [记录](candidate-revisions.json)，资料来源不等于运行证据。

下表及隔离/来源记录为首轮源码核查历史，描述当时尚未安装的条件。后续已按固定提交检出代码、下载校验权重和准备独立环境，不修改上游已跟踪代码。实际运行边界以上方真实验证为准，不把历史“未安装”作为当前阻断。

| 角色 | 当前核查代码 | 官方资料/源码显示 | 本轮决定及限制 |
| --- | --- | --- | --- |
| 中文参考音色 | [GPT-SoVITS 固定提交](https://github.com/RVC-Boss/GPT-SoVITS/tree/48b1a0169a28582a8984402f82cf438d3bfa6aca) | 中文与参考音色功能；API v2 使用 TTS_Config/TTS.run；源码参考片段 3–10 秒，缺失路径存在默认权重回退 | 建立独立进程调用，加载前拒绝回退。v2/v2Pro 等版本实际组合尚未固定，全部辅助权重和使用条件待逐一核查 |
| 照片人物 | [SadTalker 固定提交](https://github.com/OpenTalker/SadTalker/tree/cd4c0465ae0b54a6f85af57f5c65fec9fe23e7f8) | 照片与驱动音频输入；文档主要起点为 Python 3.8 + 较旧 PyTorch/CUDA；V0.0.2 256/512 safetensors 及辅助权重 | 初始原型 size=256、batch_size=1，无 enhancer 自动下载入口；正式版本尚未采纳，Python 3.8 环境本机尚未准备。不能证明 4 GB GPU 足够 |
| 视频口型 | [MuseTalk 固定提交](https://github.com/TMElyralab/MuseTalk/tree/0a89dec45a0192b824e3cf4daf96c239440c5ed8) | 1.5 视频配音，256×256 面部区域；Python 3.10 起点；Whisper、VAE、UNet、检测/面部分割等依赖；Windows 调用需显式模型参数 | 原型明确 v15 模型/配置路径、batch_size=1、fp16、完整源视频输入。实际模型/依赖未安装，身份/抖动/接缝问题待验证 |

候选代码许可记录：[GPT-SoVITS MIT](upstream/GPT-SoVITS-LICENSE)、[SadTalker Apache 2.0 及第三方例外声明](upstream/SadTalker-LICENSE)、[MuseTalk MIT](upstream/MuseTalk-LICENSE)。代码许可不能自动覆盖所有辅助模型、训练数据或教师素材；MuseTalk README 还单独描述模型、其他开源依赖及演示测试数据的使用条件。未确认完整权重组合前不填写 usage_review.accepted:true，也不把网上示例人脸/声音作为授权教师素材。

本轮没有采用外部付费 API，没有下载大权重，没有把官方演示吞吐量作为项目性能。控制环境 `.venv-m1` 仅安装解析/探测依赖；模型计划各用独立解释器或隔离服务。当前机器有 4 GB GPU、可用显存约 2.8 GB，模型能否加载/完成 30 秒任务仍未知。缺 nvcc 不是单独的模型不能运行证明，实际 PyTorch 自带 CUDA runtime 需要另行检测。

待补齐完整权重清单、SHA-256、代码与权重实际版本、依赖锁、输入时长约束、加载与显存证据。照片和视频路径不因硬件不足自行裁剪；若需替换模型或设备，依据兼容和质量实测决定。
