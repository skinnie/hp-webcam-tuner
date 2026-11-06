import fcntl, struct, sys, os
dev=sys.argv[1]
fd=os.open(dev,os.O_RDWR)
def IOWR(t,nr,size): return (3<<30)|(size<<16)|(ord(t)<<8)|nr
QC=IOWR('V',36,68); GC=IOWR('V',27,8); SC=IOWR('V',28,8)
FLAG_NEXT=0x80000000
cid=FLAG_NEXT
def get(i):
    b=bytearray(struct.pack('Ii',i,0)); fcntl.ioctl(fd,GC,b); return struct.unpack('Ii',b)[1]
if len(sys.argv)>2:
    for a in sys.argv[2:]:
        k,v=a.split('='); b=bytearray(struct.pack('Ii',int(k,0),int(v))); fcntl.ioctl(fd,SC,b)
while True:
    b=bytearray(struct.pack('II32siiiiII',cid,0,b'',0,0,0,0,0,0)+b'\0'*0)
    b=bytearray(68); struct.pack_into('I',b,0,cid)
    try: fcntl.ioctl(fd,QC,b)
    except OSError: break
    i,t,name,mn,mx,st,df,fl=struct.unpack_from('II32siiiiI',b)
    try: cur=get(i)
    except OSError as e: cur='err'
    print(hex(i),name.rstrip(b'\0').decode(),'type',t,'min',mn,'max',mx,'step',st,'def',df,'cur',cur,'flags',hex(fl))
    cid=i|FLAG_NEXT
