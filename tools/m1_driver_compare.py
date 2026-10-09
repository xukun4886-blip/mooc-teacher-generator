"""Compare independently rendered current-audio outputs, not just container hashes."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from mooc_m1.core import read_json,write_json,run,digest
from mooc_m1.__main__ import setup
from m1_sample_review import audio_pcm,correlation,frame


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('request_id')
    args=parser.parse_args()
    media,adapters,storage=setup(read_json('config/m1.local.json'))
    state=read_json(Path(storage)/'requests'/args.request_id/'status.json')
    if state['state']!='media_ready' or not state.get('warm_output'):
        raise RuntimeError('Actual primary and warm media must pass adapter checks first')
    role=state['role']
    work=Path(storage)/'driver-comparison'/args.request_id
    work.mkdir(parents=True,exist_ok=True)
    checks=[]
    hashes=[]
    for label,output,input_name in [('a',state['output'],'audio'),('b',state['warm_output'],'warm_audio')]:
        driver=state['inputs'][input_name]
        driver_pcm=audio_pcm(media.ffmpeg,driver['path'],work/f'{label}-driver.wav')
        final_pcm=audio_pcm(media.ffmpeg,output['path'],work/f'{label}-final.wav')
        result=run([media.ffmpeg,'-v','error','-i',output['path'],'-map','0:v:0','-f','framemd5','-'])
        checksum_file=work/f'{label}-frames.md5'
        checksum_file.write_text(result['stdout'],encoding='utf-8')
        rows=[line.rsplit(',',1)[-1].strip() for line in result['stdout'].splitlines() if not line.startswith('#') and line.strip()]
        hashes.append(rows)
        checks.append({'label':label,'driver_audio_sha256':driver['sha256'],'output':output['path'],
            'output_sha256':output['sha256'],'decoded_frame_count':len(rows),
            'frame_checksum_file':str(checksum_file.resolve()),'frame_checksum_file_sha256':digest(checksum_file),
            'decoded_audio_correlation_at_zero_offset':correlation(driver_pcm,final_pcm)})
    if len(hashes[0])!=len(hashes[1]):
        raise RuntimeError('Different decoded frame counts for same-duration drivers')
    different=sum(a!=b for a,b in zip(*hashes))
    if not different:
        raise RuntimeError('Identical decoded video frames despite different driving audio')
    fps=state['output']['fps']
    dimensions=(180,168) if role=='photo' else (180,320)
    tile_height=dimensions[1]+24
    canvas=Image.new('RGB',(360*4,tile_height),'white')
    draw=ImageDraw.Draw(canvas)
    for index,second in enumerate([1,3,7,15]):
        number=int(second*fps)
        for label,output,offset in [('a',state['output'],0),('b',state['warm_output'],180)]:
            im=frame(media.ffmpeg,output['path'],number,work/f'{label}-{number}.png')
            canvas.paste(im.resize(dimensions),(index*360+offset,24))
        draw.text((index*360+4,3),f'{second}s: audio A | audio B',fill='black')
    contact=work/'a-vs-b.png'
    canvas.save(contact)
    result={'request_id':args.request_id,'role':role,'checks':checks,
        'different_decoded_frames':different,'total_frames':len(hashes[0]),
        'native_driving':state.get('native_driving'),
        'warm_seconds':state.get('warm_seconds'), 'same_loaded_native_models':True,
        'contact':{'path':str(contact.resolve()),'sha256':digest(contact)},
        'scope':'actual separate native renders and current audio correspondence; differing frames alone do not prove lip synchronization',
        'human_lipsync_review':'pending','quality_verified':False}
    write_json(f'docs/evidence/M1/{role}-driver-comparison.json',result)
    print({k:result[k] for k in ['request_id','role','different_decoded_frames','total_frames','warm_seconds','quality_verified']})


if __name__=='__main__':
    main()
