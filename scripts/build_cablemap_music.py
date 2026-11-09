#!/usr/bin/env python3
"""Original gentle ambient instrumental for the CableMap video, no third-party samples."""
import math, sys, wave
import numpy as np
out, duration = sys.argv[1], float(sys.argv[2])
sr=22050
size=int(sr*duration)
buf=np.zeros(size,dtype=np.float32)
rng=np.random.default_rng(42176)
def hz(m): return 440*2**((m-69)/12)
def voice(note,start,seconds,gain,style="pad",echo=False):
    a=int(max(0,start)*sr)
    if a>=size:return
    n=min(int(seconds*sr),size-a)
    if n<=0:return
    t=np.arange(n,dtype=np.float32)/sr
    f=hz(note)
    if style=="pad":
        x=.71*np.sin(2*np.pi*f*t)+.25*np.sin(2*np.pi*f*1.0035*t+.39)+.115*np.sin(2*np.pi*f*2.001*t+1.12)+.045*np.sin(2*np.pi*f*3.003*t+1.81)
        env=np.minimum(1,t/1.65)**1.7*np.minimum(1,np.maximum(0,seconds-t)/2.5)**1.4*(.89+.11*np.sin(2*np.pi*.17*t+.3))
    elif style=="bell":
        x=.75*np.sin(2*np.pi*f*t)+.13*np.sin(2*np.pi*f*2.01*t)+.05*np.sin(2*np.pi*f*3.996*t)
        env=(1-np.exp(-t*14))*np.exp(-t/2.1)*np.minimum(1,np.maximum(0,seconds-t)/.28)
    else:
        x=np.sin(2*np.pi*f*t)+.14*np.sin(2*np.pi*f*2*t)
        env=np.minimum(1,t/.85)*np.minimum(1,np.maximum(0,seconds-t)/2.4)
    v=(gain*x*env).astype(np.float32)
    buf[a:a+n]+=v
    if echo:
        for offset,level in ((.36,.16),(.72,.075)):
            b=a+int(offset*sr); e=min(size,b+n)
            if e>b:buf[b:e]+=v[:e-b]*level
# Eight original chord voicings and delicate upper-register notes, no continuous tone.
chords=[
 (45,[57,60,64,71],[76,72,71,69]),
 (41,[57,60,64,69],[72,76,74,72]),
 (48,[55,59,62,64],[79,76,74,72]),
 (43,[55,59,62,69],[74,71,76,74]),
 (50,[57,60,64,69],[77,76,72,76]),
 (41,[57,60,67,69],[76,72,74,69]),
 (40,[55,59,62,67],[71,74,76,74]),
 (43,[55,57,62,69],[76,74,71,69])]
bar=8.
for k in range(math.ceil(duration/bar)):
    start=k*bar
    root,tones,motif=chords[k%len(chords)]
    voice(root,max(0,start-.2),bar+1.7,.056,"bass")
    for i,note in enumerate(tones):
        voice(note,max(0,start+.24*i-.32),bar+2.45,.035 if i==0 else .029)
    for i,note in enumerate(motif):
        if i==3 and k%3==0:continue
        voice(note,start+.6+i*1.8+(rng.random()-.5)*.15,4.3,.013 if i==0 else .010,"bell",True)
t=np.arange(size,dtype=np.float32)/sr
buf+=(.0018*np.sin(2*np.pi*.047*t)+.0012*np.sin(2*np.pi*.089*t+1.1))
buf*=np.minimum(1,t/3)*np.minimum(1,np.maximum(0,duration-t)/5)
peak=np.max(np.abs(buf))
if peak>.78:buf*=.78/peak
with wave.open(out,"wb") as wav:
    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(sr)
    wav.writeframes(np.int16(buf*32767).tobytes())
print("Original ambient score generated",out,duration,"s")
