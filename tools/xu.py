import fcntl, struct, sys, os, ctypes
fd=os.open(sys.argv[1],os.O_RDWR); unit=int(sys.argv[2])
# struct uvc_xu_control_query { __u8 unit; __u8 selector; __u8 query; __u16 size; __u8 *data; }  -> 16 bytes on x86_64
QUERY=(3<<30)|(16<<16)|(ord('u')<<8)|0x21
names={0x81:'CUR',0x82:'MIN',0x83:'MAX',0x84:'RES',0x85:'LEN',0x86:'INFO',0x87:'DEF'}
def q(sel,qq,size):
    buf=ctypes.create_string_buffer(size)
    b=bytearray(struct.pack('BBBxHxxP',unit,sel,qq,size,ctypes.addressof(buf)))
    fcntl.ioctl(fd,QUERY,b); return buf.raw
for sel in range(1,9):
    try:
        ln=struct.unpack('<H',q(sel,0x85,2))[0]; info=q(sel,0x86,1)[0]
        out=[f'sel {sel} len {ln} info {info:#x}']
        for qq in (0x81,0x82,0x83,0x84,0x87):
            try: out.append(names[qq]+'='+q(sel,qq,ln).hex())
            except OSError as e: out.append(names[qq]+'=E%d'%e.errno)
        print(' '.join(out))
    except OSError as e: print('sel',sel,'err',e)
