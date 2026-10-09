# 本次本地模型使用记录

2026-10-01；范围仅为已授权素材的本地 M1 能力评估，不含训练、权重再分发或正式部署采纳。下载版本和每个文件摘要见 [GPT](gpt-weight-downloads.json)、[SadTalker](sad-weight-downloads.json)、[MuseTalk](muse-weight-downloads.json)。模型代码提交保持 [固定版本](candidate-revisions.json)。

| 组件 | 核查依据与本次使用条件 |
| --- | --- |
| GPT-SoVITS v2 | [作者权重卡](https://huggingface.co/lj1995/GPT-SoVITS) 标注 MIT；代码 MIT。只使用 v2 推理权重，不用 v3/v4 声码器或 Pro 音色嵌入权重 |
| 中文 RoBERTa | [原作者模型卡](https://huggingface.co/hfl/chinese-roberta-wwm-ext-large) 标注 Apache-2.0；使用 GPT 作者提供的对应文件，记录独立摘要，不声称所有衍生文件同一许可证 |
| 中文 HuBERT | [原作者模型卡](https://huggingface.co/TencentGameMate/chinese-hubert-base) 标注 MIT；实际下载 GPT 作者提供的推理副本 |
| G2PW | [原作者仓库](https://github.com/GitYCC/g2pW) 为 Apache-2.0；使用 GPT 上游明确链接的 G2PWModel.zip，固定下载仓库提交及 LFS 摘要 |
| jieba | MIT；本机未安装 C 编译器，显式选择 jieba==0.42.1 替代 jieba_fast 的分词接口。代码通过包装器指定，无自动异常回退；必须记录发音和分词结果差异风险 |
| fastText lid.176.bin | [官方语言识别模型页](https://fasttext.cc/docs/en/language-identification.html) 明确模型为 CC-BY-SA 3.0；保留来源、版本与摘要。显式使用完整 bin 模型，禁用小模型回退和运行时下载，本次不分发权重 |
| NLTK 数据 | 从 [官方 nltk_data](https://github.com/nltk/nltk_data) 获取 cmudict 与两种 averaged_perceptron_tagger；[官方包元数据](nltk-usage-metadata.json) 标注两种 tagger 为 MIT、cmudict 可用于研究及商业用途并希望注明来源。保留各包 NOTICE；归档与来源/摘要见 [语言资产](tts-language-assets.json)，不将 NLTK 软件许可证直接套到全部数据 |
| SadTalker v0.0.2 | [官方代码](https://github.com/OpenTalker/SadTalker) 与 release 下载清单；Apache-2.0，许可证明确保留第三方例外。只用 256/full、mapping_00109 及必要定位权重，不使用 GFPGAN 增强；不把该试验视为所有第三方素材的商用清查完成 |
| facexlib 定位 | [官方许可证](https://github.com/xinntao/facexlib/blob/master/LICENSE) 为 MIT；采用官方 release 中的 alignment_WFLW_4HG 与 detection_Resnet50_Final。本地记录摘要，旧 release 未提供官方摘要时该字段保持未知 |
| MuseTalk v15 | [作者代码](https://github.com/TMElyralab/MuseTalk) 为 MIT；实际权重附带 LICENSE.txt（含第三方许可），保留原文于下载目录；选定权重与辅助权重逐项记录 |
| VAE | [作者模型卡](https://huggingface.co/stabilityai/sd-vae-ft-mse) 的 CreativeML Open RAIL-M 条件适用，不将其写为 MIT；本地授权 M1 推理不涉及分发或训练 |
| Whisper / DWPose / face parsing | 来自 MuseTalk 官方下载清单；[Whisper](https://github.com/openai/whisper) MIT、[DWPose](https://github.com/IDEA-Research/DWPose) Apache-2.0、[face parsing](https://github.com/zllrunning/face-parsing.PyTorch) MIT。S3FD 链接由代码提供，face-alignment BSD-3-Clause。副本摘要不等于重新授权声明 |

本次 usage_review.accepted 表示允许这组公开组件进入本地评估，不代表模型质量通过或正式应用商用方案已采纳。权重与教师素材不进入 Git；正式分发需保留许可/NOTICE、逐项处理第三方条件。
