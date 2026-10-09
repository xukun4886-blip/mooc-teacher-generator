"""One exact reference clip, local existing Whisper weights; no network/teacher approval."""
import json
import sys
from pathlib import Path
import torch
import librosa
from transformers import WhisperProcessor, WhisperForConditionalGeneration

torch.set_num_threads(4)
source, output, weights = sys.argv[1:]
processor = WhisperProcessor.from_pretrained(weights, local_files_only=True)
model = WhisperForConditionalGeneration.from_pretrained(weights, local_files_only=True).eval()
audio, _ = librosa.load(source, sr=16000)
features = processor(audio, sampling_rate=16000, return_tensors='pt').input_features
with torch.no_grad():
    tokens = model.generate(features, language='chinese', task='transcribe', max_new_tokens=180)
text = processor.batch_decode(tokens, skip_special_tokens=True)[0].strip()
Path(output).write_text(json.dumps({'text': text, 'model': 'local_whisper_tiny', 'human_review': False}, ensure_ascii=False), encoding='utf-8')
