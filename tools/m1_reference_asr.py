"""Local Whisper-tiny inspection; automatic text is not human review."""
import sys
import json
import argparse
from pathlib import Path
import torch
import librosa
from transformers import WhisperProcessor, WhisperForConditionalGeneration

root=Path(__file__).resolve().parents[1]
model_path=root/'.tools/models/MuseTalk/models/whisper'
torch.set_num_threads(4)
processor=WhisperProcessor.from_pretrained(model_path,local_files_only=True)
model=WhisperForConditionalGeneration.from_pretrained(model_path,local_files_only=True).eval()
parser=argparse.ArgumentParser()
parser.add_argument('input')
parser.add_argument('--output',default=str(root/'storage/m1/reference-asr.json'))
parser.add_argument('--full',action='store_true')
args=parser.parse_args()
path=Path(args.input)
audio,sr=librosa.load(path,sr=16000)
results=[]
windows = [(start,min(start+30,len(audio)/sr)) for start in range(0,int(len(audio)/sr)+1,30)] if args.full else [(0,end) for end in [7.3655,9.0,21.119958]]
for start,end in windows:
    if end <= start:
        continue
    inputs=processor(audio[int(start*sr):int(end*sr)],sampling_rate=sr,return_tensors='pt')
    with torch.no_grad():
        tokens=model.generate(inputs.input_features,language='chinese',task='transcribe',max_new_tokens=180)
    text=processor.batch_decode(tokens,skip_special_tokens=True)[0]
    results.append({'start_seconds':start,'end_seconds':end,'automatic_transcript':text})
    print(end,text,flush=True)
Path(args.output).write_text(json.dumps({'model':'openai/whisper-tiny','mode':'local_cpu','human_review':False,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
