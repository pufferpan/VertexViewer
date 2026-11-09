"""Convert the owner's float WAV into a portable PCM startup resource."""
from pathlib import Path
import struct
import sys
import wave

import numpy as np


def convert(source,target):
    data=Path(source).read_bytes()
    if data[:4]!=b'RIFF' or data[8:12]!=b'WAVE':raise ValueError('需要 RIFF WAV 文件')
    offset=12;fmt=None;audio=None
    while offset+8<=len(data):
        kind,size=struct.unpack_from('<4sI',data,offset)
        chunk=data[offset+8:offset+8+size]
        if len(chunk)!=size:raise ValueError('WAV 数据不完整')
        if kind==b'fmt ':fmt=struct.unpack_from('<HHIIHH',chunk)
        elif kind==b'data':audio=chunk
        offset+=8+size+(size%2)
    if fmt is None or audio is None:raise ValueError('WAV 缺少格式或声音数据')
    tag,channels,rate,_,align,bits=fmt
    if tag!=3 or bits!=32 or align!=channels*4:raise ValueError('需要 32 位浮点 WAV')
    samples=np.frombuffer(audio,'<f4')
    if len(samples)%channels or not np.isfinite(samples).all():raise ValueError('WAV 包含无效采样')
    pcm=np.clip(np.rint(samples.astype(np.float64)*32768),-32768,32767).astype('<i2')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(target),'wb') as output:
        output.setnchannels(channels);output.setsampwidth(2);output.setframerate(rate)
        output.writeframes(pcm.tobytes())
    print(f'{target}: {len(samples)/channels/rate:.3f}s, {rate}Hz, {channels}ch PCM16')


if __name__=='__main__':
    convert(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else Path(__file__).resolve().parents[1]/'assets/audio/OPEN_0.wav')
