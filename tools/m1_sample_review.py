"""Objective media correspondence checks, with human quality judgments left pending."""
import argparse
import sys
import wave
from pathlib import Path
from array import array
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops, ImageStat, ImageDraw
from mooc_m1.core import read_json, write_json, run, digest
from mooc_m1.__main__ import setup


def correlation(a, b):
    count = min(len(a),len(b))
    a, b = a[:count], b[:count]
    ma, mb = sum(a)/count, sum(b)/count
    dot = sum((x-ma)*(y-mb) for x,y in zip(a,b))
    denominator = (sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))**0.5
    return dot/denominator if denominator else None


def audio_pcm(ffmpeg, path, output):
    run([ffmpeg,"-y","-v","error","-i",path,"-map","0:a:0","-ac","1","-ar","8000","-c:a","pcm_s16le",output])
    with wave.open(str(output),'rb') as wav:
        samples = array('h',wav.readframes(wav.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples


def frame(ffmpeg, path, number, output):
    run([ffmpeg,"-y","-v","error","-i",path,"-vf",f"select=eq(n\\,{number})","-frames:v","1",output])
    return Image.open(output).convert('RGB')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--photo',default='80cce8da-f59d-40ee-ba91-544097f9fada')
    parser.add_argument('--video',default='687eeec7-7064-44d1-9bfd-b6e8574f5a2c')
    args=parser.parse_args()
    media,adapters,storage=setup(read_json('config/m1.local.json'))
    work=Path(storage)/'correspondence-review'
    work.mkdir(exist_ok=True)
    records={role:read_json(Path(storage)/'requests'/getattr(args,role)/'status.json') for role in ['photo','video']}
    checks={}
    for role,state in records.items():
        driver=state['inputs']['audio']['path']
        video=state['output']['path']
        original=audio_pcm(media.ffmpeg,driver,work/f'{role}-driver.wav')
        final=audio_pcm(media.ffmpeg,video,work/f'{role}-final.wav')
        checks[role]={'request_id':state['request_id'],'driver_audio_sha256':digest(driver),
            'output_sha256':digest(video),'decoded_audio_correlation_at_zero_offset':correlation(original,final),
            'scope':'acoustic waveform correspondence only; does not measure mouth synchronization or voice similarity',
            'quality_verified':False}
    video=records['video']['output']['path']
    source=records['video']['inputs']['video']['path']
    frames=[0,90,210,449,450,451,600,870]
    canvas=Image.new('RGB',(360*4,340*2),'white')
    draw=ImageDraw.Draw(canvas)
    comparisons=[]
    for index,number in enumerate(frames):
        source_number=number if number<450 else 899-number
        a=frame(media.ffmpeg,source,source_number,work/f'source-{number}.png')
        b=frame(media.ffmpeg,video,number,work/f'output-{number}.png')
        x,y=(index%4)*360,(index//4)*340
        canvas.paste(a.resize((180,320)),(x,y+20))
        canvas.paste(b.resize((180,320)),(x+180,y+20))
        draw.text((x+4,y+3),f'source#{source_number} | output#{number}',fill='black')
        # The fixed top and lower bands exclude the face replacement region.
        top=ImageStat.Stat(ImageChops.difference(a.crop((0,0,720,200)),b.crop((0,0,720,200)))).mean
        bottom=ImageStat.Stat(ImageChops.difference(a.crop((0,1000,720,1280)),b.crop((0,1000,720,1280)))).mean
        comparisons.append({'output_frame':number,'source_frame':source_number,
            'top_background_rgb_mean_absolute_error':top,'lower_clothing_rgb_mean_absolute_error':bottom})
    contact=work/'source-vs-output.png'
    canvas.save(contact)
    seam=[]
    previous=None
    for number in range(443,457):
        im=frame(media.ffmpeg,video,number,work/f'seam-{number}.png')
        if previous:
            seam.append({'from_frame':number-1,'to_frame':number,
                'rgb_mean_absolute_frame_change':ImageStat.Stat(ImageChops.difference(previous,im)).mean})
        previous=im
    write_json('docs/evidence/M1/sample-review.json',{
        'audio_correspondence':checks,'video_sequence':{'source_frames':450,'output_frames':900,'fps':30,
            'native_sequence_policy':'forward 0..449 then reverse 449..0; original full frame sequence, mouth area regenerated',
            'boundary_frame':450,'comparisons':comparisons,'seam_frame_changes':seam,
            'contact_sheet':{'path':str(contact.resolve()),'sha256':digest(contact)},
            'visual_review':'contact frames show varying gaze/head pose and similar surrounding source imagery; no scene cut visible at the sampled turnaround',
            'continuous_playback_and_audiovisual_sync':'pending human review'},
        'photo_review':'visible face/head changes in sampled frames; original 180x168 source limits mouth detail; human identity and lipsync pending',
        'full_script_listening':'pending human review; local Whisper-tiny has recognition errors and is not acceptance evidence',
        'quality_verified':False,'m1_passed':False})
    print(checks)


if __name__=='__main__':
    main()
