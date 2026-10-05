"""Generate the small application icon from simple original geometry."""
from pathlib import Path
from PIL import Image, ImageDraw

root=Path(__file__).resolve().parents[1]
image=Image.new('RGBA',(256,256),'#131b16')
draw=ImageDraw.Draw(image)
draw.rounded_rectangle((75,96,181,212),20,fill='#dec38c')
draw.polygon(((128,28),(180,104),(156,148),(100,148),(76,104)),fill='#90b998')
draw.rectangle((116,104,140,184),fill='#131b16')
image.save(root/'data/lamp.png')
image.save(root/'data/lamp.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
