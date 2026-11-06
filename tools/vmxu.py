import fcntl, struct, sys, os, ctypes
QUERY=(3<<30)|(16<<16)|(ord('u')<<8)|0x21
SET_CUR,GET_CUR=0x01,0x81
class XU:
    def __init__(s,dev='/dev/video2',unit=4): s.fd=os.open(dev,os.O_RDWR); s.unit=unit
    def q(s,sel,qq,data=None,size=4):
        buf=ctypes.create_string_buffer(bytes(data) if data else b'\0'*size,size)
        b=bytearray(struct.pack('BBBxHxxP',s.unit,sel,qq,size,ctypes.addressof(buf)))
        fcntl.ioctl(s.fd,QUERY,b); return buf.raw
    def get(s,sel): return s.q(sel,GET_CUR)
    def set(s,sel,data): s.q(sel,SET_CUR,data)
if __name__=='__main__':
    x=XU()
    print('sel5 get',x.get(5).hex())
    x.set(5,[0xe1,0x01,0,0]); print('sel5 after set',x.get(5).hex())
    try: print('sel3 get',x.get(3).hex())
    except OSError as e: print('sel3 err',e)

def rreg(x,a):
    x.set(5,[a&0xff,0x01,0,0]); return x.get(3)[0]
def wreg(x,a,v):
    x.set(5,[a&0xff,0x01,0,0]); cur=x.get(3); x.set(3,[a&0xff,v&0xff,0x01,cur[3]]); __import__("time").sleep(0.05)
