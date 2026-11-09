#!/usr/bin/env python3
"""Original upbeat CableMap tech-presentation soundtrack; no third-party samples."""
import math, sys, wave
import numpy as np

out, duration = sys.argv[1], float(sys.argv[2])
sr = 22050
n = int(duration*sr)
audio = np.zeros(n,dtype=np.float32)
rng=np.random.default_rng(36116)
beat=60/114.0
bar=beat*4

def hz(m): return 440*2**((m-69)/12)
def mix(signal, start, gain=1., echo=False):
    offset=round(start*sr)
    if offset>=n:return
    if offset<0:
        signal=signal[-offset:]
        offset=0
    length=min(len(signal),n-offset)
    if length<=0:return
    signal=np.asarray(signal[:length],dtype=np.float32)
    audio[offset:offset+length]+=signal*gain
    if echo:
        for delay,attenuation in ((beat*.75,.16),(beat*1.5,.065)):
            at=offset+round(delay*sr)
            count=min(length,n-at)
            if count>0:audio[at:at+count]+=signal[:count]*gain*attenuation

def synth(midi,seconds,instrument):
    count=max(2,round(seconds*sr))
    t=np.arange(count,dtype=np.float32)/sr
    phase=2*np.pi*hz(midi)*t
    if instrument=="keys":
        x=.63*np.sin(phase)+.19*np.sin(2*phase+.4)+.09*np.sin(3*phase+.6)+.03*np.sin(5*phase+1)
        env=(1-np.exp(-t*45))*(.66*np.exp(-t/.57)+.34*np.exp(-t/1.9))
        env*=np.minimum(1,np.maximum(0,(seconds-t)/.14))
    elif instrument=="pluck":
        x=.78*np.sin(phase)+.23*np.sin(2*phase+.25)+.08*np.sin(3*phase+.5)
        env=(1-np.exp(-t*80))*np.exp(-t/.33)
        env*=np.minimum(1,np.maximum(0,(seconds-t)/.12))
    elif instrument=="bass":
        x=.88*np.sin(phase)+.21*np.sin(2*phase+.09)+.085*np.sin(3*phase)
        env=(1-np.exp(-t*48))*np.exp(-t/.32)
        env*=np.minimum(1,np.maximum(0,(seconds-t)/.13))
    elif instrument=="pad":
        x=.69*np.sin(phase)+.17*np.sin(phase*1.004+.8)+.17*np.sin(2*phase+.4)+.05*np.sin(3*phase+1.4)
        env=np.minimum(1,t/.42)*np.minimum(1,np.maximum(0,(seconds-t)/.48))
    else:raise ValueError(instrument)
    return (x*env).astype(np.float32)

def kick():
    t=np.arange(round(.31*sr),dtype=np.float32)/sr
    f=58+105*np.exp(-t*27)
    phase=2*np.pi*np.cumsum(f)/sr
    tone=np.sin(phase)*np.exp(-t*18)
    click=rng.standard_normal(len(t)).astype(np.float32)*np.exp(-t*120)
    return .75*tone+.03*click

def clap():
    t=np.arange(round(.22*sr),dtype=np.float32)/sr
    noise=rng.standard_normal(len(t)).astype(np.float32)
    high=noise-np.convolve(noise,np.ones(9,dtype=np.float32)/9,mode="same")
    return (.21*high*np.exp(-t*21)*(1+.35*np.sin(2*np.pi*35*t))).astype(np.float32)

def hat(open_hat=False):
    seconds=.19 if open_hat else .075
    t=np.arange(round(seconds*sr),dtype=np.float32)/sr
    noise=rng.standard_normal(len(t)).astype(np.float32)
    high=noise-np.convolve(noise,np.ones(7,dtype=np.float32)/7,mode="same")
    return (.085*high*np.exp(-t*(19 if open_hat else 59))).astype(np.float32)

kick_hit=kick()
clap_hit=clap()
progression=[
 (38,[62,66,69,73],[74,76,78,81,78,76]),
 (35,[59,62,66,71],[78,76,74,73,71,74]),
 (31,[55,59,62,66],[74,78,79,78,76,74]),
 (33,[57,61,64,69],[73,76,78,76,74,73])
]
for b in range(math.ceil(duration/bar)):
    start=b*bar
    bass,chord,melody=progression[(b//2)%4]
    phrase=(b//8)%4
    for note in chord[:3]:
        mix(synth(note-12,bar+.35,"pad"),start,.026 if b>1 else .019)
    for at,weight in ((0.,.033),(1.5,.023),(2.75,.029)):
        for note in chord:
            mix(synth(note,1.38,"keys"),start+at*beat,weight)
    for step,note in ((0,bass),(1.5,bass+12),(2,bass),(2.75,bass+7),(3.5,bass+12)):
        mix(synth(note,.49,"bass"),start+step*beat,.13 if step in (0,2) else .075)
    if b>=2:
        for j,at in enumerate((.5,1.25,2.25,3.0)):
            note=melody[(j+phrase+b%2)%len(melody)]
            mix(synth(note,.58,"pluck"),start+at*beat,.06 if j==0 else .047,echo=j==0)
    if b>=4 and b%2==1:
        mix(synth(chord[-1]+12,1.2,"keys"),start+2.5*beat,.035)
    level=min(1,(b+1)/4)
    for step in range(4):
        mix(kick_hit,start+step*beat,.22*level*(1 if step==0 else .8))
        mix(hat(),start+(step+.5)*beat,.36*level)
        if step in (1,3):mix(clap_hit,start+step*beat,.24*level)
        if b>=4:mix(hat(),start+step*beat,.11*level)
    if b%4==3:mix(hat(True),start+3.75*beat,.24*level)

t=np.arange(n,dtype=np.float32)/sr
audio*=np.minimum(1,t/1.2)*np.minimum(1,np.maximum(0,(duration-t)/3.2))
peak=float(np.max(np.abs(audio)))
if peak>.87:audio*=.87/peak
with wave.open(out,"wb") as w:
    w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr)
    w.writeframes((np.clip(audio,-.99,.99)*32767).astype("<i2").tobytes())
print(f"CableMap bright instrumental: {duration:.2f}s, 114 BPM, peak={float(np.max(np.abs(audio))):.3f}")
