import sys,time,json; sys.path.insert(0,sys.argv[1]); from vmxu import XU
x=XU(); out={}; t=time.time()
lo,hi=int(sys.argv[3],0),int(sys.argv[4],0)
for a in range(lo,hi):
    try:
        x.set(5,[a&0xff,a>>8,0,0]); out[a]=x.get(3)[0]
    except OSError: pass
json.dump(out,open(sys.argv[2],'w')); print(len(out),'valid of',hi-lo,'in %.1fs'%(time.time()-t))
