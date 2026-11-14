import sys, time, numpy as np
sys.path.insert(0, "../reconstruction")
import geom as G
from gltf_writer import GLBWriter
from snack import Piece, snack_textures
t=time.time()
rng=np.random.default_rng(42)
pieces=[Piece(i, rng).build() for i in range(17)]
print("tris/piece", [len(p.F) for p in pieces][:6], "time", time.time()-t)
res=int(sys.argv[1]) if len(sys.argv)>1 else 2048
alb,hgt,rough,ao,pxmm=snack_textures(pieces,res=res)
print("tex", time.time()-t)
nm=G.normal_map_from_height_image(ndimage_h:=hgt, pxmm) if False else G.normal_map_from_height_image(hgt, pxmm)
W=GLBWriter()
m=W.material("RibbonSeeval_FriedDough", base=W.texture(alb,quality=92), normal=W.texture(nm,quality=90),
             orm=W.texture(np.stack([ao,rough,np.zeros_like(rough)],-1),quality=90))
nodes=[]
for p in pieces:
    N=G.vertex_normals(p.V,p.F); TAN=G.tangents(p.V,N,p.UV,p.F)
    mi=W.mesh_only(f"piece{p.idx}",[dict(V=p.V,N=N,UV=p.UV,TAN=TAN,F=p.F,material=m)])
    i,j=p.idx%6,p.idx//6
    nodes.append(W.node(f"p{p.idx}",mi,translation=[(i-2.5)*38,8,(j-1)*38],rotation=[-0.7071,0,0,0.7071]))
W.group("test",nodes); print(W.write("/tmp/claude-0/-home-user-new/57a6c802-2a6c-5a87-a9e3-175d2c56d5e4/scratchpad/viewer/pieces_test.glb")/1e6,"MB", time.time()-t)
