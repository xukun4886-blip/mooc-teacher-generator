"""Summarize actual cold-process measurements without inventing warm baselines."""
from pathlib import Path
import statistics
from mooc_m1.core import read_json

ROOT = Path(__file__).resolve().parents[1]


def duration(seconds):
    return f'{int(seconds // 60)}分{seconds % 60:.2f}秒'


def main():
    evidence = read_json(ROOT / 'docs/evidence/M3/external-long-courses.json')
    lines = ['# 两条十页真实长课补验 · 2026-10-09', '',
             '本轮完成的是独立外部稿、未经教师审核的工程课程。原课时及旧AI失败项目保留；不是用外部稿补AI成功，也不计入12项正式基线任务。建议指标未冻结，M1–M4退出未通过。', '',
             '三项素材和原页5–14的来源映射、原生请求、全部片段摘要、逐页资源及四类导出见[完整记录](external-long-courses.json)。新上传AI历史见[原失败记录](long-course-validation.json)，免费视觉备选重新上传见[独立AI复验](fresh-ai-validation.json)。', '',
             '| 路径 | 有效页 | 实际成片 | 媒体任务墙钟耗时 | 一键提交至成片完成 | 初始排队 | 恢复次数 | 设备显存峰值 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for mode, entry in evidence['paths'].items():
        state, perf = entry['status'], entry['performance']
        assert state['state'] == 'completed'
        result = state['media']['result']
        label = '照片 · SadTalker' if mode == 'photo' else '原视频序列 · MuseTalk'
        lines.append(f"| {label} | {state['media']['progress']['valid']}/10 | {duration(result['duration_seconds'])} | {duration(perf['media_job_created_to_finished_wall_seconds'])} | {duration(perf['course_submission_to_media_finished_wall_seconds'])} | {duration(perf['course_initial_queue_seconds'])} | {entry['media_history']['recoveries']} | {perf['device_peak_used_mib']} MiB |")
    lines += ['', '两条成片均为163.88秒，距180秒目标少16.12秒；没有填充静音伪装时长。此处只记录“约三分钟”的真实工程结果，正式时长/教学及视听质量仍待确认。照片耗时包含故障注入及三次恢复，不能当作无中断吞吐；视频的一键总耗时包含等待照片完成。墙钟基于持久化创建和最终完成时间；中断前未落盘耗时无法还原，累计检查点耗时另存，不与墙钟混用。', '',
              '| 路径/模型 | 实际冷请求数 | 请求墙钟中位数 | 最快/最慢 | torch分配峰值 | torch保留峰值 |',
              '| --- | --- | --- | --- | --- | --- |']
    for mode, entry in evidence['paths'].items():
        for layer in ['tts', 'portrait']:
            values = [v for v in entry['performance']['native_measurements'] if v['layer'] == layer]
            elapsed = [v['cold_native_elapsed_seconds'] for v in values]
            peak = lambda field: max((v[field] for v in values if v[field] is not None), default=None)
            label = ('照片' if mode == 'photo' else '视频') + ' / ' + values[0]['provider']
            lines.append(f"| {label} | {len(values)} | {statistics.median(elapsed):.2f}秒 | {min(elapsed):.2f}/{max(elapsed):.2f}秒 | {peak('torch_peak_allocated_mib')} MiB | {peak('torch_peak_reserved_mib')} MiB |")
    lines += ['', '本机RTX3050 Laptop 4096MiB，串行运行。设备峰值包括桌面及其他GPU占用，torch分配/保留是各模型进程观测，不能相加当作并发需求。当前每个请求独立加载，全部为冷进程；十页课程同进程预热尚未验证。M1已有30秒同进程预热样片，不外推长课。', '',
              '两条均为1920×1080、25fps、H.264/AAC，全部10页显示教师。整片完全解码及四类HTTP下载摘要通过；29条SRT与实测句段/Manifest一致、完整显示文本保留。两条结束时差均为0秒；非逐词对齐或口型质量结论。十份原生请求的所选人物文件和各自音频摘要均核对，MuseTalk十组当前Whisper特征各异且均为原视频请求。', '',
              '[浏览器实测](../M4/browser-long-courses.json)记录两条从0连续播放到结束、实际MP4下载和跳转。两条高级SRT/讲稿/JSON下载摘要与第6页跳转均已检。视频自动化拖动两次未改变时间，原因未确定；点击进度条和键盘定位通过，拖动待人工/桌面浏览器复核。没有提交教师确认。', '',
              '照片重启记录见[实际原生进程中断](../M4/real-model-restart.json)与[首次脚本超时](../M4/real-generation-restart.json)，有效片段哈希保持，同一个任务最终10/10恢复完成。最新启动与默认PowerShell脚本策略的首次失败另见[启动复测](../M4/final-startup.json)和[首次启动](../M4/final-startup-first.json)。', '',
              '音色、人物、口型、字幕误差、原页重点遮挡、视频转向接缝、内容正确性及理解/连贯评分仍待人工。受控20句/20口型候选/5段十秒及三名评审空白表见[评审材料索引](../M4/review-materials.json)。']
    (ROOT / 'docs/evidence/M3/long-course-validation.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Long-course report generated from actual completed evidence')


if __name__ == '__main__':
    main()
