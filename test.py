from PIL import Image
import glob
import numpy as np

for f in sorted(glob.glob("data/raw/faces/*")):
    im = np.array(Image.open(f).convert("RGB"))
    print(f, "평균밝기:", round(im.mean(), 1), " 표준편차:", round(im.std(), 1))