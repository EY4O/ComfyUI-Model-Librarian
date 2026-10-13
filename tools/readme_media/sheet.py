"""Contact sheet of a GIF: every Nth frame in a grid, for checking."""
import sys

from PIL import Image, ImageSequence

gif, out = sys.argv[1], sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 4
frames = [f.convert("RGB").copy() for f in ImageSequence.Iterator(Image.open(gif))]
step = max(1, len(frames) // (cols * 3))
pick = frames[::step][: cols * 3]
w, h = pick[0].size
tw, th = w // 2, h // 2
sheet = Image.new("RGB", (tw * cols, th * ((len(pick) + cols - 1) // cols)), (40, 40, 40))
for i, f in enumerate(pick):
    sheet.paste(f.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
sheet.save(out)
print(len(frames), "frames; sheet of", len(pick))
