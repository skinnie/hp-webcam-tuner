import sys,time,subprocess,json; sys.path.insert(0,sys.argv[1]); from vmxu import XU
import fcntl,struct
x=XU(); fd=x.fd
SC=(3<<30)|(8<<16)|(ord('V')<<8)|28
def setc(cid,v): fcntl.ioctl(fd,SC,bytearray(struct.pack('Ii',cid,v)))
def dump():
    o={}
    for a in range(0x100,0x500):
        x.set(5,[a&0xff,a>>8,0,0]); o[a]=x.get(3)[0]
    return o
def diff(a,b): return {k:(a[k],b[k]) for k in a if a[k]!=b[k]}
ff=subprocess.Popen(['ffmpeg','-loglevel','error','-f','v4l2','-input_format','mjpeg','-video_size','640x480','-i','/dev/video2','-f','null','-'])
time.sleep(4)
base=dump(); time.sleep(1); base2=dump()
res={'base':base,'drift':diff(base,base2)}
print('DRIFT (auto loops):',{hex(k):v for k,v in res['drift'].items()})
ctrls={'bright':(0x980900,128,200),'contrast':(0x980901,25,70),'sat':(0x980902,155,50),'hue':(0x980903,0,90),
 'gamma':(0x980910,75,45),'wbtemp':(0x98091a,5000,3000),'sharp':(0x98091b,6,0),'backlight':(0x98091c,0,4),'plf':(0x980918,1,2),'zoom':(0x9a090d,0,30)}
noisy=set(res['drift'])
for n,(cid,d,v) in ctrls.items():
    a=dump(); setc(cid,v); time.sleep(1.5); b=dump(); setc(cid,d); time.sleep(1.5)
    dd={hex(k):(hex(p),hex(q)) for k,(p,q) in diff(a,b).items()}
    print(n,dd); res[n]=diff(a,b)
ff.terminate()
json.dump({k:{str(a):b for a,b in v.items()} for k,v in res.items()},open(sys.argv[1]+'/map.json','w'))
